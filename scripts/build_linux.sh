#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
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
