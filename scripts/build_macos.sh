#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
APP_NAME="${APP_NAME:-wildcam}"
ENTRY_POINT="${ENTRY_POINT:-main.py}"
PLATFORM="${PLATFORM:-macos}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f "$ENTRY_POINT" ]]; then
  echo "Entry point not found: $ENTRY_POINT" >&2
  exit 1
fi

VENV_DIR="$REPO_ROOT/.venv"
DIST_DIR="$REPO_ROOT/dist"
BUILD_DIR="$REPO_ROOT/build"

if [[ -d "$VENV_DIR" ]]; then
  VENV_PY="$VENV_DIR/bin/python"
  if [[ -x "$VENV_PY" ]]; then
    VENV_VERSION="$($VENV_PY -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    REQUESTED_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$VENV_VERSION" != "$REQUESTED_VERSION" ]]; then
      if [[ "${RECREATE_VENV:-0}" == "1" ]]; then
        rm -rf "$VENV_DIR"
      else
        echo "Existing venv uses Python $VENV_VERSION but requested is $REQUESTED_VERSION." >&2
        echo "Delete $VENV_DIR or re-run with RECREATE_VENV=1" >&2
        exit 1
      fi
    fi
  fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

"$PY" -m pip install --upgrade pip

if [[ -f "requirements.txt" ]]; then
  "$PIP" install -r requirements.txt
fi

"$PIP" install "pyinstaller>=6.0"

rm -rf "$DIST_DIR" "$BUILD_DIR"

"$PY" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "$APP_NAME" \
  --add-data "assets/icons:assets/icons" \
  --collect-all "PyQt6" \
  --collect-all "cv2" \
  --collect-all "numpy" \
  "$ENTRY_POINT"

BUNDLE_PATH="$DIST_DIR/${APP_NAME}.app"
if [[ ! -e "$BUNDLE_PATH" ]]; then
  BUNDLE_PATH="$DIST_DIR/$APP_NAME"
fi

if [[ ! -e "$BUNDLE_PATH" ]]; then
  echo "Build failed: bundle not found under $DIST_DIR" >&2
  exit 1
fi

if [[ -d "$BUNDLE_PATH" ]]; then
  for extra_file in README.md docker-compose.yml neolink_manager.py camera_config.json.example; do
    if [[ -f "$extra_file" ]]; then
      cp "$extra_file" "$BUNDLE_PATH/"
    fi
  done

  if [[ -f "neolink.toml" ]]; then
    cp "neolink.toml" "$BUNDLE_PATH/"
  fi
fi

TS="$(date +%Y%m%d_%H%M%S)"
ZIP_PATH="$DIST_DIR/${APP_NAME}_${PLATFORM}_${TS}.zip"

export BUNDLE_PATH
export ZIP_PATH

"$PY" - <<PY
import os
import zipfile

bundle_path = os.environ.get("BUNDLE_PATH")
zip_path = os.environ.get("ZIP_PATH")
parent_dir = os.path.dirname(bundle_path)

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
    if os.path.isdir(bundle_path):
        for root, _, files in os.walk(bundle_path):
            for file_name in files:
                full_path = os.path.join(root, file_name)
                arcname = os.path.relpath(full_path, parent_dir)
                z.write(full_path, arcname=arcname)
    else:
        z.write(bundle_path, arcname=os.path.relpath(bundle_path, parent_dir))

print(f"BUNDLE: {bundle_path}")
print(f"ZIP: {zip_path}")
PY
