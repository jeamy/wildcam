# wildcam

`wildcam` is a PyQt6-based multi-camera viewer optimized for parallel RTSP streams (e.g. Reolink).

## Features

- **Multi-camera list + large preview** (select a camera on the left)
- **Per-camera controls**
  - Start/stop stream
  - Start/stop recording
  - Snapshot
  - Edit/remove camera
- **Auto-discovery** (network scan)
- **Recording & snapshots**
  - Default recordings folder: `~/Videos/Reolink`
  - Snapshots are stored in `~/Videos/Reolink/snapshots`
- **Object detection alerts**
  - Uses Ultralytics YOLO when installed
  - Automatically selects CUDA when PyTorch detects an NVIDIA GPU, otherwise CPU
  - Can be enabled per camera from the camera tile
  - Saves annotated detection snapshots and short event clips
  - Can send optional SMTP email alerts with the detection image attached
  - Includes a settings-page test mail button for SMTP checks
- **UI language switch** (German/English), stored in `camera_config.json`

## License

WildCam is licensed under **AGPL-3.0-or-later**. The object detection
integration uses Ultralytics YOLO, whose default open-source license is
AGPL-3.0. If you distribute modified versions or run a network-accessible
modified version, make the corresponding source available as required by the
AGPL.

## Requirements

- Python 3.12 (tested)
- Dependencies listed in `requirements.txt`

It is recommended to use a virtual environment (venv).

If you install dependencies via your distro packages (recommended in Docker/managed envs), ensure at least:

- PyQt6
- OpenCV (`cv2`)
- NumPy
- requests
- Ultralytics YOLO / PyTorch for object detection

## Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

`./start_wildcam.sh` activates `.venv`/`venv` automatically. If no virtual
environment exists, it creates `.venv`; before starting WildCam it runs
`python3 -m pip install -r requirements.txt` so missing packages are installed.

## Configure Cameras

### Reolink cameras: recommended setup

WildCam supports two ways to connect Reolink cameras:

- **Native RTSP (port 554)**
  - Works well for mains-powered cameras.
- **ReolinkProxy (recommended for Reolink WLAN / battery cameras)**
  - Many Reolink WLAN/battery models use the **Baichuan protocol (port 9000)**.
  - WildCam will automatically:
    - add/update `reolinkproxy.env`
    - switch the stored RTSP URL to `rtsp://localhost:8554/<NAME>/mainStream`
    - so the app uses the ReolinkProxy-proxied stream

#### What gets stored where

- **`camera_config.json`**
  - What the app actually uses at runtime.
  - After ReolinkProxy conversion, URLs look like:
    - `rtsp://localhost:8554/D58/mainStream`
- **`reolinkproxy.env`**
  - Contains the real camera IP/credentials for port 9000 cameras.
  - Example:
    - `REOLINK_CAMERA_0_HOST="192.168.8.58"`
    - `REOLINK_CAMERA_0_RTSP_PATH="D58/mainStream"`

#### Quick start (recommended)

```bash
./start_wildcam.sh
```

This will:

- Generate/extend `reolinkproxy.env` based on `camera_config.json`
- Start ReolinkProxy via Docker
- Start WildCam

Important:

- WildCam manages the ReolinkProxy configuration, but it does **not** embed the actual `reolinkproxy` runtime.
- For Reolink WLAN / battery cameras you still need a running ReolinkProxy instance, typically via `docker compose up -d`.
- For regular RTSP cameras on port 554, ReolinkProxy is not required.

## Configuration File (`camera_config.json`)

This app stores your local setup in `camera_config.json`.

You usually **do not need to create this file manually**:

- The app will **create and update** `camera_config.json` automatically when you add/edit/remove cameras via the GUI.
- Auto-Discover results are stored there as well.
- Reordering cameras via drag & drop updates the stored order.

Manual editing is optional (e.g. to bulk-edit RTSP URLs or names).

- The file is **gitignored** because it can contain **credentials** inside RTSP URLs.
- `reolinkproxy.env` is generated from this file and should not be edited as the primary configuration.
- Use `camera_config.json.example` as a safe template and create your local config from it.

### Create your local config

```bash
cp camera_config.json.example camera_config.json
```

Then edit `camera_config.json` and replace IPs / usernames / passwords.

### Schema

- **`cameras`**
  - List of camera objects, in the exact order they appear on the left.
  - **`id`** must be unique.
  - **`url`** is the RTSP URL.
  - **`name`** is the display name.
  - **`detection_enabled`** enables object detection for that camera.
  - **`proxy`** is optional and contains ReolinkProxy connection settings for battery/WLAN cameras.
- **`recording_path`**
  - Target directory for recordings.
- **`detection`**
  - Object detection settings.
  - `device: "auto"` uses CUDA when available and falls back to CPU.
  - Event snapshots are saved below `snapshots`.
  - Event clips are saved below `events`.
- **`email`**
  - Optional SMTP alert settings.
  - Disabled by default.
- **`next_camera_id`**
  - Internal counter for assigning new IDs.
- **`language`**
  - UI language (`de` or `en`).
- **`order_custom`**
  - `false`: default sort by `id` on startup.
  - `true`: keep the stored order from the file (after you reorder via drag & drop).

Example snippet:

```json
{
  "cameras": [
    {
      "id": 1,
      "url": "rtsp://localhost:8554/D54/mainStream",
      "name": "D54",
      "uid": "9527000000000000",
      "proxy": {
        "type": "reolinkproxy",
        "host": "192.168.1.100",
        "port": 9000,
        "username": "admin",
        "password": "password",
        "stream": "main",
        "battery": true,
        "pause_on_client": true,
        "idle_disconnect": true,
        "idle_timeout": "30s"
      }
    }
  ],
  "recording_path": "/home/USER/Videos/Reolink",
  "detection": {
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
    "motion_required_classes": ["bicycle", "car", "motorcycle", "bus", "truck"],
    "motion_min_pixels": 12.0,
    "classes": ["person", "car", "truck", "dog", "cat", "bird"]
  },
  "email": {
    "enabled": false,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
    "use_tls": true,
    "from": "",
    "to": []
  },
  "next_camera_id": 2,
  "language": "de",
  "order_custom": false
}
```

## Object Detection

Detection is controlled through `camera_config.json` and each camera tile's
`AI` button.
The default model is `yolo11n.pt`, which is a small, fast model suitable for
multi-camera testing. For a GTX 1660 Ti, start with:

```json
"analysis_fps_per_camera": 3.0,
"imgsz": 640,
"model": "yolo11n.pt"
```

When an object is detected for `stable_frames` consecutive analysis frames,
the per-camera/per-class `cooldown_seconds` has elapsed, and the camera-wide
`event_suppress_seconds` burst lock has elapsed, WildCam:

- saves an annotated JPEG snapshot in `~/Videos/Reolink/snapshots`
- starts an AVI event clip in `~/Videos/Reolink/events`
- sends an email with the image attached if `email.enabled` is `true`

`event_clip_seconds` controls the total event video length and is capped at
180 seconds. `pre_event_seconds` is included in that total length.

Classes listed in `motion_required_classes` only trigger an event when the
detected bounding box moves by at least `motion_min_pixels` between analyzed
frames. By default this is enabled for vehicle classes, so parked cars do not
create repeated alerts.

Pretrained COCO classes include `person`, vehicles, and common animals such as
`dog`, `cat`, `bird`, `horse`, `sheep`, and `cow`. Wild animals such as deer,
foxes, or boars usually need a custom fine-tuned model for reliable alerts.

Release builds include the Python detection libraries. YOLO model weights are
resolved by Ultralytics from the configured model name/path, so the first run
must either be able to download the model or point `detection.model` to a local
weights file.

The **Download/test model** button stores known YOLO weights in:

```text
<recording_path>/models
```

For the default path this is:

```text
~/Videos/Reolink/models
```

### Add camera manually

1. Enter the camera RTSP URL
2. Optionally set a name
3. Click **Add**

Example RTSP URL:

```text
rtsp://admin:password@192.168.1.100:554/h264Preview_01_main
```

For Reolink WLAN / Baichuan (port 9000) you can also enter:

```text
rtsp://admin:password@192.168.1.100:9000/h264Preview_01_main
```

WildCam will automatically:

- append/update the camera entry in `reolinkproxy.env`
- store the camera in `camera_config.json` as:
  - `rtsp://localhost:8554/<NAME>/mainStream`

### Auto-discover

Open **Auto-Discover**, choose your network (e.g. `192.168.1.0/24`), enter credentials, and start the scan.

When you add found Reolink WLAN/battery cameras, WildCam will automatically:

- update `reolinkproxy.env`
- store `localhost:8554/...` URLs in `camera_config.json`

ReolinkProxy is a **proxy** and does not magically discover/wake sleeping cameras. The camera still needs to be reachable (awake) for discovery and for ReolinkProxy to connect.

Important:

- WildCam writes and updates `reolinkproxy.env`, but the actual ReolinkProxy must run separately.
- The recommended setup in this repository is the Docker Compose stack from `docker-compose.yml`.

## Battery Cameras

### Automatic ReolinkProxy Setup

WildCam includes automatic ReolinkProxy setup for battery cameras using port 9000 (Baichuan protocol).

This is handled in two places:

- The **GUI** automatically switches Reolink WLAN/Baichuan cameras to `rtsp://localhost:8554/...` and appends the camera to `reolinkproxy.env`.
- The **startup script** can start the ReolinkProxy container for you.

#### Quick Start

```bash
# 1. Start WildCam with automatic ReolinkProxy setup
./start_wildcam.sh
```

**What it does:**
- ✅ Detects battery cameras (port 9000) in `camera_config.json`
- Auto-generates `reolinkproxy.env` configuration
- Starts ReolinkProxy Docker container
- ✅ The app stores/uses `rtsp://localhost:8554/...` URLs for these cameras

#### Manual Setup

If you prefer manual control:

```bash
# 1. Generate reolinkproxy.env from your camera config
python3 reolinkproxy_manager.py --auto-update

# 2. Start ReolinkProxy container
docker compose up -d

# 3. Check ReolinkProxy logs
docker logs wildcam-reolinkproxy

# 4. Start WildCam
python3 main.py
```

If you distribute WildCam as a standalone build:

- the bundle can include `docker-compose.yml`, `reolinkproxy_manager.py`, `camera_config.json.example`, and the app itself
- `reolinkproxy.env` is not bundled because it is generated locally and can contain credentials
- but it still does **not** include the external ReolinkProxy container/image
- users who rely on Reolink battery / Baichuan cameras still need Docker/Compose or a separately installed `reolinkproxy`

#### How it Works

**1. Detection:**
The script scans `camera_config.json` for cameras using port 9000:
```json
{
  "id": 7,
  "url": "rtsp://admin:password@192.168.8.58:9000/h264Preview_01_main",
  "name": "ArgusCamera",
  "uid": "9527000KVKX2161S"
}
```

**2. ReolinkProxy Config Generation:**
Creates `reolinkproxy.env` automatically:
```env
REOLINK_CAMERA_0_NAME="ArgusCamera"
REOLINK_CAMERA_0_HOST="192.168.8.58"
REOLINK_CAMERA_0_PORT=9000
REOLINK_CAMERA_0_USERNAME="admin"
REOLINK_CAMERA_0_PASSWORD="password"
REOLINK_CAMERA_0_UID="9527000KVKX2161S"
REOLINK_CAMERA_0_RTSP_PATH="ArgusCamera/mainStream"
REOLINK_CAMERA_0_BATTERY_CAMERA=true
REOLINK_CAMERA_0_PAUSE_ON_CLIENT=true
REOLINK_CAMERA_0_IDLE_DISCONNECT=true
```

**3. URL Conversion (Optional):**
Updates camera URLs to use ReolinkProxy:
```
Before: rtsp://admin:password@192.168.8.58:9000/...
After:  rtsp://localhost:8554/ArgusCamera/mainStream
```

#### Stopping ReolinkProxy

```bash
docker compose down
```

## Recording / Snapshots

- **Recording** writes MP4 files to the selected storage directory.
- **Snapshot** saves a JPG from the last received frame.

## Build (Standalone Binaries)

The repository contains helper scripts using PyInstaller.

Note about ReolinkProxy:

- The packaged app bundles WildCam and helper files such as `docker-compose.yml` and `reolinkproxy_manager.py`.
- The actual ReolinkProxy runtime is **not** bundled into the app archive.
- If you use only normal RTSP cameras, the standalone app is enough.
- If you use Reolink WLAN / battery cameras, you must additionally run ReolinkProxy externally.

### Linux

```bash
bash scripts/build_linux.sh
```

Output:

- Binary: `dist/wildcam`
- Zip archive: `dist/wildcam_linux_<timestamp>.zip`

### Windows (PowerShell)

```powershell
scripts\build_windows.ps1
```

Or via CMD wrapper:

```bat
scripts\build_windows.cmd
```

Output:

- EXE: `dist\wildcam.exe`
- Zip archive: `dist\wildcam_windows_<timestamp>.zip`
