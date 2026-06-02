import threading
import time
import math
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

import cv2
from PyQt6.QtCore import QThread, pyqtSignal


KNOWN_YOLO_WEIGHTS = {
    "yolo11n.pt",
    "yolo11s.pt",
    "yolo11m.pt",
    "yolo11l.pt",
    "yolo11x.pt",
    "yolov8n.pt",
    "yolov8s.pt",
    "yolov8m.pt",
    "yolov8l.pt",
    "yolov8x.pt",
}


DEFAULT_DETECTION_CONFIG = {
    "model": "yolo11n.pt",
    "imgsz": 640,
    "confidence": 0.4,
    "device": "auto",
    "analysis_fps_per_camera": 3.0,
    "stable_frames": 2,
    "cooldown_seconds": 180,
    "event_suppress_seconds": 30,
    "event_clip_seconds": 30,
    "pre_event_seconds": 8,
    "post_event_seconds": 20,
    "motion_required_classes": [
        "bicycle",
        "car",
        "motorcycle",
        "bus",
        "truck",
    ],
    "motion_min_pixels": 12.0,
    "classes": [
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "bus",
        "truck",
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
    ],
}


class ModelLoadError(RuntimeError):
    pass


def default_model_dir(recording_path: str) -> Path:
    return Path(recording_path).expanduser() / "models"


def is_known_yolo_weight(model_name: str) -> bool:
    return Path(str(model_name)).name in KNOWN_YOLO_WEIGHTS


def _find_downloaded_weight(file_name: str) -> Path | None:
    search_roots = [
        Path.cwd(),
        Path.home() / ".cache",
        Path.home() / ".config" / "Ultralytics",
    ]
    for root in search_roots:
        if not root.exists():
            continue
        direct = root / file_name
        if direct.exists():
            return direct
        try:
            for candidate in root.rglob(file_name):
                if candidate.is_file():
                    return candidate
        except Exception:
            continue
    return None


def prepare_model_path(model_name: str, model_dir: str | Path) -> Path:
    raw = str(model_name or "").strip() or DEFAULT_DETECTION_CONFIG["model"]
    expanded = Path(raw).expanduser()
    if expanded.exists():
        return expanded

    file_name = Path(raw).name
    target_dir = Path(model_dir).expanduser()
    local_target = target_dir / file_name
    if local_target.exists():
        return local_target

    if not is_known_yolo_weight(raw):
        raise ModelLoadError(f"Modell nicht gefunden: {raw}")

    target_dir.mkdir(parents=True, exist_ok=True)
    last_error = None

    try:
        from ultralytics.utils.downloads import attempt_download_asset

        downloaded = Path(attempt_download_asset(file_name)).expanduser()
        if downloaded.exists():
            shutil.copy2(downloaded, local_target)
            return local_target
    except Exception as exc:
        last_error = exc

    try:
        from ultralytics import YOLO

        model = YOLO(file_name)
        for attr in ("ckpt_path", "pt_path"):
            downloaded_attr = getattr(model, attr, None)
            if downloaded_attr and Path(downloaded_attr).exists():
                shutil.copy2(Path(downloaded_attr), local_target)
                return local_target
    except Exception as exc:
        last_error = exc

    downloaded = _find_downloaded_weight(file_name)
    if downloaded is not None:
        shutil.copy2(downloaded, local_target)
        return local_target

    raise ModelLoadError(f"Modell-Download fehlgeschlagen: {file_name}: {last_error}")


@dataclass
class DetectionResult:
    camera_id: int
    camera_name: str
    label: str
    confidence: float
    detections: list[dict[str, Any]]
    annotated_frame: Any
    timestamp: float


class DetectionWorker(QThread):
    detected = pyqtSignal(object)
    status = pyqtSignal(str)

    def __init__(self, config: dict | None = None, parent=None):
        super().__init__(parent)
        merged = dict(DEFAULT_DETECTION_CONFIG)
        if config:
            merged.update(config)
        self.config = merged
        self._running = False
        self._lock = threading.Lock()
        self._latest_frames: dict[int, tuple[str, Any, float]] = {}
        self._last_analyzed: dict[int, float] = {}
        self._stable_hits: dict[tuple[int, str], int] = {}
        self._last_event: dict[tuple[int, str], float] = {}
        self._last_camera_event: dict[int, float] = {}
        self._last_motion_box: dict[tuple[int, str], tuple[float, float]] = {}
        self._model = None
        self._names: dict[int, str] = {}
        self._device = "cpu"

    def submit_frame(self, camera_id: int, camera_name: str, frame):
        if not self._running:
            return
        with self._lock:
            self._latest_frames[int(camera_id)] = (camera_name, frame.copy(), time.monotonic())

    def stop(self, timeout_ms: int = 3000) -> bool:
        self._running = False
        if self.isRunning():
            return bool(self.wait(timeout_ms))
        return True

    def run(self):
        self._running = True
        try:
            self._load_model()
        except Exception as exc:
            self.status.emit(f"Modell-Laden fehlgeschlagen: {exc}")
            self._running = False
            return

        self.status.emit(f"Objekterkennung aktiv ({self.config['model']}, {self._device})")
        while self._running:
            item = self._next_frame()
            if item is None:
                self.msleep(50)
                continue

            camera_id, camera_name, frame = item
            try:
                self._analyze_frame(camera_id, camera_name, frame)
            except Exception as exc:
                self.status.emit(f"Objekterkennung Fehler: {exc}")
                self.msleep(500)

    def _load_model(self):
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise RuntimeError("Python-Paket 'ultralytics' ist nicht installiert") from exc

        requested_device = str(self.config.get("device", "auto")).strip().lower()
        if requested_device == "auto":
            try:
                import torch

                self._device = "cuda:0" if torch.cuda.is_available() else "cpu"
            except Exception:
                self._device = "cpu"
        else:
            self._device = requested_device

        model_dir = self.config.get("model_dir") or default_model_dir(self.config.get("recording_path", "."))
        model_path = prepare_model_path(str(self.config.get("model", "yolo11n.pt")), model_dir)
        self.config["model"] = str(model_path)
        self._model = YOLO(str(model_path))
        self._names = dict(getattr(self._model, "names", {}) or {})

    def _next_frame(self):
        now = time.monotonic()
        min_interval = 1.0 / max(0.1, float(self.config.get("analysis_fps_per_camera", 3.0)))

        with self._lock:
            if not self._latest_frames:
                return None
            for camera_id, (_camera_name, _frame, frame_time) in list(self._latest_frames.items()):
                if now - frame_time > 2.0:
                    self._latest_frames.pop(camera_id, None)
                    self._last_analyzed.pop(camera_id, None)
            candidates = sorted(
                self._latest_frames.items(),
                key=lambda item: self._last_analyzed.get(item[0], 0.0),
            )
            for camera_id, (camera_name, frame, _frame_time) in candidates:
                if now - self._last_analyzed.get(camera_id, 0.0) >= min_interval:
                    self._last_analyzed[camera_id] = now
                    return camera_id, camera_name, frame
        return None

    def _analyze_frame(self, camera_id: int, camera_name: str, frame):
        if self._model is None:
            return

        wanted = set(self.config.get("classes") or [])
        results = self._model.predict(
            frame,
            imgsz=int(self.config.get("imgsz", 640)),
            conf=float(self.config.get("confidence", 0.4)),
            device=self._device,
            verbose=False,
        )

        detections = []
        best_by_label: dict[str, dict[str, Any]] = {}
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                label = str(self._names.get(cls_id, cls_id))
                if wanted and label not in wanted:
                    continue
                confidence = float(box.conf[0])
                xyxy = [int(v) for v in box.xyxy[0].tolist()]
                item = {
                    "label": label,
                    "confidence": confidence,
                    "box": xyxy,
                }
                detections.append(item)
                if label not in best_by_label or confidence > best_by_label[label]["confidence"]:
                    best_by_label[label] = item

        if not detections:
            self._decay_stable_hits(camera_id)
            return

        now = time.monotonic()
        stable_frames = max(1, int(self.config.get("stable_frames", 2)))
        cooldown = max(0.0, float(self.config.get("cooldown_seconds", 180)))
        event_suppress = max(0.0, float(self.config.get("event_suppress_seconds", 30)))
        motion_required = set(self.config.get("motion_required_classes") or [])
        motion_min_pixels = max(0.0, float(self.config.get("motion_min_pixels", 12.0)))
        eligible: list[tuple[str, dict[str, Any]]] = []

        if now - self._last_camera_event.get(camera_id, 0.0) < event_suppress:
            self._reset_stable_hits(camera_id)
            return

        for label, best in best_by_label.items():
            key = (camera_id, label)
            if motion_required and label in motion_required and not self._has_required_motion(key, best, motion_min_pixels):
                self._stable_hits[key] = 0
                continue
            self._stable_hits[key] = self._stable_hits.get(key, 0) + 1
            if self._stable_hits[key] < stable_frames:
                continue
            if now - self._last_event.get(key, 0.0) < cooldown:
                continue
            eligible.append((label, best))

        if not eligible:
            return

        label, best = max(eligible, key=lambda item: float(item[1]["confidence"]))
        self._last_event[(camera_id, label)] = now
        self._last_camera_event[camera_id] = now
        self._reset_other_stable_hits(camera_id, label)
        annotated = self._annotate(frame, detections)
        self.detected.emit(
            DetectionResult(
                camera_id=camera_id,
                camera_name=camera_name,
                label=label,
                confidence=float(best["confidence"]),
                detections=detections,
                annotated_frame=annotated,
                timestamp=time.time(),
            )
        )

    def _decay_stable_hits(self, camera_id: int):
        for key in list(self._stable_hits.keys()):
            if key[0] == camera_id:
                self._stable_hits[key] = max(0, self._stable_hits[key] - 1)

    def _reset_stable_hits(self, camera_id: int):
        for key in list(self._stable_hits.keys()):
            if key[0] == camera_id:
                self._stable_hits[key] = 0

    def _reset_other_stable_hits(self, camera_id: int, active_label: str):
        for key in list(self._stable_hits.keys()):
            if key[0] == camera_id and key[1] != active_label:
                self._stable_hits[key] = 0

    def _has_required_motion(self, key: tuple[int, str], detection: dict[str, Any], min_pixels: float) -> bool:
        x1, y1, x2, y2 = detection["box"]
        center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        previous = self._last_motion_box.get(key)
        self._last_motion_box[key] = center
        if previous is None:
            return False
        return math.hypot(center[0] - previous[0], center[1] - previous[1]) >= min_pixels

    def _annotate(self, frame, detections: list[dict[str, Any]]):
        annotated = frame.copy()
        for detection in detections:
            x1, y1, x2, y2 = detection["box"]
            label = detection["label"]
            confidence = detection["confidence"]
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 2)
            text = f"{label} {confidence:.2f}"
            cv2.putText(
                annotated,
                text,
                (x1, max(20, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 200, 255),
                2,
                cv2.LINE_AA,
            )
        return annotated
