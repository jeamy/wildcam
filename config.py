import json
import os

from camera_utils import normalize_reolinkproxy_camera
from detection import DEFAULT_DETECTION_CONFIG
from notifications import DEFAULT_EMAIL_CONFIG


CONFIG_PATH = "camera_config.json"
DEFAULT_RECORDING_PATH = os.path.expanduser("~/Videos/Reolink")


def snapshot_path_for(recording_path: str) -> str:
    return os.path.join(recording_path, "snapshots")


def config_payload(window) -> dict:
    detection_config = dict(window.detection_config)
    detection_config.pop("enabled", None)
    return {
        "cameras": window.cameras,
        "recording_path": window.recording_path,
        "detection": detection_config,
        "email": window.email_config,
        "cameras_per_row": window.cameras_per_row,
        "next_camera_id": window.next_camera_id,
        "language": window.language,
        "order_custom": window._order_custom,
        "preview_camera_ids": list(window.selected_camera_ids),
        "selected_camera_id": window.selected_camera_id,
    }


def save_config_data(config: dict, path: str = CONFIG_PATH):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def _coerce_camera_id(camera: dict):
    try:
        return int(camera.get("id"))
    except Exception:
        return None


def _repair_camera_ids(cameras: list[dict]) -> tuple[list[dict], bool]:
    used_ids = set()
    max_id = 0
    fixed = False
    for camera in cameras:
        camera_id = _coerce_camera_id(camera)
        if camera_id is not None:
            max_id = max(max_id, camera_id)

    repaired = []
    for camera in cameras:
        camera_id = _coerce_camera_id(camera)
        if camera_id is None or camera_id in used_ids:
            max_id += 1
            camera["id"] = max_id
            used_ids.add(max_id)
            fixed = True
        else:
            used_ids.add(camera_id)
        repaired.append(camera)
    return repaired, fixed


def _dedupe_by_url(cameras: list[dict]) -> tuple[list[dict], bool]:
    seen_urls = set()
    deduped = []
    fixed = False
    for camera in cameras:
        url = (camera.get("url") or "").strip()
        if url:
            if url in seen_urls:
                fixed = True
                continue
            seen_urls.add(url)
        if "uid" not in camera:
            camera["uid"] = ""
            fixed = True
        if "detection_enabled" not in camera:
            camera["detection_enabled"] = False
            fixed = True
        deduped.append(camera)
    return deduped, fixed


def repair_cameras(cameras: list[dict], order_custom: bool) -> tuple[list[dict], bool]:
    repaired, ids_fixed = _repair_camera_ids(cameras)
    repaired, urls_fixed = _dedupe_by_url(repaired)
    proxy_fixed = False
    for camera in repaired:
        proxy_fixed = normalize_reolinkproxy_camera(camera) or proxy_fixed
    if not order_custom:
        try:
            repaired.sort(key=lambda camera: int(camera.get("id", 0)))
        except Exception:
            pass
    return repaired, ids_fixed or urls_fixed or proxy_fixed


def load_config_data(path: str = CONFIG_PATH) -> tuple[dict | None, bool]:
    try:
        with open(path, "r") as f:
            raw_config = json.load(f)
    except FileNotFoundError:
        return None, False

    order_custom = bool(raw_config.get("order_custom", False))
    cameras, fixed = repair_cameras(raw_config.get("cameras", []), order_custom)
    next_camera_id = max([camera.get("id", 0) for camera in cameras] + [0]) + 1
    if raw_config.get("next_camera_id") != next_camera_id:
        fixed = True

    valid_camera_ids = {
        int(camera.get("id"))
        for camera in cameras
        if camera.get("id") is not None
    }
    preview_ids = []
    for camera_id in raw_config.get("preview_camera_ids", []):
        try:
            camera_id = int(camera_id)
        except Exception:
            continue
        if camera_id in valid_camera_ids and camera_id not in preview_ids:
            preview_ids.append(camera_id)

    try:
        selected_camera_id = (
            int(raw_config.get("selected_camera_id"))
            if raw_config.get("selected_camera_id") is not None
            else None
        )
    except Exception:
        selected_camera_id = None
    if selected_camera_id not in valid_camera_ids:
        selected_camera_id = None

    config = {
        **raw_config,
        "cameras": cameras,
        "recording_path": raw_config.get("recording_path", DEFAULT_RECORDING_PATH),
        "snapshot_path": snapshot_path_for(raw_config.get("recording_path", DEFAULT_RECORDING_PATH)),
        "detection": {**DEFAULT_DETECTION_CONFIG, **raw_config.get("detection", {})},
        "email": {**DEFAULT_EMAIL_CONFIG, **raw_config.get("email", {})},
        "cameras_per_row": raw_config.get("cameras_per_row", 3),
        "next_camera_id": next_camera_id,
        "language": raw_config.get("language", "de"),
        "order_custom": order_custom,
        "preview_camera_ids": preview_ids,
        "selected_camera_id": selected_camera_id,
    }
    return config, fixed
