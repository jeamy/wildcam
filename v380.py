"""V380/Macrovideo LAN video (D57 verified: device v32, comm v20, HEVC).

Discovery: NVDEVSEARCH^100 -> UDP 10008, reply on local UDP 10009.
Auth: 1167/1168; fresh TCP stream connection: 301/401 then 303.
Protocol references and live evidence: docs/d57-v380-analysis.md.
Only the verified v31/v32, communication-v20 media variant is supported.
"""
from __future__ import annotations

import errno
import secrets
import socket
import struct
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_PORT = 8800
_DISCOVERY_LOCK = threading.Lock()
_MAX_FRAME = 16 * 1024 * 1024
PTZ_PULSE_SECONDS = 0.35
# Battery D57: woken only by the vendor cloud (V380 Pro app). About 20-30 s
# after the last stream ends it stops answering TCP; a stream started while it
# dozes stalls after a few seconds. Both mean "asleep", not a broken stream.
SLEEP_STALL_WINDOW = 20.0  # burst (~5 s) + 8 s read timeout + login
_ASLEEP_ERRNOS = {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ETIMEDOUT}
_PTZ_AXES = {
    'left': (1001, 1000), 'right': (1002, 1000),
    'up': (1000, 1003), 'down': (1000, 1004),
}


def ptz_packet(direction=None):
    """Command 170 acts on the movable lens; channel 0 is not a view index."""
    pan, tilt = (1000, 1000) if direction is None else _PTZ_AXES[direction]
    return struct.pack('<I6H', 170, 1000, 1000, pan, tilt, 0, 1)



class V380Error(Exception):
    def __init__(self, message, *, permanent=False, asleep=False, stalled=False):
        super().__init__(message)
        self.permanent = permanent
        self.asleep = asleep    # camera does not answer TCP at all
        self.stalled = stalled  # camera stopped sending mid-session


def is_v380_url(url):
    return str(url or '').lower().startswith('v380://')


def build_v380_url(host, user, password, device_id='', port=DEFAULT_PORT, quality='hd'):
    host = f'[{host}]' if ':' in host and not host.startswith('[') else host
    return (f'v380://{quote(str(user), safe="")}:{quote(str(password), safe="")}@{host}:{int(port)}?'
            + urlencode({'device_id': str(device_id), 'quality': quality}))


def parse_v380_url(url):
    try:
        u = urlparse(url)
        q = parse_qs(u.query, keep_blank_values=True)
        port = u.port or DEFAULT_PORT
        device_id = int(q.get('device_id', ['0'])[0] or 0)
        quality = q.get('quality', ['hd'])[0]
        if u.scheme.lower() != 'v380' or not u.hostname or not 0 < port < 65536:
            raise ValueError()
        if not 0 <= device_id <= 0xffffffff or quality not in ('hd', 'sd'):
            raise ValueError()
        user, password = unquote(u.username or 'admin'), unquote(u.password or '')
        if len(user.encode('ascii')) > 32 or len(password.encode('ascii')) > 48:
            raise ValueError()
        return dict(host=u.hostname, port=port, user=user, password=password,
                    device_id=device_id, quality=quality)
    except (ValueError, UnicodeError):
        raise V380Error('Invalid V380 address, device ID or credentials', permanent=True) from None


def normalize_v380_ptz(camera):
    """Upgrade earlier video-only D57 entries; preserve explicit user choices."""
    if (is_v380_url(camera.get('url', '')) and
            str(camera.get('model', '')).upper() == 'D57' and
            not camera.get('ptz_manual') and not camera.get('ptz_backend')):
        camera.update(ptz=True, ptz_backend='v380')
        return True
    return False


def parse_discovery_reply(data, host):
    try:
        f = data.decode('ascii').strip('\x00\r\n').split('^')
        if len(f) < 15 or f[:2] != ['NVDEVRESULT', '200'] or f[3] != host:
            return None
        port, device_id = int(f[9]), int(f[12])
        if not 0 < port < 65536 or not 0 < device_id <= 0xffffffff:
            return None
        return dict(host=host, port=port, device_id=device_id, mac=f[2])
    except (ValueError, UnicodeError):
        return None


def discover_v380(host, timeout=2.0):
    # The fixed reply port must be shared sequentially by parallel host probes.
    with _DISCOVERY_LOCK:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(('', 10009))
            s.sendto(b'NVDEVSEARCH^100', (host, 10008))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                s.settimeout(max(0.01, deadline - time.monotonic()))
                try:
                    data, addr = s.recvfrom(8192)
                except socket.timeout:
                    break
                if addr[0] == host:
                    result = parse_discovery_reply(data, host)
                    if result:
                        return result
    return None


def _aes(key, data, decrypt=False):
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    operation = cipher.decryptor() if decrypt else cipher.encryptor()
    return operation.update(data) + operation.finalize()


def _password_wire(password):
    random = secrets.token_hex(8).encode('ascii')
    padded = password.encode('ascii').ljust(48, b'\0')
    return random + _aes(random, _aes(b'macrovideo+*#!^@', padded))


class V380Client:
    def __init__(self, url):
        self.params = parse_v380_url(url)
        self.sock = None
        self._closed = threading.Event()
        self.version = 0
        self.width = self.height = 0
        self._media_key = b''
        self._send_lock = threading.RLock()
        self._live = False
        self._ptz_moving = False
        self._ptz_timer = None
        self._ptz_generation = 0
        self.ptz_error = None

    @property
    def live(self):
        return self._live and not self._closed.is_set()

    def move_ptz(self, direction):
        packet = ptz_packet(direction)  # validate before touching the camera
        with self._send_lock:
            if not self.live or self.sock is None:
                raise V380Error('Start the camera video before using PTZ')
            self._ptz_generation += 1
            generation = self._ptz_generation
            if self._ptz_timer:
                self._ptz_timer.cancel()
            self._ptz_moving = True
            self.ptz_error = None
            # Arm the watchdog independently of Qt button release events.
            timer = threading.Timer(PTZ_PULSE_SECONDS, self._watchdog_stop, (generation,))
            timer.daemon = True
            self._ptz_timer = timer
            try:
                timer.start()
                self.sock.sendall(packet)
            except Exception:
                self.stop_ptz()
                raise

    def _watchdog_stop(self, generation):
        with self._send_lock:
            if generation != self._ptz_generation:
                return
            try:
                self.stop_ptz()
            except OSError as exc:
                self.ptz_error = str(exc)

    def stop_ptz(self, force=False):
        with self._send_lock:
            self._ptz_generation += 1
            if self._ptz_timer:
                self._ptz_timer.cancel()
                self._ptz_timer = None
            moving = self._ptz_moving
            try:
                if self.live and self.sock is not None and (moving or force):
                    self.sock.sendall(ptz_packet())
            except OSError as exc:
                self.ptz_error = str(exc)
                raise
            else:
                self._ptz_moving = False

    def close(self):
        with self._send_lock:
            # Send motor stop before closing the authenticated video socket.
            try:
                self.stop_ptz()
            except OSError:
                pass
            self._closed.set()
            self._live = False
            sock, self.sock = self.sock, None
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()

    def _connect(self):
        if self._closed.is_set():
            raise V380Error('Connection closed')
        try:
            sock = socket.create_connection((self.params['host'], self.params['port']), timeout=5)
        except socket.timeout:
            raise V380Error('Camera not reachable (asleep?)', asleep=True) from None
        except OSError as exc:
            if exc.errno in _ASLEEP_ERRNOS:
                raise V380Error('Camera not reachable (asleep?)', asleep=True) from None
            raise
        self.sock = sock
        if self._closed.is_set():
            self.close()
            raise V380Error('Connection closed')
        sock.settimeout(8)

    def _read(self, count):
        out = bytearray()
        deadline = time.monotonic() + 8
        while len(out) < count:
            if self._closed.is_set() or self.sock is None:
                raise V380Error('Connection closed')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise V380Error('Camera read timed out', stalled=True)
            sock = self.sock
            if sock is None:
                raise V380Error('Connection closed')
            sock.settimeout(remaining)
            try:
                data = sock.recv(count - len(out))
            except socket.timeout:
                raise V380Error('Camera read timed out', stalled=True) from None
            if not data:
                raise V380Error('Camera closed connection')
            out.extend(data)
        return bytes(out)

    def open_live(self):
        try:
            p = self.params
            if not p['device_id']:
                found = discover_v380(p['host'])
                if not found:
                    raise V380Error('Device ID missing; discovery returned no device')
                p['device_id'] = found['device_id']
            self._connect()
            req = bytearray(520)
            struct.pack_into('<IIBII', req, 0, 1167, 120, 31, 1, p['device_id'])
            user = p['user'].encode('ascii')
            req[49:49 + len(user)] = user
            req[81:145] = _password_wire(p['password'])
            self.sock.sendall(req)
            response = self._read(256)
            command, result = struct.unpack_from('<II', response)
            if command != 1168:
                raise V380Error('Unexpected authentication response')
            if result != 1001:
                reason = {1011: 'Invalid local username', 1012: 'Invalid local password',
                          1018: 'Invalid device ID'}.get(result, f'Authentication rejected ({result})')
                raise V380Error(reason, permanent=result in (1011, 1012, 1018))
            self.version = response[12]
            if self.version not in (31, 32):
                raise V380Error(f'Unsupported device version {self.version}', permanent=True)
            ticket = struct.unpack_from('<I', response, 13)[0]
            self._media_key = struct.pack('<IQI', ticket, 0x618123462c14795c, 0x82800df0)
            self.sock.close()
            self.sock = None
            self._connect()
            req = bytearray(256)
            struct.pack_into('<II', req, 0, 301, p['device_id'])
            struct.pack_into('<HI', req, 12, 20, ticket)
            struct.pack_into('<II', req, 22, 4096, int(p['quality'] == 'hd'))
            self.sock.sendall(req)
            response = self._read(32)  # D57 sends 32 bytes, NOT 256.
            command, result, comm, self.width, self.height = struct.unpack_from('<IiHII', response)
            if command != 401 or result != 1001:
                raise V380Error(f'Stream login rejected ({result})')
            if comm != 20:
                raise V380Error(f'Unsupported communication version {comm}', permanent=True)
            req = bytearray(256)
            struct.pack_into('<IH', req, 0, 303, 0x3001)
            self.sock.sendall(req)
            self._live = True
        except Exception:
            self.close()
            raise

    def frames(self):
        parts, expected, frame_type, size = [], 0, None, 0
        deadline = time.monotonic() + 10
        while not self._closed.is_set():
            if time.monotonic() > deadline:
                raise V380Error('No complete video frame for 10 seconds', stalled=True)
            header = self._read(12)
            total, index, length = struct.unpack_from('<HHH', header, 3)
            if header[0] != 0x7f or not 0 < total <= 8192 or index >= total or not 0 < length <= 20000:
                raise V380Error('Invalid media fragment header')
            payload = self._read(length)
            typ = header[1]
            if typ not in (0, 1, 9, 0x28, 0x29):
                continue
            if index == 0:
                parts, expected, frame_type, size = [], total, typ, 0
            if index != len(parts) or total != expected or typ != frame_type:
                parts = []
                continue
            size += length
            if size > _MAX_FRAME:
                raise V380Error('Video frame exceeds size limit')
            parts.append(payload)
            if index + 1 != total:
                continue
            data = b''.join(parts)
            parts = []
            if len(data) <= 16:
                continue
            body = bytearray(data[16:])
            for offset in range(0, len(body) - 63, 80):
                body[offset:offset + 64] = _aes(self._media_key, bytes(body[offset:offset + 64]), True)
            deadline = time.monotonic() + 10
            yield typ in (0, 9, 0x28), bytes(body)


class V380Bridge:
    """Bounded LAN client serving decrypted HEVC/H.264/MJPEG on loopback TCP."""
    def __init__(self, url):
        parse_v380_url(url)
        self.source_url = url
        self.error = None
        self.permanent_error = False
        self.asleep = False
        self._stop = threading.Event()
        self._client = None
        self._conn = None
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(('127.0.0.1', 0))
        self._server.listen(1)
        self._server.settimeout(0.5)
        self.url = f'tcp://127.0.0.1:{self._server.getsockname()[1]}'
        self._thread = threading.Thread(target=self._serve, name='v380-bridge', daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._conn = conn
            started_at = time.monotonic()
            try:
                conn.settimeout(5)
                client = V380Client(self.source_url)
                self._client = client
                if self._stop.is_set():
                    break
                client.open_live()
                self.error = None
                self.asleep = False
                started = False
                for key_frame, payload in client.frames():
                    if self._stop.is_set():
                        break
                    if not started and not key_frame:
                        continue
                    started = True
                    conn.sendall(payload)
            except Exception as exc:
                # Exception text is generated locally or by sockets, never a URL.
                self.error = str(exc)
                self.permanent_error = isinstance(exc, V380Error) and exc.permanent
                self.asleep = isinstance(exc, V380Error) and (
                    exc.asleep or (exc.stalled and time.monotonic() - started_at < SLEEP_STALL_WINDOW))
            finally:
                conn.close()
                self._conn = None
                if self._client:
                    self._client.close()
                    self._client = None
            if self.permanent_error:
                break

    def ptz_client(self):
        client = self._client
        return client if client is not None and client.live else None

    def close(self):
        self._stop.set()
        self._server.close()
        client, conn = self._client, self._conn
        if client:
            client.close()
        if conn:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._thread.join(timeout=6)
