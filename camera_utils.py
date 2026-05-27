import json
import re
import socket
import struct
import time
from urllib.parse import quote, unquote, urlparse


def _parse_rtsp_url(rtsp_url: str):
    """Best-effort RTSP URL parsing (host/port/user/pass)."""
    try:
        u = urlparse(rtsp_url, allow_fragments=False)
        if not u.hostname and "#" in rtsp_url:
            sanitized = rtsp_url.replace("#", "%23")
            u = urlparse(sanitized, allow_fragments=False)
        if u.hostname:
            return u.hostname, u.port or 554, unquote(u.username or ""), unquote(u.password or "")
    except Exception:
        pass

    try:
        pattern = r"^[a-z]+://(?:([^:@/]+)(?::([^@/]*))?@)?([^:/]+)(?::(\d+))?"
        match = re.match(pattern, rtsp_url or "", re.IGNORECASE)
        if not match:
            return None, 554, None, None
        return (
            match.group(3),
            int(match.group(4) or 554),
            unquote(match.group(1) or ""),
            unquote(match.group(2) or ""),
        )
    except Exception:
        return None, 554, None, None


def _normalize_rtsp_url(rtsp_url: str) -> str:
    """Normalize RTSP URL to always include explicit port to avoid FFmpeg TCP fallback errors."""
    try:
        u = urlparse(rtsp_url)
        if not u.scheme or u.scheme not in ('rtsp', 'rtsps'):
            return rtsp_url
        
        # Ensure port is explicit
        port = u.port or 554
        host = u.hostname
        if not host:
            return rtsp_url
        
        # Rebuild URL with explicit port
        auth = f"{u.username}:{u.password}@" if u.username else ""
        path = u.path or "/"
        query = f"?{u.query}" if u.query else ""
        
        return f"{u.scheme}://{auth}{host}:{port}{path}{query}"
    except Exception:
        return rtsp_url


def _is_battery_camera(model: str, name: str = "") -> bool:
    """Check if camera is battery-powered based on model/name."""
    if not model and not name:
        return False
    
    search_text = f"{model} {name}".lower()
    
    # Known battery camera series/models
    battery_keywords = [
        "argus",      # Argus series (Argus 2, 3, PT, Eco, Ultra)
        "go",         # Go series (Go, Go Plus, Go PT)
        "altas",      # Altas PT Ultra
        "battery",    # Explicit battery mention
        "solar",      # Solar-powered (usually battery)
    ]
    
    return any(keyword in search_text for keyword in battery_keywords)


def _build_rtsp_url(host: str, port: int = 554, username: str = "", password: str = "", 
                    path: str = "h264Preview_01_main", scheme: str = "rtsp") -> str:
    """Build RTSP URL with proper URL-encoding for credentials containing special characters.
    
    Args:
        host: Camera IP or hostname
        port: RTSP port (default 554)
        username: Username (will be URL-encoded)
        password: Password (will be URL-encoded) 
        path: RTSP path (default h264Preview_01_main)
        scheme: URL scheme (rtsp or rtsps)
    
    Returns:
        Properly formatted RTSP URL with encoded credentials
    """
    # URL-encode credentials to handle special characters like #, @, :, etc.
    # safe='' means encode ALL special characters
    encoded_user = quote(username, safe='') if username else ''
    encoded_pass = quote(password, safe='') if password else ''
    
    # Build auth string
    if encoded_user and encoded_pass:
        auth = f"{encoded_user}:{encoded_pass}@"
    elif encoded_user:
        auth = f"{encoded_user}@"
    else:
        auth = ""
    
    # Ensure path starts with /
    if path and not path.startswith('/'):
        path = f"/{path}"
    
    return f"{scheme}://{auth}{host}:{port}{path}"


def _reolinkproxy_camera_name(name: str) -> str:
    """Normalize camera name for ReolinkProxy stream path."""
    return (name or "Camera").strip().replace(" ", "_")


def _reolinkproxy_rtsp_url(name: str, port: int = 8554) -> str:
    cam_name = _reolinkproxy_camera_name(name)
    return f"rtsp://localhost:{port}/{cam_name}/mainStream"


def _reolinkproxy_proxy_config(rtsp_url: str, name: str, username: str, password: str, uid: str = "", model: str = "", manufacturer: str = "") -> dict | None:
    """Build a persistent proxy config for Reolink WLAN/Battery cameras."""
    host, port, user, pwd = _parse_rtsp_url(rtsp_url)
    if host in ("localhost", "127.0.0.1") and port == 8554:
        return None

    is_reolink = (
        (manufacturer or "").lower() == "reolink"
        or "reolink" in (model or "").lower()
        or port == 9000
    )
    use_reolinkproxy = port == 9000 or _is_battery_camera(model, name)

    if not (is_reolink and use_reolinkproxy and host):
        return None

    proxy_port = int(port or 9000)

    return {
        "type": "reolinkproxy",
        "host": host,
        "port": proxy_port,
        "username": username or user or "",
        "password": password or pwd or "",
        "stream": "main",
        "battery": True,
        "pause_on_client": True,
        "idle_disconnect": True,
        "idle_timeout": "30s",
    }


def normalize_reolinkproxy_camera(camera: dict, username: str = "", password: str = "") -> bool:
    """Normalize a camera dict to use ReolinkProxy when it represents a Reolink battery/Baichuan camera."""
    url = (camera.get("url") or "").strip()
    if not url:
        return False

    proxy_config = _reolinkproxy_proxy_config(
        rtsp_url=url,
        name=camera.get("name", ""),
        username=username,
        password=password,
        uid=camera.get("uid", ""),
        model=camera.get("model", ""),
        manufacturer=camera.get("manufacturer", ""),
    )
    changed = False
    if proxy_config:
        new_url = _reolinkproxy_rtsp_url(camera.get("name", ""))
        if camera.get("url") != new_url:
            camera["url"] = new_url
            changed = True
        if camera.get("proxy") != proxy_config:
            camera["proxy"] = proxy_config
            changed = True
    return changed


def _tcp_probe(host: str, port: int, timeout: float = 0.7) -> tuple[bool, str]:
    """Fast TCP reachability check.

    Returns (ok, reason) where reason is one of: ok, timeout, refused, unreachable, error.
    """
    if not host:
        return False, "error"
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        return True, "ok"
    except ConnectionRefusedError:
        return False, "refused"
    except TimeoutError:
        return False, "timeout"
    except OSError as e:
        # e.g. No route to host, network unreachable, etc.
        if getattr(e, "errno", None) in (101, 113):
            return False, "unreachable"
        return False, "error"


def _ws_discovery(timeout: float = 2.0) -> list[str]:
    """ONVIF/WS-Discovery (UDP 3702)."""
    msg = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Envelope xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns="http://www.w3.org/2003/05/soap-envelope">'
        '<Header><MessageID xmlns="http://schemas.xmlsoap.org/ws/2004/08/addressing">uuid:8253()</MessageID>'
        '<To xmlns="http://schemas.xmlsoap.org/ws/2004/08/addressing">urn:schemas-xmlsoap-org:ws:2004:08:discovery</To>'
        '<Action xmlns="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/discovery/Probe</Action></Header>'
        '<Body><Probe xmlns="http://schemas.xmlsoap.org/ws/2004/08/discovery"><Types>tds:Device</Types></Probe></Body></Envelope>'
    )
    ips = set()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(msg.encode(), ("239.255.255.250", 3702))
        
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                ips.add(addr[0])
            except socket.timeout:
                break
    except Exception:
        pass
    finally:
        if sock is not None:
            sock.close()
    return list(ips)


def _ssdp_discovery(timeout: float = 2.0) -> list[str]:
    """UPnP/SSDP Discovery (UDP 1900)."""
    msg = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 2\r\n'
        'ST: ssdp:all\r\n'
        '\r\n'
    )
    ips = set()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.sendto(msg.encode(), ("239.255.255.250", 1900))
        
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                ips.add(addr[0])
            except socket.timeout:
                break
    except Exception:
        pass
    finally:
        if sock is not None:
            sock.close()
    return list(ips)


def _udp_reolink_probe(ip: str, timeout: float = 2.0) -> list | dict | None:
    """Sendet ein Reolink UDP Discovery Paket an eine spezifische oder Broadcast IP."""
    ports = [9000, 10000, 2000]
    
    # Discovery JSON Payloads (GetDevInfo und Search)
    payloads = [
        [{"cmd": "GetDevInfo", "action": 0, "param": {}}],
        {"cmd": "GetDevInfo", "action": 0, "param": {}},
        [{"cmd": "Search", "action": 0, "param": {}}],
        {"cmd": "Search", "action": 0, "param": {}}
    ]
    
    results = []
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    if ip == "255.255.255.255":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    for port in ports:
        for cmd_data in payloads:
            data = json.dumps(cmd_data).encode('utf-8')
            for endian in ['<', '>']:
                header = struct.pack(endian + "2sHHHII", b"BC", 0, 1, 0, len(data), 0)
                payload = header + data
                try:
                    # Weck-Schuss
                    sock.sendto(b"\x00" * 32, (ip, port))
                    sock.sendto(payload, (ip, port))
                    
                    while True:
                        try:
                            resp_data, addr = sock.recvfrom(4096)
                        except socket.timeout:
                            break
                            
                        if len(resp_data) >= 16:
                            idx = -1
                            for i in range(len(resp_data) - 1):
                                if resp_data[i:i+2].lower() == b"bc":
                                    for j in range(i+2, min(i+48, len(resp_data))):
                                        if resp_data[j] in (ord('['), ord('{')):
                                            idx = j
                                            break
                                    if idx != -1:
                                        break
                            
                            if idx != -1:
                                content = resp_data[idx:].decode('utf-8', 'ignore')
                                if content.startswith('['):
                                    end = content.rfind(']')
                                else:
                                    end = content.rfind('}')
                                
                                if end != -1:
                                    try:
                                        res = json.loads(content[:end+1])
                                        info = None
                                        # Wir suchen nach DevInfo oder Search-Response
                                        val = res[0].get('value', {}) if isinstance(res, list) else res.get('value', {})
                                        info = val.get('DevInfo') or val.get('SearchResult') or val
                                        
                                        if info and (info.get('name') or info.get('serial') or info.get('mac')):
                                            info['remote_ip'] = addr[0]
                                            if ip != "255.255.255.255":
                                                sock.close()
                                                return info
                                            if info.get('remote_ip') not in [r.get('remote_ip') for r in results]:
                                                results.append(info)
                                    except Exception:
                                        pass
                        if ip != "255.255.255.255":
                            break
                except Exception:
                    break
            if ip != "255.255.255.255" and results:
                break
    
    sock.close()
    return results if ip == "255.255.255.255" else (results[0] if results else None)


def _udp_reolink_wake(ip: str, uid: str = ""):
    """Sendet einen intensiven Weck-Burst an eine Reolink Kamera."""
    if not ip:
        return
    sock = None
    try:
        # Falls UID vorhanden, bauen wir ein echtes Abfrage-Paket
        payload = b""
        if uid:
            msg = [{"cmd": "GetDevInfo", "action": 0, "param": {}}]
            data = json.dumps(msg).encode('utf-8')
            header = struct.pack("<2sHHHII", b"BC", 0, 1, 0, len(data), 0)
            payload = header + data

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Wir pingen alle relevanten Ports mehrfach
        for port in [9000, 10000, 8000]:
            for _ in range(5):
                # Null-Bytes zum "Aufwecken" des WLAN/PIR
                sock.sendto(b"\x00" * 64, (ip, port))
                if payload:
                    # Gezielte Abfrage mit UID (Baichuan)
                    sock.sendto(payload, (ip, port))
                else:
                    # Generischer Header
                    h = struct.pack("<2sHHHII", b"BC", 0, 1, 0, 0, 0)
                    sock.sendto(h, (ip, port))
                time.sleep(0.02)
    except Exception:
        pass
    finally:
        if sock is not None:
            sock.close()
