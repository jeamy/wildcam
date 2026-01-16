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
- **UI language switch** (German/English), stored in `camera_config.json`

## Requirements

- Python 3.12 (tested)
- Dependencies listed in `requirements.txt`

It is recommended to use a virtual environment (venv).

If you install dependencies via your distro packages (recommended in Docker/managed envs), ensure at least:

- PyQt6
- OpenCV (`cv2`)
- NumPy
- requests

## Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Configure Cameras

### Reolink cameras: recommended setup

WildCam supports two ways to connect Reolink cameras:

- **Native RTSP (port 554)**
  - Works well for mains-powered cameras.
- **Neolink proxy (recommended for Reolink WLAN / battery cameras)**
  - Many Reolink WLAN/battery models use the **Baichuan protocol (port 9000)**.
  - WildCam will automatically:
    - add/update `neolink.toml`
    - switch the stored RTSP URL to `rtsp://localhost:8554/<NAME>/mainStream`
    - so the app uses the Neolink-proxied stream

#### What gets stored where

- **`camera_config.json`**
  - What the app actually uses at runtime.
  - After Neolink conversion, URLs look like:
    - `rtsp://localhost:8554/D58/mainStream`
- **`neolink.toml`**
  - Contains the real camera IP/credentials for port 9000 cameras.
  - Example:
    - `address = "192.168.8.58:9000"`

#### Quick start (recommended)

```bash
./start_wildcam.sh
```

This will:

- Generate/extend `neolink.toml` based on `camera_config.json`
- Start Neolink via Docker
- Start WildCam

## Configuration File (`camera_config.json`)

This app stores your local setup in `camera_config.json`.

You usually **do not need to create this file manually**:

- The app will **create and update** `camera_config.json` automatically when you add/edit/remove cameras via the GUI.
- Auto-Discover results are stored there as well.
- Reordering cameras via drag & drop updates the stored order.

Manual editing is optional (e.g. to bulk-edit RTSP URLs or names).

- The file is **gitignored** because it can contain **credentials** inside RTSP URLs.
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
- **`recording_path`**
  - Target directory for recordings.
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
      "url": "rtsp://USER:PASS@192.168.1.100:554/h264Preview_01_main",
      "name": "Camera 1"
    }
  ],
  "recording_path": "/home/USER/Videos/Reolink",
  "next_camera_id": 2,
  "language": "de",
  "order_custom": false
}
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

- append/update the camera entry in `neolink.toml`
- store the camera in `camera_config.json` as:
  - `rtsp://localhost:8554/<NAME>/mainStream`

### Auto-discover

Open **Auto-Discover**, choose your network (e.g. `192.168.1.0/24`), enter credentials, and start the scan.

When you add found Reolink WLAN/battery cameras, WildCam will automatically:

- update `neolink.toml`
- store `localhost:8554/...` URLs in `camera_config.json`

Neolink is a **proxy** and does not magically discover/wake sleeping cameras. The camera still needs to be reachable (awake) for discovery and for Neolink to connect.

## Battery Cameras

### Automatic Neolink Setup ⭐

WildCam includes automatic Neolink setup for battery cameras using port 9000 (Baichuan protocol).

This is handled in two places:

- The **GUI** automatically switches Reolink WLAN/Baichuan cameras to `rtsp://localhost:8554/...` and appends the camera to `neolink.toml`.
- The **startup script** can start the Neolink container for you.

#### Quick Start

```bash
# 1. Start WildCam with automatic Neolink setup
./start_wildcam.sh
```

**What it does:**
- ✅ Detects battery cameras (port 9000) in `camera_config.json`
- ✅ Auto-generates `neolink.toml` configuration
- ✅ Starts Neolink Docker container
- ✅ The app stores/uses `rtsp://localhost:8554/...` URLs for these cameras

#### Manual Setup

If you prefer manual control:

```bash
# 1. Generate neolink.toml from your camera config
python3 neolink_manager.py

# 2. Start Neolink container
docker compose up -d

# 3. Check Neolink logs
docker logs wildcam-neolink

# 4. Start WildCam
python3 main.py
```

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

**2. Neolink Config Generation:**
Creates `neolink.toml` automatically:
```toml
[[cameras]]
name = "ArgusCamera"
username = "admin"
password = "password"
address = "192.168.8.58:9000"
uid = "9527000KVKX2161S"
idle_disconnect = true
```

**3. URL Conversion (Optional):**
Updates camera URLs to use Neolink:
```
Before: rtsp://admin:password@192.168.8.58:9000/...
After:  rtsp://localhost:8554/ArgusCamera/mainStream
```

#### Stopping Neolink

```bash
docker compose down
```

## Recording / Snapshots

- **Recording** writes MP4 files to the selected storage directory.
- **Snapshot** saves a JPG from the last received frame.

## Build (Standalone Binaries)

The repository contains helper scripts using PyInstaller.

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
