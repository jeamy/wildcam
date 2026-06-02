import os
import threading
import time
from collections import deque
from datetime import datetime
from urllib.parse import urlparse

import cv2
import numpy as np
import requests
from PyQt6.QtCore import QThread, pyqtSignal

from camera_utils import (
    _build_rtsp_url,
    _normalize_rtsp_url,
    _parse_rtsp_url,
    _tcp_probe,
    _udp_reolink_wake,
)
from i18n import tr


class CameraThread(QThread):
    """Thread für einzelne Kamera mit OpenCV - optimiert für parallele Streams"""
    frame_ready = pyqtSignal(np.ndarray, int)
    connection_status = pyqtSignal(bool, int, str)
    
    def __init__(self, camera_id, rtsp_url, uid=""):
        super().__init__()
        self.camera_id = camera_id
        # Normalize URL to ensure explicit port (prevents FFmpeg TCP fallback errors)
        self.rtsp_url = _normalize_rtsp_url(rtsp_url)
        self.uid = uid
        self.running = False
        self.recording = False
        self.video_writer = None
        self.event_writer = None
        self._event_clip_filename = None
        self._event_clip_until = 0.0
        self._event_clip_started = 0.0
        self._writer_lock = threading.Lock()
        self._buffer_lock = threading.Lock()
        self._frame_buffer = deque()
        self._frame_buffer_seconds = 12.0
        self.cap = None
        self.reconnect_delay = 5  # Mehr Zeit für Akku-Kameras
        self._host, self._port, self._user, self._password = _parse_rtsp_url(rtsp_url)
        self._is_proxy_stream = self._host in ("localhost", "127.0.0.1") and int(self._port or 0) == 8554
        if self._is_proxy_stream:
            self.reconnect_delay = 2
        
        # Alternative Pfade (Reolink Fallbacks)
        self._alt_paths = [
            "h264Preview_01_main",
            "h265Preview_01_main",
            "Preview_01_main",
            "h264Preview_01_sub",
            "Preview_01_sub"
        ]
        
    def run(self):
        """Hauptschleife mit automatischem Retry"""
        self.running = True
        
        while self.running:
            try:
                self._connect_and_stream()
            except Exception as e:
                self.connection_status.emit(False, self.camera_id, tr("error.prefix", error=str(e)))
            finally:
                self._release_capture()

            if self.running:
                self.connection_status.emit(False, self.camera_id, tr("camera.preview.retrying"))
                for _ in range(int(self.reconnect_delay * 10)):
                    if not self.running:
                        break
                    self.msleep(100)
        
        self._cleanup()

    def _release_capture(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _release_writer(self):
        with self._writer_lock:
            if self.video_writer:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
                self.video_writer = None
            self.recording = False

    def _wait_before_reconnect(self, seconds: float):
        end_time = time.monotonic() + seconds
        while self.running and time.monotonic() < end_time:
            self.msleep(100)

    def _open_capture(self, rtsp_url: str, open_timeout_ms: int, read_timeout_ms: int):
        self._release_capture()
        return cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, read_timeout_ms
        ])
    
    def _connect_and_stream(self):
        """Verbindung herstellen und streamen"""
        # Best-effort wake attempt for sleeping/battery cameras
        if self._host and not self._is_proxy_stream:
            # Intensiv-Weckphase (für Akku-Kameras wie Argus PT Ultra)
            # Wir wiederholen das Wecken und prüfen die Erreichbarkeit über mind. 10 Sek.
            self.connection_status.emit(False, self.camera_id, tr("camera.preview.waiting"))
            
            wake_ok = False
            for attempt in range(10):  # 10 Versuche alle ~1s = ca. 10s total
                if not self.running:
                    break
                
                # 1. UDP Wake Burst
                _udp_reolink_wake(self._host, self.uid)
                
                # 2. Optionaler HTTP Ping
                try:
                    requests.get(f"http://{self._host}:8000/api.cgi?cmd=GetDevInfo", timeout=0.2)
                except Exception:
                    pass
                
                # 3. RTSP Erreichbarkeit prüfen (Port 554)
                for _ in range(3):
                    if not self.running:
                        break
                    ok, _ = _tcp_probe(self._host, int(self._port or 554), timeout=0.2)
                    if ok:
                        wake_ok = True
                        break
                    time.sleep(0.3)
                
                if wake_ok:
                    break
            
            if wake_ok:
                self.connection_status.emit(True, self.camera_id, tr("camera.status.connected")) # Wach!
                self._wait_before_reconnect(1.0)
            else:
                # Auch wenn TCP Probe fehlschlägt, versuchen wir es trotzdem 
                # (manchen Kameras antworten nicht auf Port-Checks, aber auf echte RTSP-Anfragen)
                self.connection_status.emit(False, self.camera_id, tr("camera.status.connecting"))

        open_timeout_ms = 20000 if self._is_proxy_stream else 3000
        read_timeout_ms = 10000 if self._is_proxy_stream else 3000

        # RTSP Stream öffnen (mit Fallback-Pfaden für native Reolink-RTSP-URLs)
        # Use TCP transport to reduce RTP packet loss warnings
        self.cap = self._open_capture(self.rtsp_url, open_timeout_ms, read_timeout_ms)
        
        # Falls eine native Kamera nicht öffnet, probieren wir Reolink-typische Varianten.
        # Bei ReolinkProxy-URLs ist der Pfad absichtlich fix (<Name>/mainStream).
        if not self.cap.isOpened() and not self._is_proxy_stream:
            # Parse URL properly to rebuild with alternative paths
            try:
                u = urlparse(self.rtsp_url)
                port = u.port or 554
                
                for path in self._alt_paths:
                    # Use _build_rtsp_url to properly encode credentials
                    test_url = _build_rtsp_url(
                        host=u.hostname,
                        port=port,
                        username=u.username or '',
                        password=u.password or '',
                        path=path,
                        scheme=u.scheme
                    )
                    if test_url == self.rtsp_url:
                        continue
                    
                    self.connection_status.emit(False, self.camera_id, f"Prüfe Pfad: {path}...")
                    self.cap = self._open_capture(test_url, open_timeout_ms, read_timeout_ms)
                    if self.cap.isOpened():
                        self.rtsp_url = test_url
                        break
            except Exception:
                pass
        
        if not self.cap.isOpened():
            # Diagnostik: Wenn RTSP zu ist, aber Port 8000 offen, ist RTSP wahrscheinlich in der Kamera deaktiviert
            if self._host and not self._is_proxy_stream:
                ok_api, _ = _tcp_probe(self._host, 8000, timeout=0.5)
                if ok_api:
                    raise Exception("Kamera antwortet auf API (Port 8000), aber RTSP ist blockiert. Bitte 'RTSP' in den Kamera-Einstellungen (Netzwerk -> Fortgeschritten -> Servereinstellungen) aktivieren!")
            raise Exception(tr("camera.error.stream_unreachable"))
        
        # Optimierungen für geringe Latenz
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self._is_proxy_stream:
            self.cap.set(cv2.CAP_PROP_FPS, 25)
        
        self.connection_status.emit(True, self.camera_id, tr("camera.status.connected"))
        
        last_ui_emit = 0.0
        ui_emit_interval = 1.0 / (15 if self._is_proxy_stream else 25)
        failed_reads = 0
        max_failed_reads = 4 if self._is_proxy_stream else 3
        
        while self.running:
            ret, frame = self.cap.read()
            
            if not ret:
                failed_reads += 1
                if failed_reads >= max_failed_reads:
                    raise Exception(tr("camera.error.stream_interrupted"))
                self.msleep(500 if self._is_proxy_stream else 200)
                continue

            failed_reads = 0
            self._remember_frame(frame)
            
            now = time.monotonic()
            if now - last_ui_emit >= ui_emit_interval:
                self.frame_ready.emit(frame.copy(), self.camera_id)
                last_ui_emit = now
            
            # Aufzeichnung (alle Frames)
            with self._writer_lock:
                if self.recording and self.video_writer is not None:
                    try:
                        self.video_writer.write(frame)
                    except Exception:
                        # Don't crash the streaming thread due to writer issues.
                        pass
                if self.event_writer is not None:
                    try:
                        self.event_writer.write(frame)
                    except Exception:
                        pass
                    if time.monotonic() >= self._event_clip_until:
                        self._release_event_writer_locked()
            
            self.msleep(5 if self._is_proxy_stream else 10)

    def _remember_frame(self, frame):
        now = time.monotonic()
        with self._buffer_lock:
            self._frame_buffer.append((now, frame.copy()))
            cutoff = now - self._frame_buffer_seconds
            while self._frame_buffer and self._frame_buffer[0][0] < cutoff:
                self._frame_buffer.popleft()
    
    def _cleanup(self):
        """Ressourcen freigeben"""
        self._release_capture()
        self._release_writer()
        with self._writer_lock:
            self._release_event_writer_locked()

    def _release_event_writer_locked(self):
        if self.event_writer:
            try:
                self.event_writer.release()
            except Exception:
                pass
        self.event_writer = None
        self._event_clip_filename = None
        self._event_clip_until = 0.0
        self._event_clip_started = 0.0
    
    def start_recording(self, output_path):
        """Starte Aufzeichnung"""
        if not (self.cap and self.cap.isOpened()):
            return None

        with self._writer_lock:
            if self.recording and self.video_writer is not None:
                return None

            # Ensure any previous writer is closed before re-opening
            if self.video_writer is not None:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
                self.video_writer = None

            fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            if not fps or fps <= 0 or fps > 120:
                fps = 25.0
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width <= 0 or height <= 0:
                width, height = 640, 480

            os.makedirs(output_path, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Some streams behave badly with MPEG4/XVID timestamping (invalid PTS).
            # MJPG-in-AVI is usually more tolerant.
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            filename = os.path.join(output_path, f"camera_{self.camera_id}_{timestamp}.avi")

            vw = cv2.VideoWriter(filename, fourcc, fps, (width, height))
            if not vw.isOpened():
                return None

            self.video_writer = vw
            self.recording = True
            return filename
        return None

    def start_event_clip(
        self,
        output_path,
        label: str,
        pre_seconds: float = 8.0,
        post_seconds: float = 20.0,
        max_seconds: float = 180.0,
    ):
        """Start a short event clip from the rolling frame buffer plus future frames."""
        if not (self.cap and self.cap.isOpened()):
            return None

        with self._writer_lock:
            now = time.monotonic()
            max_seconds = min(180.0, max(1.0, float(max_seconds)))
            post_seconds = max(1.0, min(float(post_seconds), max_seconds))
            if self.event_writer is not None and now < self._event_clip_until:
                max_until = (self._event_clip_started or now) + max_seconds
                self._event_clip_until = min(max_until, max(self._event_clip_until, now + post_seconds))
                return self._event_clip_filename

            with self._buffer_lock:
                buffered_items = [
                    (frame_time, frame)
                    for frame_time, frame in self._frame_buffer
                    if frame_time >= now - max(0.0, min(float(pre_seconds), max_seconds))
                ]
            buffered = [frame for _frame_time, frame in buffered_items]
            actual_pre_seconds = now - buffered_items[0][0] if buffered_items else 0.0

            fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            if not fps or fps <= 0 or fps > 120:
                fps = 25.0
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if (width <= 0 or height <= 0) and buffered:
                height, width = buffered[-1].shape[:2]
            if width <= 0 or height <= 0:
                width, height = 640, 480

            os.makedirs(output_path, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_label = "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(label))
            filename = os.path.join(output_path, f"event_{self.camera_id}_{safe_label}_{timestamp}.avi")

            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            vw = cv2.VideoWriter(filename, fourcc, fps, (width, height))
            if not vw.isOpened():
                return None

            for frame in buffered:
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
                vw.write(frame)

            self.event_writer = vw
            self._event_clip_filename = filename
            self._event_clip_started = now - max(0.0, actual_pre_seconds)
            self._event_clip_until = min(self._event_clip_started + max_seconds, now + post_seconds)
            return filename
    
    def stop_recording(self):
        """Stoppe Aufzeichnung"""
        with self._writer_lock:
            self.recording = False
            if self.video_writer:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
                self.video_writer = None
    
    def request_stop(self):
        """Signal the stream loop to stop.

        OpenCV/FFmpeg can abort if VideoCapture is released from a different
        thread while open/read is active. The stream thread owns cleanup.
        """
        self.running = False
        self.stop_recording()

    def stop(self, timeout_ms=2000):
        """Thread stoppen"""
        self.request_stop()
        if not self.wait(timeout_ms):
            return False
        return True
