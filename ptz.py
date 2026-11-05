"""Pan/tilt control: capability detection and movement commands.

Backends:
- ONVIF (Tapo & co., and ReolinkProxy >= 0.2.7 at 127.0.0.1:8002)
- Reolink HTTP API (native Reolink cameras without proxy)

All network calls block; PtzController runs them on its own worker thread
so the GUI never waits for a camera.
"""
import queue
import re
import threading

import requests
import urllib3

from camera_utils import (
    _parse_rtsp_url,
    _tcp_probe,
    _reolinkproxy_camera_name,
    is_proxy_stream_url,
    is_reolink_camera,
)
from onvif import ONVIF_PORTS, OnvifClient, find_onvif_service

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROXY_ONVIF_URL = "http://127.0.0.1:8002/onvif/device_service"

# direction -> (pan, tilt) unit vector
DIRECTIONS = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, 1.0),
    "down": (0.0, -1.0),
}
_REOLINK_OPS = {"left": "Left", "right": "Right", "up": "Up", "down": "Down"}


def camera_has_ptz(camera: dict) -> bool:
    """Effective PTZ flag: explicit "ptz" value, otherwise proxy cameras
    count as pan/tilt (ReolinkProxy cannot tell) and others as fixed."""
    if "ptz" in camera:
        return bool(camera.get("ptz"))
    return is_proxy_stream_url(camera.get("url", ""))


def needs_ptz_detection(camera: dict) -> bool:
    return "ptz" not in camera and not is_proxy_stream_url(camera.get("url", ""))


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

class OnvifPtzBackend:
    def __init__(self, device_url: str, username: str = "", password: str = "",
                 profile_token: str | None = None, speed: float = 0.5):
        self.client = OnvifClient(device_url, username, password, timeout=4.0)
        self.profile_token = profile_token
        self.speed = speed
        self._ptz_url = None

    def _ensure_ready(self):
        if self._ptz_url:
            return
        self.client.sync_time()
        caps = self.client.call(
            self.client.device_url,
            '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>PTZ</Category></GetCapabilities>',
            auth=bool(self.client.username),
        )
        match = re.search(r"<(?:\w+:)?PTZ>\s*<(?:\w+:)?XAddr>([^<]+)<", caps)
        if not match:
            raise RuntimeError("no ONVIF PTZ service")
        ptz_url = match.group(1).strip()
        if not self.profile_token:
            media = self.client.media_url()
            profiles = self.client.call(media, '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>',
                                        auth=bool(self.client.username))
            token = re.search(r'<(?:\w+:)?Profiles[^>]*\btoken="([^"]+)"', profiles)
            if not token:
                raise RuntimeError("no media profile")
            self.profile_token = token.group(1)
        self._ptz_url = ptz_url

    def move(self, direction: str):
        self._ensure_ready()
        pan, tilt = DIRECTIONS[direction]
        self.client.call(
            self._ptz_url,
            '<ContinuousMove xmlns="http://www.onvif.org/ver20/ptz/wsdl">'
            f"<ProfileToken>{self.profile_token}</ProfileToken>"
            '<Velocity><PanTilt xmlns="http://www.onvif.org/ver10/schema" '
            f'x="{pan * self.speed:.2f}" y="{tilt * self.speed:.2f}"/></Velocity>'
            "</ContinuousMove>",
            auth=bool(self.client.username),
        )

    def stop(self):
        self._ensure_ready()
        self.client.call(
            self._ptz_url,
            '<Stop xmlns="http://www.onvif.org/ver20/ptz/wsdl">'
            f"<ProfileToken>{self.profile_token}</ProfileToken>"
            "<PanTilt>true</PanTilt><Zoom>true</Zoom></Stop>",
            auth=bool(self.client.username),
        )


class ReolinkHttpPtzBackend:
    def __init__(self, host: str, username: str, password: str, speed: int = 32):
        self.host = host
        self.username = username
        self.password = password
        self.speed = speed

    def _command(self, op: str):
        last_error = None
        for base in (f"https://{self.host}", f"http://{self.host}"):
            try:
                response = requests.post(
                    f"{base}/api.cgi",
                    params={"cmd": "PtzCtrl", "user": self.username, "password": self.password},
                    json=[{"cmd": "PtzCtrl", "action": 0,
                           "param": {"channel": 0, "op": op, "speed": self.speed}}],
                    timeout=4,
                    verify=False,
                )
                data = response.json()
                if isinstance(data, list) and data and data[0].get("code") == 0:
                    return
                last_error = RuntimeError(str(data)[:200])
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("PtzCtrl failed")

    def move(self, direction: str):
        self._command(_REOLINK_OPS[direction])

    def stop(self):
        self._command("Stop")


def backend_for_camera(camera: dict):
    """Build the PTZ backend for a camera (no network access)."""
    url = camera.get("url", "")
    if is_proxy_stream_url(url):
        profile = f"{_reolinkproxy_camera_name(camera.get('name', ''))}_main"
        return OnvifPtzBackend(PROXY_ONVIF_URL, profile_token=profile)
    host, _port, username, password = _parse_rtsp_url(url)
    if camera.get("ptz_backend") == "reolink" or (camera.get("ptz_backend") is None and is_reolink_camera(camera)):
        return ReolinkHttpPtzBackend(host, username or "", password or "")
    onvif_url = camera.get("onvif_url") or f"http://{host}/onvif/device_service"
    return OnvifPtzBackend(onvif_url, username or "", password or "")


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def _reolink_ptz_ability(host: str, username: str, password: str) -> bool | None:
    for base in (f"https://{host}", f"http://{host}"):
        try:
            response = requests.post(
                f"{base}/api.cgi",
                params={"cmd": "GetAbility", "user": username, "password": password},
                json=[{"cmd": "GetAbility", "action": 0, "param": {"User": {"userName": username}}}],
                timeout=5,
                verify=False,
            )
            data = response.json()
        except Exception:
            continue
        if not (isinstance(data, list) and data and data[0].get("code") == 0):
            continue
        ability = (data[0].get("value") or {}).get("Ability") or {}
        channel = (ability.get("abilityChn") or [{}])[0]
        # "ver" > 0 means the model has the feature ("permit" is the user right).
        return any(int((channel.get(key) or {}).get("ver", 0)) > 0 for key in ("ptzCtrl", "ptzType"))
    return None


def _onvif_ptz(host: str, username: str, password: str) -> tuple[bool, str] | None:
    from discovery import scan_host  # local import: discovery imports PyQt

    open_ports = scan_host(host, ONVIF_PORTS, timeout=1.5)
    device_url = find_onvif_service(host, None, open_ports)
    if not device_url:
        return None
    client = OnvifClient(device_url, username, password)
    client.sync_time()
    try:
        caps = client.call(
            device_url,
            '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>All</Category></GetCapabilities>',
        )
    except Exception:
        return None
    has_service = re.search(r"<(?:\w+:)?PTZ>\s*<(?:\w+:)?XAddr>", caps) is not None
    if not has_service:
        return False, device_url
    try:
        profiles = client.call(client.media_url(), '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>')
    except Exception:
        return None
    return "PTZConfiguration" in profiles, device_url


def detect_ptz(camera: dict) -> dict | None:
    """Detect pan/tilt support. Returns camera fields to store, or None if
    the camera could not be asked (offline, wrong credentials, ...)."""
    url = camera.get("url", "")
    if is_proxy_stream_url(url):
        return None
    host, _port, username, password = _parse_rtsp_url(url)
    if not host:
        return None
    if is_reolink_camera(camera):
        ability = _reolink_ptz_ability(host, username or "", password or "")
        if ability is not None:
            return {"ptz": ability, "ptz_backend": "reolink"}
    result = _onvif_ptz(host, username or "", password or "")
    if result is None:
        # Reachable camera without ONVIF/Reolink API -> cannot be controlled.
        reachable, _reason = _tcp_probe(host, int(_port or 554), timeout=1.5)
        return {"ptz": False} if reachable else None
    has_ptz, device_url = result
    return {"ptz": has_ptz, "ptz_backend": "onvif", "onvif_url": device_url}


# --------------------------------------------------------------------------
# Controller
# --------------------------------------------------------------------------

class PtzController:
    """Serializes move/stop commands for one camera on a daemon thread.

    A backlog is collapsed to the newest command, so a quick press/release
    ends with "stop" instead of replaying old moves.
    """

    def __init__(self, backend, on_error=None):
        self.backend = backend
        self.on_error = on_error
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def move(self, direction: str):
        if direction in DIRECTIONS:
            self._queue.put(("move", direction))

    def stop(self):
        self._queue.put(("stop", None))

    def close(self):
        self._queue.put(None)

    def _run(self):
        while True:
            items = [self._queue.get()]
            while True:
                try:
                    items.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if None in items:
                return
            action, direction = items[-1]  # only the newest command matters
            try:
                if action == "move":
                    self.backend.move(direction)
                else:
                    self.backend.stop()
            except Exception as exc:
                if self.on_error is not None:
                    try:
                        self.on_error(str(exc))
                    except Exception:
                        pass
