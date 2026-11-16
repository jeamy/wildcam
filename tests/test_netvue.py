"""Offline tests: python3 -m unittest discover -s tests -v"""
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

from netvue import (
    CMD_DISCOVERY, DISCOVERY_PORT, NetvueClient, NetvueError,
    _command, _packet, discover_local_key,
)

HOST = "192.0.2.10"


def discovery_reply(**changes):
    unit = {"A": 8, "V": 2, "C": 0,
            "P": ["serial", "firmware", HOST, 5555, "fresh-key"]}
    unit.update(changes)
    return _packet(json.dumps([unit]).encode())


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch("netvue.socket.socket")
        factory = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.sock = factory.return_value.__enter__.return_value
        self.sock.getpeername.return_value = (HOST, DISCOVERY_PORT)

    def test_unicast_key(self):
        self.sock.recv.return_value = discovery_reply()
        self.assertEqual(discover_local_key(HOST), "fresh-key")
        self.sock.connect.assert_called_once_with((HOST, DISCOVERY_PORT))
        self.sock.send.assert_called_once_with(_command({"Q": CMD_DISCOVERY, "V": 2, "P": []}))

    def test_packet_loss_retried_once(self):
        self.sock.recv.side_effect = [socket.timeout(), discovery_reply()]
        self.assertEqual(discover_local_key(HOST), "fresh-key")
        self.assertEqual(self.sock.send.call_count, 2)

    def test_invalid_replies_do_not_replace_key(self):
        self.sock.recv.side_effect = [
            b"short", _packet(b"not json"), _packet(b"{}"),
            discovery_reply(A=1), discovery_reply(V=1), discovery_reply(C=1),
            discovery_reply(P=["serial"]),
            discovery_reply(P=["serial", "fw", "192.0.2.11", 5555, "wrong-host"]),
            discovery_reply(P=["serial", "fw", HOST, 9999, "wrong-port"]),
            discovery_reply(P=["serial", "fw", HOST, 5555, None]),
            discovery_reply(P=["serial", "fw", HOST, 5555, "null"]),
            discovery_reply() + b"trailing bytes",
            _packet(b"[]", ptype=201),
            discovery_reply(),
        ]
        self.assertEqual(discover_local_key(HOST), "fresh-key")

    def test_timeout_is_bounded(self):
        self.sock.recv.side_effect = socket.timeout()
        with self.assertRaisesRegex(NetvueError, "no valid reply"):
            discover_local_key(HOST)
        self.assertEqual(self.sock.send.call_count, 2)


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.client = NetvueClient(HOST, "user", "stale-key")
        self.client.connect = MagicMock()
        self.client.close = MagicMock()
        self.client._send = MagicMock()

    def test_valid_key_does_not_use_discovery(self):
        self.client._wait_command = MagicMock(return_value={"C": 0})
        with patch("netvue.discover_local_key") as discover:
            self.client.login()
        discover.assert_not_called()
        self.assertEqual(self.client.key, "stale-key")

    def test_invalid_key_refreshed_and_login_retried(self):
        self.client._wait_command = MagicMock(side_effect=[
            NetvueError("local key invalid", code=1), {"C": 0},
        ])
        with patch("netvue.discover_local_key", return_value="fresh-key") as discover:
            self.client.login()
        discover.assert_called_once_with(HOST, 5555, 3.0)
        self.client.close.assert_called_once()
        self.client.connect.assert_called_once()
        sent = [json.loads(call.args[0][16:])[0]["P"][0]
                for call in self.client._send.call_args_list]
        self.assertEqual(sent, ["stale-key", "fresh-key"])

    def test_other_errors_do_not_trigger_discovery(self):
        self.client._wait_command = MagicMock(side_effect=NetvueError("too many sessions", code=4))
        with patch("netvue.discover_local_key") as discover:
            with self.assertRaisesRegex(NetvueError, "too many sessions"):
                self.client.login()
        discover.assert_not_called()

    def test_fresh_key_rejection_does_not_loop(self):
        self.client._wait_command = MagicMock(side_effect=NetvueError("invalid", code=1))
        with patch("netvue.discover_local_key", return_value="fresh-key") as discover:
            with self.assertRaises(NetvueError):
                self.client.login()
        discover.assert_called_once()
        self.assertEqual(self.client._send.call_count, 2)

    def test_discovery_failure_closes_open_live_connection(self):
        self.client._wait_command = MagicMock(side_effect=NetvueError("invalid", code=1))
        with patch("netvue.discover_local_key", side_effect=OSError("unreachable")):
            with self.assertRaisesRegex(NetvueError, "automatic refresh failed"):
                self.client.open_live()
        self.assertTrue(self.client.close.called)

    def test_camera_error_code_is_preserved(self):
        self.client.read_packet = MagicMock(return_value=(200, 0, b'[{"A":11,"P":[1]}]'))
        with self.assertRaises(NetvueError) as error:
            self.client._wait_command(1, float("inf"))
        self.assertEqual(error.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
