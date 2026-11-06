# wildcam

`wildcam` is a PyQt6-based multi-camera viewer optimized for parallel RTSP streams (e.g. Reolink).
It also shows Netvue cameras (e.g. Orb Mini), which have no RTSP, over their local LAN protocol.

## Features

- **Multi-camera list + large preview** (select a camera on the left)
- **Per-camera controls**
  - Start/stop stream
  - Start/stop recording
  - Snapshot
  - Edit/remove camera
- **Auto-discovery** (network scan: ONVIF, RTSP, Reolink, Netvue)
- **Camera types**
  - RTSP cameras (Reolink, Tapo, other ONVIF/RTSP cameras)
  - Reolink WLAN/battery cameras via ReolinkProxy
  - Netvue cameras via their local LAN protocol (`netvue://` URL, see [Netvue cameras](#netvue-cameras))
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
- **Live statistics in the toolbar**: app memory (RAM), network activity
  (download/upload of the whole system), data received since start and the
  frame rate of the active camera (Σ = all running streams)
- **Restores the last session**: open preview cameras, window position/size
  and maximized state are stored in `camera_config.json`
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

Object detection is optional. WildCam installs Ultralytics YOLO / PyTorch on
first use into the user's app-data directory instead of bundling it with the
main app.

## Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

To preinstall the optional object-detection stack in a development environment:

```bash
pip install -r requirements-detection.txt
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
  - WildCam automatically switches the stored RTSP URL to
    `rtsp://localhost:8554/<NAME>/mainStream` and keeps the real camera
    address/credentials in a `proxy` block, so the app uses the
    ReolinkProxy-proxied stream.
  - `reolinkproxy.env` is written from that via the
    **Generate ReolinkProxy config** button (configuration tab) or by
    `start_wildcam.sh`.

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

#### Quick start from source (recommended)

```bash
./start_wildcam.sh
```

This will:

- Generate/extend `reolinkproxy.env` based on `camera_config.json`
- Start ReolinkProxy via Docker
- Start WildCam

#### Quick start with a release build

1. Start WildCam and add your cameras.
2. Open the configuration tab and click **Generate ReolinkProxy config**.
   WildCam writes `reolinkproxy.env` (file mode `600`, it contains the camera
   passwords) next to `camera_config.json`, plus a `docker-compose.yml` if
   there is none yet. The dialog shows the directory (macOS:
   `~/Library/Application Support/WildCam`).
3. Start or restart the proxy in that directory:

   ```bash
   docker compose up -d --force-recreate
   ```

No Python installation is needed for this.

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

Where the file lives:

- **Source checkout, Linux and Windows builds:** in the current working
  directory (usually the folder you start WildCam from).
- **macOS app (`wildcam.app`):** in `~/Library/Application Support/WildCam/`,
  because apps started from the Finder have `/` as working directory. If a
  `camera_config.json` exists in the working directory on first start, it is
  copied there once. `reolinkproxy.env` and `docker-compose.yml` from
  **Generate ReolinkProxy config** are written to the same folder.

- The file is **gitignored** because it can contain **credentials** inside RTSP URLs
  and the local keys of Netvue cameras. They are only stored there, never in the repository.
- `reolinkproxy.env` is generated from this file and should not be edited as the primary configuration.
- UI state is stored there too: `preview_camera_ids` (open previews),
  `window_geometry` (position, size, maximized) and `ptz_pad_visible`. A stored
  window position is only applied if it is still visible on a connected screen.
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
  - **`url`** is the RTSP URL, or `netvue://<user id>:<local key>@<ip>:5555` for a
    [Netvue camera](#netvue-cameras). Both can contain credentials.
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
    "model": "yolo26n.pt",
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
The default model is `yolo26n.pt` (Ultralytics YOLO26, nano), a small, fast
model suitable for multi-camera testing. For a GTX 1660 Ti, start with:

```json
"analysis_fps_per_camera": 3.0,
"imgsz": 640,
"model": "yolo26n.pt"
```

Known model names are downloaded automatically into the model folder
(`~/Videos/Reolink/models`): `yolo26n/s/m/l/x.pt` (recommended, needs
`ultralytics>=8.4.0`), `yolo11n/s/m/l/x.pt` and `yolov8n/s/m/l/x.pt`. Larger
letters are more accurate but slower. Any other `.pt` file can be used by
entering its full path. An older ultralytics from a previous WildCam install
is upgraded automatically the next time detection starts. Existing
configurations keep their model until you change it.

All of these models are trained on COCO (80 classes). Animals covered are
`bird`, `cat`, `dog`, `horse`, `sheep`, `cow`, `elephant`, `bear`, `zebra`
and `giraffe`; deer, foxes, wild boar or martens are **not** separate classes
and need a custom-trained model.

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

Release builds do not bundle the Python detection libraries. When object
detection is enabled or **Install/test runtime/model** is clicked for the first time,
WildCam installs the optional runtime into the user's app-data directory:

```text
Linux:   ~/.local/share/wildcam/detection-runtime/py<version>
macOS:   ~/Library/Application Support/WildCam/detection-runtime/py<version>
Windows: %LOCALAPPDATA%\WildCam\detection-runtime\py<version>
```

In standalone builds this requires a matching external Python with `pip` and
internet access. Linux installs CPU-only PyTorch wheels by default to avoid
bundling CUDA/NVIDIA libraries. YOLO model weights are resolved by Ultralytics
from the configured model name/path, so the first detection run must either be
able to download the model or point `detection.model` to a local weights file.

The **Install/test runtime/model** button stores known YOLO weights in:

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

WildCam will automatically store the camera in `camera_config.json` as
`rtsp://localhost:8554/<NAME>/mainStream` (plus a `proxy` block). Click
**Generate ReolinkProxy config** afterwards to add it to `reolinkproxy.env`.

For a Netvue camera enter its `netvue://` URL (see [Netvue cameras](#netvue-cameras)):

```text
netvue://<user id>:<local key>@192.168.1.120:5555
```

### Auto-discover

Open **Auto-Discover**, choose your network (e.g. `192.168.1.0/24`), enter credentials, and start the scan.

The scan combines:

- **ONVIF WS-Discovery** (name/model; with credentials also the exact RTSP URL via `GetStreamUri`)
- a parallel **port scan** (554, 8554, 80, 443, 8000, 9000, 2020, 8899, 5555)
- the **Reolink HTTP API** (vendor; with credentials model, name and P2P UID)
- a **Netvue** protocol check on port 5555 (see [Netvue cameras](#netvue-cameras))

Hosts of cameras already in your list are scanned a second time with a longer
timeout (WLAN cameras often miss the fast scan). Results are matched against
the list by UID, MAC and IP; matches are shown in the *In list* column and are
not pre-selected. The ReolinkProxy host itself is ignored.

When you add found Reolink WLAN/battery cameras (port 9000 only, or a battery
model), WildCam stores `localhost:8554/...` URLs plus a `proxy` block in
`camera_config.json`. Click **Generate ReolinkProxy config** (or run
`start_wildcam.sh`) and restart the proxy afterwards; until then the camera
shows *Not in proxy*.

### ReolinkProxy status

For idle proxy cameras WildCam asks ReolinkProxy every 60 s with an RTSP
`DESCRIBE` (this does not wake the camera). The camera tile shows:

- *Proxy ready* – stream registered, the proxy has connected before (the camera may be asleep)
- *Camera unreachable* – the proxy cannot reach the camera (e.g. UID discovery timed out)
- *Not in proxy* – camera missing from `reolinkproxy.env`
- *ReolinkProxy is not running* – nothing listens on port 8554

ReolinkProxy is a **proxy** and does not magically discover/wake sleeping cameras. The camera still needs to be reachable (awake) for discovery and for ReolinkProxy to connect.

Important:

- WildCam writes `reolinkproxy.env` (button **Generate ReolinkProxy config**), but the actual ReolinkProxy must run separately.
- The recommended setup in this repository is the Docker Compose stack from `docker-compose.yml`.

### Pan/tilt (PTZ) control

When the selected camera can pan/tilt, a control cross appears in the
bottom-right corner of the big preview: press and hold an arrow to move,
release to stop. The ✥ button collapses/expands the cross (remembered).

Detection (runs once in the background, stored as `"ptz"` per camera):

- **ONVIF cameras** (e.g. Tapo): PTZ service + PTZ profile → pan/tilt
- **Native Reolink cameras**: `GetAbility` (`ptzCtrl`/`ptzType`)
- **ReolinkProxy cameras**: the proxy reports PTZ for every camera, so they
  count as pan/tilt by default; control goes through the proxy's ONVIF PTZ
  service (requires ReolinkProxy **0.2.7 or newer**)

The automatic result can be overridden per camera in the edit dialog
(*Pan/tilt camera*).

## Netvue cameras

Netvue cameras (e.g. **Orb Mini**) have no RTSP, ONVIF or web interface; the
only open port is TCP **5555**. The Netvue app streams live video over this
port directly in the LAN with a small proprietary protocol, which WildCam
speaks as well (`netvue.py`): login with the app's **local key**, then H.264
video (1920×1080 on the Orb Mini). Nothing on the camera is changed.

Camera URL:

```text
netvue://<user id>:<local key>@<camera ip>:5555
```

Optional `?quality=0..3` (0 auto, 1 HD = default, 2 balanced, 3 SD).

### Reading user id and local key

Both are stored by the Netvue app and written to the Android log when the
live view opens. With wireless debugging (Developer options → *Wireless
debugging*) or USB debugging enabled:

1. Open the camera's live view in the Netvue app.
2. On the PC (source checkout):

   ```bash
   adb logcat -d | python3 netvue.py from-log
   ```

   This prints the complete `netvue://` URL for every camera the app has
   opened. Without the source checkout, search the log manually:
   `adb logcat -d | grep doLogin` shows `user:<USER> ... localKey:<KEY>`.

The local key is a password for the camera's video: keep it private. It is
stored only in your local `camera_config.json` (gitignored) like RTSP
passwords; there is no separate key file. Raw test recordings (`*.h264`)
are gitignored as well.

### Adding the camera

- **Auto-Discover** lists Netvue cameras (manufacturer *Netvue*) after a
  protocol check on port 5555, so other devices on that port (e.g. Android
  ADB) are not listed. After adding, WildCam asks for the key.
- **Edit dialog:** choose path `netvue`, enter IP, user id (*Username*) and
  local key (*Password*), click **Build URL**. Port 5555 is filled in.
- Or paste the URL from `from-log` as RTSP URL when adding a camera.

How it works: `netvue.py` connects to the camera, logs in and requests the
live channel; a small bridge on `127.0.0.1` passes the H.264 video to the
normal stream thread, which reads it with OpenCV/FFmpeg like an RTSP stream.
The protocol (packet header, commands, error codes) is documented at the top
of `netvue.py`.

Notes:

- Preview, recording, snapshots and object detection work as for RTSP
  cameras. Audio is not used. Opening the stream takes about 5 s.
- Pan/tilt (the Orb Mini can pan) is not supported yet; it would need the
  Netvue control commands.
- If the camera rejects the key (*local key invalid*), open the live view in
  the Netvue app again and read the key anew. A Netvue firmware or app
  update may change the protocol.
- Test without WildCam: `python3 netvue.py <ip> --user <USER> --key <KEY>`
  saves 8 s of raw H.264 to `netvue_test.h264`.

## Battery Cameras

### Automatic ReolinkProxy Setup

WildCam includes automatic ReolinkProxy setup for battery cameras using port 9000 (Baichuan protocol).

This is handled in two places:

- The **GUI** automatically switches Reolink WLAN/Baichuan cameras to `rtsp://localhost:8554/...`
  and writes `reolinkproxy.env` when you click **Generate ReolinkProxy config**.
- The **startup script** (source checkout only) generates `reolinkproxy.env` and starts the ReolinkProxy container for you.

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

If you prefer manual control (source checkout; with a release build use the
**Generate ReolinkProxy config** button instead of step 1):

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

- the bundle includes the app, `docker-compose.yml`, `camera_config.json.example` and `README.md`
- `reolinkproxy.env` is not bundled because it is generated locally and contains credentials;
  the app generates it (button **Generate ReolinkProxy config**)
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

- The packaged app bundles WildCam, `docker-compose.yml`, `camera_config.json.example` and `README.md`.
  The `reolinkproxy.env` generator is built into the app (button **Generate ReolinkProxy config**).
- The actual ReolinkProxy runtime (Docker image `ghcr.io/shareed2k/reolinkproxy`) is **not** bundled into the app archive.
- The optional object-detection runtime is **not** bundled into the app archive;
  it is installed on first use.
- If you use only normal RTSP cameras, the standalone app is enough.
- If you use Reolink WLAN / battery cameras, you must additionally run ReolinkProxy externally.

### Linux

```bash
bash scripts/build_linux.sh
```

Output:

- Bundle: `dist/wildcam/`
- Zip archive: `dist/wildcam_linux_<timestamp>.zip`
- AppImage: `dist/wildcam_linux_<timestamp>.AppImage`

### macOS

```bash
bash scripts/build_macos.sh
```

Output:

- App bundle: `dist/wildcam.app`
- Zip archive: `dist/wildcam_<platform>_<timestamp>.zip`

### Windows (PowerShell)

```powershell
scripts\build_windows.ps1
```

Or via CMD wrapper:

```bat
scripts\build_windows.cmd
```

Output:

- Bundle: `dist\wildcam\` (contains `wildcam.exe`)
- Zip archive: `dist\wildcam_windows_<timestamp>.zip`

### Release via GitHub Actions

`.github/workflows/build.yml` is started manually (*Actions → Build App → Run
workflow*) with a tag (e.g. `v1.0.0`) and a source ref (default `master`). It
creates or moves the tag, builds Linux (zip + AppImage), Windows, macOS Intel
and macOS Apple Silicon with the scripts above, and attaches the archives to
the GitHub release for that tag.
