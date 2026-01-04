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

- Python 3
- Dependencies listed in `requirements.txt`

If you install dependencies via your distro packages (recommended in Docker/managed envs), ensure at least:

- PyQt6
- OpenCV (`cv2`)
- NumPy
- requests

## Run

```bash
python3 main.py
```

## Configure Cameras

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

### Auto-discover

Open **Auto-Discover**, choose your network (e.g. `192.168.1.0/24`), enter credentials, and start the scan.

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
