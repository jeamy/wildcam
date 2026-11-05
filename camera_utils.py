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


# Known battery-powered Reolink series, matched as whole words so names like
# "Garage" or "Logo" do not count ("go" used to match any substring).
_BATTERY_PATTERN = re.compile(r"\b(argus|go|altas|battery|solar|akku)\b", re.IGNORECASE)


def _is_battery_camera(model: str, name: str = "") -> bool:
    """Check if camera is battery-powered based on model/name."""
    return bool(_BATTERY_PATTERN.search(f"{model or ''} {name or ''}"))


def _build_rtsp_url(host: str, port: int = 554, username: str = "", password: str = "", 
                    path: str | None = "h264Preview_01_main", scheme: str = "rtsp") -> str:
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
    
    path = path or ""
    # Ensure path starts with /
    if not path.startswith('/'):
        path = f"/{path}"
    
    return f"{scheme}://{auth}{host}:{port}{path}"


PROXY_RTSP_HOSTS = ("localhost", "127.0.0.1")
PROXY_RTSP_PORT = 8554


def is_proxy_stream_url(rtsp_url: str) -> bool:
    """True if the URL points at the local ReolinkProxy RTSP server."""
    host, port, _user, _password = _parse_rtsp_url(rtsp_url or "")
    return host in PROXY_RTSP_HOSTS and int(port or 0) == PROXY_RTSP_PORT


# Result codes of rtsp_describe_status()
PROXY_READY = "ready"            # 200: stream registered, proxy has connected before
PROXY_UNREACHABLE = "unreachable"  # 503/timeout: proxy cannot reach the camera
PROXY_MISSING = "missing"        # 404: camera not configured in reolinkproxy.env
PROXY_DOWN = "proxy_down"        # RTSP listener not reachable
PROXY_ERROR = "error"


def rtsp_describe_status(rtsp_url: str, timeout: float = 12.0) -> str:
    """Send a single RTSP DESCRIBE and classify the answer.

    Against ReolinkProxy this does not wake a sleeping camera: registered
    streams answer from the cached SDP, unreachable ones answer 503.
    """
    host, port, _user, _password = _parse_rtsp_url(rtsp_url or "")
    if not host:
        return PROXY_ERROR
    try:
        sock = socket.create_connection((host, int(port or 554)), timeout=min(timeout, 3.0))
    except ConnectionRefusedError:
        return PROXY_DOWN
    except OSError:
        return PROXY_DOWN
    try:
        sock.settimeout(timeout)
        request = (
            f"DESCRIBE {rtsp_url} RTSP/1.0\r\n"
            "CSeq: 1\r\n"
            "Accept: application/sdp\r\n"
            "User-Agent: WildCam\r\n\r\n"
        )
        sock.sendall(request.encode("utf-8"))
        first_line = sock.recv(1024).decode("utf-8", "ignore").split("\r\n", 1)[0]
    except (TimeoutError, socket.timeout):
        return PROXY_UNREACHABLE
    except OSError:
        return PROXY_ERROR
    finally:
        sock.close()
    parts = first_line.split()
    code = parts[1] if len(parts) > 1 else ""
    if code == "200":
        return PROXY_READY
    if code == "404":
        return PROXY_MISSING
    if code in ("503", "500", "504"):
        return PROXY_UNREACHABLE
    return PROXY_ERROR


def is_reolink_camera(camera: dict) -> bool:
    """Heuristic: does this camera need the Reolink wake-up / path fallbacks?"""
    if (camera.get("manufacturer") or "").lower() == "reolink":
        return True
    if "reolink" in (camera.get("model") or "").lower():
        return True
    if (camera.get("uid") or "").startswith("9527"):
        return True
    if (camera.get("proxy") or {}).get("type") == "reolinkproxy":
        return True
    url = camera.get("url") or ""
    return "Preview_01_" in url or _parse_rtsp_url(url)[1] == 9000


def with_credentials(uri: str, username: str = "", password: str = "") -> str:
    """Insert (URL-encoded) credentials into an RTSP URI, keeping path and query."""
    u = urlparse(uri, allow_fragments=False)
    if not u.hostname:
        return uri
    path = u.path or "/"
    if u.query:
        path = f"{path}?{u.query}"
    return _build_rtsp_url(
        host=u.hostname,
        port=u.port or 554,
        username=username,
        password=password,
        path=path,
        scheme=u.scheme or "rtsp",
    )


def camera_hosts(camera: dict) -> set[str]:
    """Network addresses a configured camera is known under (URL host, proxy host)."""
    hosts = set()
    host, _port, _user, _password = _parse_rtsp_url(camera.get("url") or "")
    if host and host not in PROXY_RTSP_HOSTS:
        hosts.add(host)
    proxy_host = (camera.get("proxy") or {}).get("host")
    if proxy_host:
        hosts.add(proxy_host)
    return hosts


def find_matching_camera(info: dict, cameras: list[dict]) -> dict | None:
    """Find a configured camera matching a discovery result.

    Order: UID (stable, Reolink), MAC (survives DHCP changes), then IP.
    """
    uid = (info.get("uid") or "").strip().lower()
    mac = (info.get("mac") or "").strip().lower()
    ip = info.get("ip") or ""
    if uid:
        for camera in cameras:
            if (camera.get("uid") or "").strip().lower() == uid:
                return camera
    if mac:
        for camera in cameras:
            if (camera.get("mac") or "").strip().lower() == mac:
                return camera
    if ip:
        for camera in cameras:
            if ip in camera_hosts(camera):
                return camera
    return None


def _reolinkproxy_camera_name(name: str) -> str:
    """Normalize camera name for ReolinkProxy stream path.

    Spaces become "_", characters that would break an RTSP path segment
    ("/", "?", "#", "%", quotes, control chars) are replaced as well. Plain
    names like "D58" stay unchanged.
    """
    cleaned = (name or "Camera").strip().replace(" ", "_")
    cleaned = re.sub(r"[/\\?#%\"'<>\x00-\x1f]", "_", cleaned)
    return cleaned or "Camera"


def _reolinkproxy_rtsp_url(name: str, port: int = 8554) -> str:
    cam_name = _reolinkproxy_camera_name(name)
    return f"rtsp://localhost:{port}/{cam_name}/mainStream"


def _reolinkproxy_proxy_config(rtsp_url: str, name: str, username: str, password: str, model: str = "", manufacturer: str = "") -> dict | None:
    """Build a persistent proxy config for Reolink WLAN/Battery cameras."""
    if is_proxy_stream_url(rtsp_url):
        return None
    host, port, user, pwd = _parse_rtsp_url(rtsp_url)

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
