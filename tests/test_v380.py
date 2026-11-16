"""Offline protocol and integration checks; no camera or credentials required."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import socket
import struct
import unittest
from unittest.mock import MagicMock, patch

from v380 import (V380Client, V380Bridge, V380Error, _aes, _password_wire,
                  build_v380_url, parse_v380_url, parse_discovery_reply, ptz_packet, normalize_v380_ptz)

URL = build_v380_url('192.0.2.1', 'admin', 'test-only', 123)


class ChunkSocket:
    def __init__(self, data):
        self.data = bytearray(data)
        self.closed = False
        self.sent = []

    def recv(self, count):
        count = min(count, 3)  # exercise fragmented TCP reads
        result = bytes(self.data[:count])
        del self.data[:count]
        return result

    def sendall(self, data): self.sent.append(bytes(data))
    def close(self): self.closed = True
    def shutdown(self, how): pass
    def settimeout(self, timeout): pass


def fragment(typ, index, total, payload):
    h = bytearray(12)
    h[:2] = bytes([0x7f, typ])
    struct.pack_into('<HHH', h, 3, total, index, len(payload))
    return bytes(h) + payload


class ProtocolTests(unittest.TestCase):
    def test_url_special_characters_and_validation(self):
        url = build_v380_url('192.0.2.1', 'a@b', 'a+#): x', 123, quality='sd')
        p = parse_v380_url(url)
        self.assertEqual((p['user'], p['password'], p['device_id'], p['quality']),
                         ('a@b', 'a+#): x', 123, 'sd'))
        for bad in ('v380://host?device_id=-1', 'v380://host?quality=bad',
                    'v380://host:99999', 'v380://host?device_id=not-a-number'):
            with self.assertRaises(V380Error) as caught: parse_v380_url(bad)
            self.assertNotIn(bad, str(caught.exception))

    def test_discovery_rejects_wrong_host_and_malformed_data(self):
        reply = b'NVDEVRESULT^200^aa:bb^192.0.2.1^mask^gateway^5040^5050^5051^8800^7050^5040^123^0^1000'
        self.assertEqual(parse_discovery_reply(reply, '192.0.2.1')['device_id'], 123)
        self.assertIsNone(parse_discovery_reply(reply, '192.0.2.2'))
        self.assertIsNone(parse_discovery_reply(b'NVDEVRESULT^200', '192.0.2.1'))

    def test_password_wire_decrypts_to_original(self):
        wire = _password_wire('test-only')
        self.assertEqual(len(wire), 64)
        plain = _aes(b'macrovideo+*#!^@', _aes(wire[:16], wire[16:], True), True)
        self.assertEqual(plain, b'test-only'.ljust(48, b'\0'))

    def test_full_handshake_uses_two_connections_and_32_byte_stream_reply(self):
        auth = bytearray(256)
        struct.pack_into('<II', auth, 0, 1168, 1001)
        auth[12] = 32
        struct.pack_into('<I', auth, 13, 42)
        stream = bytearray(32)
        struct.pack_into('<IiHII', stream, 0, 401, 1001, 20, 2304, 2592)
        sockets = [ChunkSocket(auth), ChunkSocket(stream)]
        with patch('v380.socket.create_connection', side_effect=sockets):
            c = V380Client(URL)
            c.open_live()
        self.assertTrue(sockets[0].closed)
        self.assertEqual((c.width, c.height), (2304, 2592))
        self.assertEqual([len(x) for x in sockets[1].sent], [256, 256])
        self.assertEqual(struct.unpack_from('<I', sockets[1].sent[1])[0], 303)
        c.close()
        self.assertTrue(sockets[1].closed)

    def test_bad_password_closes_connection_and_is_permanent(self):
        reply = bytearray(256)
        struct.pack_into('<II', reply, 0, 1168, 1012)
        sock = ChunkSocket(reply)
        with patch('v380.socket.create_connection', return_value=sock):
            c = V380Client(URL)
            with self.assertRaises(V380Error) as caught: c.open_live()
        self.assertTrue(caught.exception.permanent)
        self.assertTrue(sock.closed)
        self.assertIsNone(c.sock)

    def test_media_reassembly_decrypts_and_drops_incomplete_frames(self):
        c = V380Client(URL)
        c._media_key = bytes(range(16))
        plain = b'\0\0\0\1' + bytes(range(180))
        encrypted = bytearray(plain)
        for offset in range(0, len(plain) - 63, 80):
            encrypted[offset:offset+64] = _aes(c._media_key, plain[offset:offset+64])
        full = bytes(16) + encrypted
        data = (fragment(0x28, 0, 2, b'incomplete') + fragment(0x29, 1, 2, b'wrong-type')
                + fragment(0x28, 0, 2, full[:70]) + fragment(0x18, 0, 1, b'ignored')
                + fragment(0x28, 1, 2, full[70:]))
        c.sock = ChunkSocket(data)
        frames = c.frames()
        self.assertEqual(next(frames), (True, plain))
        with self.assertRaisesRegex(V380Error, 'closed'): next(frames)
        c.close()

    def test_invalid_fragment_is_rejected(self):
        c = V380Client(URL)
        c.sock = ChunkSocket(bytes(12))
        with self.assertRaisesRegex(V380Error, 'fragment'): next(c.frames())
        c.close()


class PtzTests(unittest.TestCase):
    def setUp(self):
        self.client = V380Client(URL)
        self.sock = ChunkSocket(b'')
        self.client.sock = self.sock
        self.client._live = True
        self.timer_patch = patch('v380.threading.Timer')
        self.timer = self.timer_patch.start()
        self.addCleanup(self.timer_patch.stop)
        self.addCleanup(self.client.close)

    def test_direction_packets_and_channel(self):
        axes = {'left': (1001, 1000), 'right': (1002, 1000),
                'up': (1000, 1003), 'down': (1000, 1004)}
        for direction, pair in axes.items():
            self.assertEqual(struct.unpack('<I6H', ptz_packet(direction)),
                             (170, 1000, 1000, *pair, 0, 1))
        self.assertEqual(struct.unpack('<I6H', ptz_packet()), (170, 1000, 1000, 1000, 1000, 0, 1))

    def test_watchdog_stops_without_button_release(self):
        self.client.move_ptz('right')
        duration, callback, args = self.timer.call_args.args
        self.assertLessEqual(duration, .35)
        self.assertEqual(self.sock.sent, [ptz_packet('right')])
        callback(*args)
        self.assertEqual(self.sock.sent[-1], ptz_packet())
        self.assertFalse(self.client._ptz_moving)

    def test_release_and_close_stop_motor_before_socket_close(self):
        self.client.move_ptz('left')
        self.client.stop_ptz(force=True)
        self.assertEqual(self.sock.sent[-1], ptz_packet())
        self.client.move_ptz('up')
        with patch.object(self.sock, 'close', side_effect=lambda: self.assertEqual(self.sock.sent[-1], ptz_packet())):
            self.client.close()
        self.assertFalse(self.client.live)

    def test_old_timer_does_not_stop_new_move(self):
        self.client.move_ptz('left')
        _, callback, args = self.timer.call_args.args
        self.client.move_ptz('right')
        callback(*args)
        self.assertEqual(self.sock.sent, [ptz_packet('left'), ptz_packet('right')])
        self.assertTrue(self.client._ptz_moving)

    def test_no_live_session_and_invalid_direction_never_send(self):
        self.client._live = False
        with self.assertRaises(V380Error): self.client.move_ptz('left')
        with self.assertRaises(KeyError): self.client.move_ptz('invalid')
        self.assertFalse(self.sock.sent)

    def test_backend_uses_current_client_and_stops_old_session(self):
        from ptz import V380PtzBackend
        a, b = MagicMock(), MagicMock()
        provider = MagicMock(side_effect=[a, b])
        backend = V380PtzBackend(provider)
        backend.move('left');backend.move('right');backend.stop()
        a.move_ptz.assert_called_once_with('left')
        a.stop_ptz.assert_called_once_with()
        b.stop_ptz.assert_called_once_with(force=True)

    def test_controller_close_stops_active_motor(self):
        from ptz import V380PtzBackend, PtzController
        import threading
        moved = threading.Event()
        client = MagicMock()
        client.move_ptz.side_effect = lambda direction: moved.set()
        controller = PtzController(V380PtzBackend(lambda: client))
        controller.move('left')
        self.assertTrue(moved.wait(1))
        controller.close();controller._thread.join(1)
        self.assertFalse(controller._thread.is_alive())
        client.stop_ptz.assert_called_once_with()

    def test_known_d57_config_upgrade_preserves_manual_opt_out(self):
        camera = {'url': URL, 'model': 'D57', 'ptz': False, 'name': 'D57'}
        self.assertTrue(normalize_v380_ptz(camera))
        self.assertEqual((camera['ptz'], camera['ptz_backend']), (True, 'v380'))
        self.assertFalse(normalize_v380_ptz(camera))
        manual = {'url': URL, 'model': 'D57', 'ptz': False, 'ptz_manual': True}
        self.assertFalse(normalize_v380_ptz(manual))
        self.assertFalse(manual['ptz'])
        self.assertFalse(normalize_v380_ptz({'url': URL, 'model': 'V380'}))


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_edit_dialog_roundtrip_preserves_id_password_quality(self):
        from dialogs import CameraEditDialog
        url = build_v380_url('192.0.2.1', 'admin', 'special+# end ', 123, quality='sd')
        dialog = CameraEditDialog({'url': url})
        self.assertEqual(dialog.path_combo.currentText(), 'v380')
        self.assertTrue(dialog.ptz_checkbox.isEnabled())
        dialog.build_url()
        self.assertEqual(parse_v380_url(dialog.url_input.text()), parse_v380_url(url))
        dialog.close()

    def test_discovery_identifies_only_protocol_confirmed_camera(self):
        from discovery import identify_host
        with patch('discovery.discover_v380', return_value={'device_id': 123, 'port': 8800, 'mac': 'aa'}):
            found = identify_host('192.0.2.1', [8800], None, 'admin', 'test-only')
        self.assertEqual(parse_v380_url(found['stream_uri'])['device_id'], 123)
        self.assertEqual(found['manufacturer'], 'Macrovideo')
        with patch('discovery.discover_v380', return_value=None):
            self.assertIsNone(identify_host('192.0.2.1', [8800], None))

    def test_permanent_url_error_does_not_retry_camera_thread(self):
        from stream import CameraThread
        thread = CameraThread(1, URL)
        with patch('stream.V380Bridge', side_effect=V380Error('Invalid credentials', permanent=True)) as bridge:
            thread.run()
        self.assertEqual(bridge.call_count, 1)
        self.assertFalse(thread.running)

    def test_stream_routing_and_no_onvif_ptz_probe(self):
        from stream import CameraThread
        from ptz import needs_ptz_detection, detect_ptz, camera_has_ptz, backend_for_camera, V380PtzBackend
        thread = CameraThread(1, URL)
        self.assertTrue(camera_has_ptz({'url': URL, 'ptz': True}))
        self.assertIsInstance(backend_for_camera({'url': URL}), V380PtzBackend)
        self.assertFalse(thread._is_reolink)
        self.assertTrue(thread._is_v380)
        self.assertEqual(thread.rtsp_url, URL)
        self.assertFalse(needs_ptz_detection({'url': URL}))
        self.assertIsNone(detect_ptz({'url': URL}))


if __name__ == '__main__':
    unittest.main()
