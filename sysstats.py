"""Lightweight system statistics for the toolbar (memory, network).

Uses psutil when it is installed; otherwise falls back to /proc on Linux.
All functions are cheap enough to be polled every second from the UI thread.
"""
import os
import time

try:
    import psutil
except Exception:  # pragma: no cover - psutil is optional
    psutil = None

_process = psutil.Process(os.getpid()) if psutil is not None else None


def process_memory_bytes():
    """Resident memory of this process in bytes (0 if unknown)."""
    if _process is not None:
        try:
            return int(_process.memory_info().rss)
        except Exception:
            pass
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def network_bytes():
    """Total bytes (received, sent) on all non-loopback interfaces."""
    if psutil is not None:
        try:
            recv = sent = 0
            for name, counters in psutil.net_io_counters(pernic=True).items():
                if name.startswith("lo"):
                    continue
                recv += counters.bytes_recv
                sent += counters.bytes_sent
            return recv, sent
        except Exception:
            pass
    try:
        recv = sent = 0
        with open("/proc/net/dev", "r", encoding="utf-8") as fh:
            for line in fh.readlines()[2:]:
                name, _, data = line.partition(":")
                if name.strip().startswith("lo"):
                    continue
                fields = data.split()
                recv += int(fields[0])
                sent += int(fields[8])
        return recv, sent
    except Exception:
        return 0, 0


def format_bytes(value, per_second=False):
    """Human readable size: 512 KB, 3.4 MB, 1.20 GB (optionally with /s)."""
    value = float(max(value, 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while value >= 1000 and unit < len(units) - 1:
        value /= 1024.0
        unit += 1
    if unit == 0:
        text = f"{int(value)} B"
    elif unit >= 3:
        text = f"{value:.2f} {units[unit]}"
    elif value >= 100:
        text = f"{value:.0f} {units[unit]}"
    else:
        text = f"{value:.1f} {units[unit]}"
    return text + "/s" if per_second else text


class NetworkMonitor:
    """Tracks network throughput and bytes transferred since creation."""

    def __init__(self):
        self._start_recv, self._start_sent = network_bytes()
        self._last_recv, self._last_sent = self._start_recv, self._start_sent
        self._last_time = time.monotonic()
        self.recv_rate = 0.0
        self.sent_rate = 0.0

    def update(self):
        recv, sent = network_bytes()
        now = time.monotonic()
        elapsed = now - self._last_time
        if elapsed > 0:
            self.recv_rate = max(recv - self._last_recv, 0) / elapsed
            self.sent_rate = max(sent - self._last_sent, 0) / elapsed
        self._last_recv, self._last_sent, self._last_time = recv, sent, now
        return self.recv_rate, self.sent_rate

    @property
    def total_received(self):
        return max(self._last_recv - self._start_recv, 0)

    @property
    def total_sent(self):
        return max(self._last_sent - self._start_sent, 0)
