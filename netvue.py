"""Local LAN client for Netvue cameras (e.g. Orb Mini).

Netvue cameras offer no RTSP/ONVIF. The Netvue app however streams live video
directly over the LAN: TCP port 5555, a small proprietary protocol
(reconstructed from the Netvue Android app 5.27, NvCameraLANService):

Packet = 16-byte header + body, all little endian:
    0  uint32  body size
    4  uint32  sequence (0)
    8  4 bytes crc (0)
    12 uint16  flag (0 = plain body)
    14 uint16  type: 200 = command (JSON), 201 = media data

Command body: JSON array of units {"Q": type, "V": version, "P": [...]}
(the camera answers with "A" instead of "Q").
    login           Q=1  V=1  P=[local_key, random, user, ip, port]
    select channel  Q=3  V=2  P=[1 (live), [[1, q], [2, q]], [start, end]]
    heartbeat       Q=15 V=1  P=[]
    error (camera)  A=11       P=[code]  1 = key invalid, 4 = too many sessions

Media body: byte 0 = frame_type << 4 | flags (bit0 key frame),
bytes 1..4 = pts (uint32 LE), rest = payload. frame_type 1 = H.264 video
(Annex B), 2 = AAC/PCM audio.

The local key and user id are stored by the Netvue app per camera and can be
read from the app log (``adb logcat | grep NvCameraLANService``) while the
live view is open: ``doLogin ... user:<USER>, ... localKey:<KEY>``.
"""

from __future__ import annotations

import json
import random
import re
import socket
import struct
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

DEFAULT_PORT = 5555
TYPE_COMMAND = 200
TYPE_DATA = 201
FRAME_VIDEO = 1
FRAME_AUDIO = 2

CMD_LOGIN = 1
CMD_SELECT_CHANNEL = 3
CMD_ERROR = 11
CMD_HEARTBEAT = 15

# P[0] of an error unit (ENvCameraCMDError in the app)
CAMERA_ERRORS = {
    0: "unknown error",
    1: "local key invalid",
    2: "playback file not found",
    3: "codec error",
    4: "too many sessions",
}

QUALITY_AUTO = 0
QUALITY_HD = 1
QUALITY_BALANCE = 2
QUALITY_SD = 3

URL_SCHEME = "netvue"
_SECONDS_PER_YEAR = 365 * 24 * 3600


class NetvueError(Exception):
    pass


def is_netvue_url(url: str) -> bool:
    return str(url or "").lower().startswith(URL_SCHEME + "://")


def build_netvue_url(host: str, user: str, key: str, port: int = DEFAULT_PORT, quality: int = QUALITY_HD) -> str:
    """netvue://<user>:<local_key>@<host>:<port>?quality=<q>"""
    url = f"{URL_SCHEME}://{quote(user, safe='')}:{quote(key, safe='')}@{host}:{int(port)}"
    if quality != QUALITY_HD:
        url += f"?quality={int(quality)}"
    return url


def parse_netvue_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme.lower() != URL_SCHEME or not parsed.hostname:
        raise NetvueError(f"no netvue URL: {url}")
    query = parse_qs(parsed.query)
    try:
        quality = int(query.get("quality", [QUALITY_HD])[0])
    except ValueError:
        quality = QUALITY_HD
    return {
        "host": parsed.hostname,
        "port": parsed.port or DEFAULT_PORT,
        "user": unquote(parsed.username or ""),
        "key": unquote(parsed.password or ""),
        "quality": quality,
    }


def _packet(body: bytes, ptype: int = TYPE_COMMAND) -> bytes:
    return struct.pack("<IIIHH", len(body), 0, 0, 0, ptype) + body


def _command(*units: dict) -> bytes:
    return _packet(json.dumps(list(units), separators=(",", ":")).encode())


def probe_netvue(host: str, port: int = DEFAULT_PORT, timeout: float = 2.0) -> bool:
    """True if host:port answers like a Netvue camera.

    Sends a login with an invalid key; a Netvue camera replies with a command
    packet (error "key invalid"). Nothing is changed on the camera.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            unit = {"Q": CMD_LOGIN, "V": 1, "P": ["0" * 16, 0, "wildcam-probe", host, port]}
            sock.sendall(_command(unit))
            head = b""
            while len(head) < 16:
                chunk = sock.recv(16 - len(head))
                if not chunk:
                    return False
                head += chunk
            size, _seq, _crc, _flag, ptype = struct.unpack("<IIIHH", head)
            if ptype != TYPE_COMMAND or not 0 < size < 4096:
                return False
            body = b""
            while len(body) < size:
                chunk = sock.recv(size - len(body))
                if not chunk:
                    return False
                body += chunk
            units = json.loads(body.decode("utf-8"))
            return isinstance(units, list) and bool(units) and isinstance(units[0], dict) and "A" in units[0]
    except (OSError, ValueError):
        return False


class NetvueClient:
    """Blocking client: connect(), login(), start_live(), then read_frame()."""

    def __init__(self, host: str, user: str, key: str, port: int = DEFAULT_PORT,
                 quality: int = QUALITY_HD, timeout: float = 10.0):
        self.host = host
        self.port = int(port)
        self.user = user or "localUser"
        self.key = key
        self.quality = int(quality)
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.channels = None
        self._send_lock = threading.Lock()
        self._last_heartbeat = 0.0

    # -- connection -----------------------------------------------------
    def connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _send(self, data: bytes):
        if self.sock is None:
            raise NetvueError("not connected")
        with self._send_lock:
            self.sock.sendall(data)

    def _recv_exact(self, size: int) -> bytes:
        buf = bytearray()
        while len(buf) < size:
            chunk = self.sock.recv(size - len(buf))
            if not chunk:
                raise NetvueError("connection closed by camera")
            buf += chunk
        return bytes(buf)

    def read_packet(self) -> tuple[int, int, bytes]:
        head = self._recv_exact(16)
        size, _seq, _crc, flag, ptype = struct.unpack("<IIIHH", head)
        if ptype > 1106 or size > 8 * 1024 * 1024:
            raise NetvueError(f"invalid packet: type={ptype} size={size}")
        body = self._recv_exact(size) if size else b""
        return ptype, flag, body

    # -- protocol -------------------------------------------------------
    def _wait_command(self, ack_type: int, deadline: float) -> dict:
        while time.monotonic() < deadline:
            ptype, _flag, body = self.read_packet()
            if ptype != TYPE_COMMAND:
                continue
            try:
                units = json.loads(body.decode("utf-8", "replace"))
            except ValueError:
                continue
            for unit in units if isinstance(units, list) else [units]:
                if not isinstance(unit, dict):
                    continue
                kind = unit.get("A", unit.get("Q"))
                if kind == ack_type:
                    return unit
                if kind == CMD_ERROR:
                    params = unit.get("P") or [0]
                    code = params[0] if params else 0
                    raise NetvueError(CAMERA_ERRORS.get(code, f"camera error {code}"))
        raise NetvueError(f"no answer from camera (waiting for {ack_type})")

    def login(self):
        unit = {"Q": CMD_LOGIN, "V": 1,
                "P": [self.key, random.randint(-2**31, 2**31 - 1), self.user, self.host, self.port]}
        self._send(_command(unit))
        ack = self._wait_command(CMD_LOGIN, time.monotonic() + self.timeout)
        if ack.get("C", 0) != 0:
            raise NetvueError(f"login rejected (code {ack.get('C')}), local key invalid?")

    def start_live(self, audio: bool = False):
        now = int(time.time())
        media = [[FRAME_VIDEO, self.quality]]
        if audio:
            media.append([FRAME_AUDIO, self.quality])
        unit = {"Q": CMD_SELECT_CHANNEL, "V": 2, "P": [1, media, [now, now + _SECONDS_PER_YEAR]]}
        self._send(_command(unit))
        ack = self._wait_command(CMD_SELECT_CHANNEL, time.monotonic() + self.timeout)
        if ack.get("C", 0) != 0:
            raise NetvueError(f"live stream rejected (code {ack.get('C')})")
        self.channels = ack.get("P")
        self._last_heartbeat = time.monotonic()

    def heartbeat_if_due(self, interval: float = 10.0):
        now = time.monotonic()
        if now - self._last_heartbeat >= interval:
            self._send(_command({"Q": CMD_HEARTBEAT, "V": 1, "P": []}))
            self._last_heartbeat = now

    def read_frame(self) -> tuple[int, bool, int, bytes]:
        """Next media frame: (frame_type, key_frame, pts, payload)."""
        while True:
            self.heartbeat_if_due()
            ptype, flag, body = self.read_packet()
            if ptype != TYPE_DATA or len(body) < 5:
                continue
            if flag:
                raise NetvueError("encrypted media packets are not supported")
            frame_type = body[0] >> 4
            key_frame = bool(body[0] & 1)
            pts = struct.unpack_from("<I", body, 1)[0]
            return frame_type, key_frame, pts, body[5:]

    def open_live(self, audio: bool = False):
        self.connect()
        self.login()
        self.start_live(audio=audio)
        return self


class NetvueBridge:
    """Serves a Netvue camera's H.264 stream on 127.0.0.1 for OpenCV/FFmpeg.

    ``url`` (tcp://127.0.0.1:<port>) can be opened with cv2.VideoCapture; each
    client gets its own camera connection, starting at the next key frame.
    """

    def __init__(self, netvue_url: str):
        self.params = parse_netvue_url(netvue_url)
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self._server.settimeout(1.0)
        self.port = self._server.getsockname()[1]
        self.url = f"tcp://127.0.0.1:{self.port}"
        self.error: str | None = None
        self._running = True
        self._client: NetvueClient | None = None
        self._thread = threading.Thread(target=self._serve, name="netvue-bridge", daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                conn, _addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._pump(conn)
            except Exception as exc:  # reported via .error, the reader sees EOF
                self.error = str(exc)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
                if self._client is not None:
                    self._client.close()
                    self._client = None

    def _pump(self, conn: socket.socket):
        p = self.params
        client = NetvueClient(p["host"], p["user"], p["key"], p["port"], p["quality"])
        self._client = client
        client.open_live(audio=False)
        self.error = None
        started = False
        while self._running:
            frame_type, key_frame, _pts, payload = client.read_frame()
            if frame_type != FRAME_VIDEO or not payload:
                continue
            if not started:
                if not key_frame:
                    continue
                started = True
            conn.sendall(payload)

    def close(self):
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass
        if self._client is not None:
            self._client.close()


_LOGIN_LOG = re.compile(
    r"doLogin.*?user:(?P<user>[^,\s]*),.*?target:(?P<host>[0-9.]+):(?P<port>\d+),.*?localKey:(?P<key>[^,\s]+)"
)


def urls_from_app_log(text: str) -> list[str]:
    """netvue:// URLs from Netvue app log lines (``adb logcat -d``)."""
    urls = []
    for match in _LOGIN_LOG.finditer(text):
        if match["key"] == "null":
            continue
        url = build_netvue_url(match["host"], match["user"], match["key"], int(match["port"]))
        if url not in urls:
            urls.append(url)
    return urls


def _main():
    import argparse
    import os
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "from-log":
        # adb logcat -d | python netvue.py from-log
        urls = urls_from_app_log(sys.stdin.read())
        if not urls:
            print("no Netvue login found - open the live view in the Netvue app first", file=sys.stderr)
            sys.exit(1)
        print("\n".join(urls))
        return

    ap = argparse.ArgumentParser(description="Record a few seconds of H.264 from a Netvue camera "
                                             "(or: adb logcat -d | python netvue.py from-log)")
    ap.add_argument("host")
    ap.add_argument("--user", default=os.environ.get("NETVUE_USER", ""))
    ap.add_argument("--key", default=os.environ.get("NETVUE_KEY", ""), help="local key (or NETVUE_KEY env)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--quality", type=int, default=QUALITY_HD)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--out", default="netvue_test.h264")
    args = ap.parse_args()
    if not args.key:
        ap.error("local key missing (--key or NETVUE_KEY)")

    client = NetvueClient(args.host, args.user, args.key, args.port, args.quality)
    client.connect()
    print("connected")
    client.login()
    print("login ok")
    client.start_live()
    print("channels:", client.channels)
    frames = keys = size = 0
    started = False
    end = time.monotonic() + args.seconds
    with open(args.out, "wb") as f:
        while time.monotonic() < end:
            frame_type, key_frame, _pts, payload = client.read_frame()
            if frame_type != FRAME_VIDEO:
                continue
            if not started and not key_frame:
                continue
            started = True
            f.write(payload)
            frames += 1
            keys += key_frame
            size += len(payload)
    client.close()
    print(f"{frames} video frames ({keys} key frames, {size / 1024:.0f} KiB) -> {args.out}")


if __name__ == "__main__":
    _main()
