#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
APP_NAME="${APP_NAME:-wildcam}"
ENTRY_POINT="${ENTRY_POINT:-main.py}"

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
  --onefile \
  --windowed \
  --name "$APP_NAME" \
  --add-data "assets/icons:assets/icons" \
  "$ENTRY_POINT"

EXE_PATH="$DIST_DIR/$APP_NAME"
if [[ ! -f "$EXE_PATH" ]]; then
  echo "Build failed: binary not found at $EXE_PATH" >&2
  exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
ZIP_PATH="$DIST_DIR/${APP_NAME}_linux_${TS}.zip"

export EXE_PATH
export ZIP_PATH

"$PY" - <<PY
import os
import zipfile

exe_path = os.environ.get("EXE_PATH")
zip_path = os.environ.get("ZIP_PATH")

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
    z.write(exe_path, arcname=os.path.basename(exe_path))

print(f"BIN: {exe_path}")
print(f"ZIP: {zip_path}")
PY
