"""Background status checks for cameras served through ReolinkProxy."""
import threading
from collections.abc import Callable

from camera_utils import PROXY_ERROR, rtsp_describe_status


def check_proxy_streams(
    targets: list[tuple[int, str]],
    on_result: Callable[[int, str], None],
    timeout: float = 12.0,
) -> list[threading.Thread]:
    """Check proxy stream URLs in parallel via RTSP DESCRIBE.

    Uses daemon threads so a slow check (503 takes ~10 s) never blocks app
    shutdown. ``on_result(camera_id, status)`` is called from the worker
    thread - pass a Qt signal's ``emit`` to get back onto the GUI thread.
    """

    def worker(camera_id: int, url: str):
        try:
            status = rtsp_describe_status(url, timeout)
        except Exception:
            status = PROXY_ERROR
        try:
            on_result(int(camera_id), status)
        except (RuntimeError, AttributeError):
            # Window was closed while the check was still running.
            pass

    threads = []
    for camera_id, url in targets:
        thread = threading.Thread(target=worker, args=(camera_id, url), daemon=True)
        thread.start()
        threads.append(thread)
    return threads
