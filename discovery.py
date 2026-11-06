import errno
import ipaddress
import platform
import re
import selectors
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3
from PyQt6.QtCore import QThread, pyqtSignal

from i18n import tr
from netvue import DEFAULT_PORT as NETVUE_PORT, build_netvue_url, probe_netvue
from onvif import ONVIF_PORTS, probe_onvif_device, ws_discovery

# 9000 = Reolink Baichuan (battery/WLAN cameras often expose nothing else),
# 2020 = Tapo ONVIF, 8899 = ONVIF on many OEM cameras.
# 5555 = Netvue LAN protocol (no RTSP/ONVIF, see netvue.py).
DEFAULT_SCAN_PORTS = (554, 8554, 80, 443, 8000, 9000, 2020, 8899, NETVUE_PORT)
RTSP_PORTS = (554, 8554)
REOLINK_BAICHUAN_PORT = 9000

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# connect_ex() results meaning "connection in progress" (POSIX / Windows).
_CONNECT_IN_PROGRESS = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035}


def local_ipv4_addresses() -> set[str]:
    """IPv4 addresses of this machine (the scan must not list the host itself,
    e.g. ReolinkProxy's RTSP/ONVIF ports)."""
    addresses = {"127.0.0.1"}
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass
    return addresses


def _is_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def scan_host(ip: str, ports, timeout: float = 0.5, should_stop=lambda: False) -> list[int]:
    """TCP connect scan of all ``ports`` at once (non-blocking), so one host
    costs ~``timeout`` instead of ``len(ports) * timeout``."""
    if should_stop():
        return []
    pending: dict[socket.socket, int] = {}
    open_ports = []
    try:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            result = sock.connect_ex((ip, port))
            if result == 0:
                open_ports.append(port)
                sock.close()
            elif result in _CONNECT_IN_PROGRESS:
                pending[sock] = port
            else:
                sock.close()
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            for sock in pending:
                selector.register(sock, selectors.EVENT_WRITE)
            while pending and not should_stop():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                for key, _events in selector.select(remaining):
                    sock = key.fileobj
                    port = pending.pop(sock)
                    selector.unregister(sock)
                    if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                        open_ports.append(port)
                    sock.close()
    except (OSError, ValueError):
        pass
    finally:
        for sock in pending:
            sock.close()
    order = {port: index for index, port in enumerate(ports)}
    return sorted(open_ports, key=lambda port: order.get(port, 0))


def _is_reolink_api_reply(data) -> bool:
    return isinstance(data, list) and bool(data) and isinstance(data[0], dict) and "cmd" in data[0]


def reolink_api_info(ip: str, open_ports, username: str = "", password: str = "", timeout: float = 4.0) -> dict | None:
    """Identify a Reolink camera via its HTTP API.

    Step 1 is always unauthenticated: a Reolink camera answers "please login
    first" (a JSON list with "cmd"). Only such a device gets the credentials
    in step 2 (GetDevInfo -> model/name, GetP2p -> UID for ReolinkProxy), so
    the password is never sent to routers, NAS boxes etc. HTTPS is preferred.
    """
    bases = []
    if 443 in open_ports:
        bases.append(f"https://{ip}")
    if 80 in open_ports:
        bases.append(f"http://{ip}")
    for base in bases:
        try:
            response = requests.get(f"{base}/api.cgi", params={"cmd": "GetDevInfo"}, timeout=timeout, verify=False)
            if not _is_reolink_api_reply(response.json()):
                continue
        except Exception:
            continue
        info = {"manufacturer": "Reolink"}
        if not username:
            return info
        try:
            response = requests.post(
                f"{base}/api.cgi",
                params={"cmd": "GetDevInfo", "user": username, "password": password},
                json=[
                    {"cmd": "GetDevInfo", "action": 0, "param": {}},
                    {"cmd": "GetP2p", "action": 0, "param": {}},
                ],
                timeout=timeout,
                verify=False,
            )
            data = response.json()
        except Exception:
            return info
        for item in data if _is_reolink_api_reply(data) else []:
            value = item.get("value") or {}
            dev_info = value.get("DevInfo") or {}
            p2p = value.get("P2p") or {}
            if dev_info:
                info["name"] = dev_info.get("name", "")
                info["model"] = dev_info.get("model", "")
            if p2p.get("uid"):
                info["uid"] = p2p["uid"]
        return info
    return None


def _normalize_mac(mac: str) -> str:
    mac = mac.strip().lower().replace("-", ":")
    parts = mac.split(":")
    if len(parts) != 6:
        return ""
    mac = ":".join(part.zfill(2) for part in parts)
    return "" if mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") else mac


def neighbor_macs() -> dict[str, str]:
    """Best-effort IP -> MAC from the OS neighbor (ARP) table.

    MACs seen for several IPs (WLAN repeaters in MAC-NAT mode) are dropped,
    they would make different cameras look identical.
    """
    macs = _raw_neighbor_macs()
    counts: dict[str, int] = {}
    for mac in macs.values():
        counts[mac] = counts.get(mac, 0) + 1
    return {ip: mac for ip, mac in macs.items() if counts[mac] == 1}


def _raw_neighbor_macs() -> dict[str, str]:
    macs: dict[str, str] = {}
    try:
        with open("/proc/net/arp", encoding="ascii") as f:
            next(f, None)
            for line in f:
                fields = line.split()
                if len(fields) >= 4:
                    mac = _normalize_mac(fields[3])
                    if mac:
                        macs[fields[0]] = mac
        if macs:
            return macs
    except OSError:
        pass
    try:
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        output = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=3, **kwargs).stdout
    except Exception:
        return macs
    pattern = re.compile(r"\(?(\d+\.\d+\.\d+\.\d+)\)?\s+(?:at\s+)?([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})")
    for ip, mac in pattern.findall(output):
        mac = _normalize_mac(mac)
        if mac:
            macs[ip] = mac
    return macs


def identify_host(ip: str, open_ports: list[int], onvif_info: dict | None,
                  username: str = "", password: str = "", mac: str = "") -> dict | None:
    """Combine Reolink API, ONVIF and open ports into one camera record.

    Returns None for hosts that do not look like a camera (e.g. routers or
    NAS boxes that only expose HTTP).
    """
    reolink = reolink_api_info(ip, open_ports, username, password)
    onvif = {}
    if onvif_info or any(port in open_ports for port in ONVIF_PORTS):
        onvif = probe_onvif_device(ip, onvif_info, username, password, open_ports)
    has_rtsp = any(port in open_ports for port in RTSP_PORTS)
    has_baichuan = REOLINK_BAICHUAN_PORT in open_ports

    if not (reolink or onvif or onvif_info or has_rtsp or has_baichuan):
        # Netvue: only the proprietary LAN port; confirm by protocol so that
        # other devices on 5555 (e.g. Android ADB) are not listed.
        if NETVUE_PORT in open_ports and probe_netvue(ip):
            return {
                "ip": ip,
                "ports": sorted(open_ports),
                "name": tr("camera.default_name.ip", ip=ip),
                "model": "Netvue",
                "manufacturer": "Netvue",
                "uid": "",
                "mac": mac,
                "stream_uri": build_netvue_url(ip, "", ""),
            }
        return None

    reolink = reolink or {}
    scope = onvif_info or {}
    manufacturer = reolink.get("manufacturer") or onvif.get("manufacturer") or ""
    if not manufacturer and has_baichuan:
        manufacturer = "Reolink"
    if not manufacturer and (onvif or onvif_info):
        manufacturer = "ONVIF"
    if not manufacturer:
        manufacturer = tr("camera.meta.rtsp_camera") if has_rtsp else tr("camera.meta.unknown")

    return {
        "ip": ip,
        "ports": sorted(open_ports),
        "name": reolink.get("name") or scope.get("name") or tr("camera.default_name.ip", ip=ip),
        "model": reolink.get("model") or onvif.get("model") or scope.get("hardware") or tr("camera.meta.unknown"),
        "manufacturer": manufacturer,
        "uid": reolink.get("uid", ""),
        "mac": mac or _normalize_mac(scope.get("mac", "")),
        "stream_uri": onvif.get("stream_uri", ""),
    }


class CameraDiscoveryThread(QThread):
    """Thread für automatische Kamera-Suche im Netzwerk"""
    camera_found = pyqtSignal(dict)  # {ip, name, model, manufacturer, ports, uid, mac, stream_uri}
    progress_update = pyqtSignal(int, str)
    scan_complete = pyqtSignal(int)

    def __init__(self, network_range, ports=None, username="admin", password="", port_timeout=0.8,
                 known_hosts=()):
        super().__init__()
        # Hosts of already configured cameras: scanned again with a longer
        # timeout because WLAN cameras often miss the fast bulk scan.
        self.known_hosts = [h for h in known_hosts if _is_ipv4(h)]
        self.network_range = network_range
        self.ports = tuple(ports or DEFAULT_SCAN_PORTS)
        self.username = username
        self.password = password
        self.port_timeout = port_timeout
        self.running = False
        self.found_cameras = []

    def _stopped(self) -> bool:
        return not self.running

    def run(self):
        self.running = True
        self.found_cameras = []
        try:
            self._run_scan()
        except Exception as e:
            self.progress_update.emit(100, tr("scan.error", error=str(e)))
        if self.running:
            self.scan_complete.emit(len(self.found_cameras))

    def _run_scan(self):
        local_ips = local_ipv4_addresses()
        network = ipaddress.ip_network(self.network_range, strict=False)

        # 1. ONVIF WS-Discovery (multicast) - finds ONVIF cameras with name/model.
        self.progress_update.emit(2, tr("scan.discovery"))
        onvif_hosts = {
            ip: info
            for ip, info in ws_discovery(timeout=3.0).items()
            if ip not in local_ips and info.get("name") != "ReolinkProxy"
        }
        if self._stopped():
            return

        # 2. Parallel port scan of the subnet.
        hosts = [str(ip) for ip in network.hosts() if str(ip) not in local_ips]
        hosts += [ip for ip in onvif_hosts if ip not in hosts]
        open_ports: dict[str, list[int]] = {}
        pool = ThreadPoolExecutor(max_workers=32)
        try:
            futures = {
                pool.submit(scan_host, ip, self.ports, self.port_timeout, self._stopped): ip
                for ip in hosts
            }
            for done, future in enumerate(as_completed(futures), start=1):
                if self._stopped():
                    return
                ports = future.result()
                if ports:
                    open_ports[futures[future]] = ports
                if done % 8 == 0 or done == len(futures):
                    progress = 5 + int(done / max(1, len(futures)) * 70)
                    self.progress_update.emit(progress, tr("scan.ports", done=done, total=len(futures)))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        # 2b. Retry known camera hosts slowly (two attempts, longer timeout).
        retry = [ip for ip in self.known_hosts if ip not in local_ips]
        if retry and not self._stopped():
            # Ports are merged: a flaky host may answer on different ports each time.
            with ThreadPoolExecutor(max_workers=min(16, len(retry))) as retry_pool:
                for _attempt in range(2):
                    if self._stopped():
                        break
                    results = retry_pool.map(lambda ip: (ip, scan_host(ip, self.ports, 1.5, self._stopped)), retry)
                    for ip, ports in results:
                        if ports:
                            merged = set(open_ports.get(ip, [])) | set(ports)
                            open_ports[ip] = [port for port in self.ports if port in merged]

        # 3. Identify candidates (Reolink API, ONVIF) in parallel.
        candidates = sorted(set(open_ports) | set(onvif_hosts), key=lambda ip: tuple(int(p) for p in ip.split(".")))
        macs = neighbor_macs()
        pool = ThreadPoolExecutor(max_workers=16)
        try:
            futures = {
                pool.submit(
                    identify_host, ip, open_ports.get(ip, []), onvif_hosts.get(ip),
                    self.username, self.password, macs.get(ip, ""),
                ): ip
                for ip in candidates
            }
            for done, future in enumerate(as_completed(futures), start=1):
                if self._stopped():
                    return
                ip = futures[future]
                self.progress_update.emit(75 + int(done / max(1, len(futures)) * 25), tr("scan.checking", ip=ip))
                try:
                    camera_info = future.result()
                except Exception:
                    camera_info = None
                if camera_info:
                    self.found_cameras.append(camera_info)
                    self.camera_found.emit(camera_info)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def stop(self):
        """Scan stoppen"""
        self.running = False
