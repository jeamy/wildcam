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
