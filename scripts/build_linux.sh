#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
APP_NAME="${APP_NAME:-wildcam}"
ENTRY_POINT="${ENTRY_POINT:-main.py}"
PLATFORM="${PLATFORM:-linux}"
APP_VERSION="${APP_VERSION:-dev}"
ARTIFACT_SUFFIX="${ARTIFACT_SUFFIX:-$(date +%Y%m%d_%H%M%S)}"

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

BUNDLE_PATH="$DIST_DIR/$APP_NAME"
if [[ ! -d "$BUNDLE_PATH" ]]; then
  echo "Build failed: bundle not found at $BUNDLE_PATH" >&2
  exit 1
fi

for extra_file in README.md docker-compose.yml neolink_manager.py camera_config.json.example; do
  if [[ -f "$extra_file" ]]; then
    cp "$extra_file" "$BUNDLE_PATH/"
  fi
done

if [[ -f "neolink.toml" ]]; then
  cp "neolink.toml" "$BUNDLE_PATH/"
fi

APPDIR_PATH="$BUILD_DIR/${APP_NAME}.AppDir"
APPDIR_USR_BIN="$APPDIR_PATH/usr/bin"
APPDIR_USR_LIB="$APPDIR_PATH/usr/lib/$APP_NAME"
APPDIR_APPRUN="$APPDIR_PATH/AppRun"
DESKTOP_FILE="$BUILD_DIR/${APP_NAME}.desktop"
ICON_PATH="$BUILD_DIR/${APP_NAME}.png"
LAUNCHER_PATH="$APPDIR_USR_BIN/$APP_NAME"
APPIMAGE_TOOL="$BUILD_DIR/appimagetool-x86_64.AppImage"

rm -rf "$APPDIR_PATH"
mkdir -p "$APPDIR_USR_BIN" "$APPDIR_USR_LIB"
cp -a "$BUNDLE_PATH/." "$APPDIR_USR_LIB/"

cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$HERE/../lib/$APP_NAME/$APP_NAME" "\$@"
EOF
chmod +x "$LAUNCHER_PATH"

cat > "$APPDIR_APPRUN" <<EOF
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$HERE/usr/bin/$APP_NAME" "\$@"
EOF
chmod +x "$APPDIR_APPRUN"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=WildCam
Exec=$APP_NAME
Icon=$APP_NAME
Categories=AudioVideo;Video;Viewer;
Terminal=false
EOF

export QT_QPA_PLATFORM=offscreen
export ICON_PATH
"$PY" - <<PY
import os
import sys
from PyQt6.QtGui import QGuiApplication, QIcon

icon_path = os.environ["ICON_PATH"]
app = QGuiApplication([])
icon = QIcon(os.path.join("assets", "icons", "camera.svg"))
pixmap = icon.pixmap(256, 256)
if pixmap.isNull():
    raise SystemExit("Failed to render icon from assets/icons/camera.svg")
if not pixmap.save(icon_path, "PNG"):
    raise SystemExit(f"Failed to save icon to {icon_path}")
print(f"ICON: {icon_path}")
PY

if [[ ! -f "$APPIMAGE_TOOL" ]]; then
  curl -fsSL \
    -o "$APPIMAGE_TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$APPIMAGE_TOOL"
fi

APPIMAGE_FINAL="$DIST_DIR/${APP_NAME}_${PLATFORM}_${ARTIFACT_SUFFIX}.AppImage"
cp "$DESKTOP_FILE" "$APPDIR_PATH/${APP_NAME}.desktop"
cp "$ICON_PATH" "$APPDIR_PATH/${APP_NAME}.png"

APPIMAGE_EXTRACT_AND_RUN=1 \
ARCH=x86_64 \
VERSION="$APP_VERSION" \
"$APPIMAGE_TOOL" \
  "$APPDIR_PATH" \
  "$APPIMAGE_FINAL"

if [[ ! -f "$APPIMAGE_FINAL" ]]; then
  echo "Build failed: AppImage not found at $APPIMAGE_FINAL" >&2
  exit 1
fi

ZIP_PATH="$DIST_DIR/${APP_NAME}_${PLATFORM}_${ARTIFACT_SUFFIX}.zip"

export BUNDLE_PATH
export ZIP_PATH
export APPIMAGE_FINAL

"$PY" - <<PY
import os
import zipfile

bundle_path = os.environ.get("BUNDLE_PATH")
zip_path = os.environ.get("ZIP_PATH")

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(bundle_path):
        for file_name in files:
            full_path = os.path.join(root, file_name)
            arcname = os.path.relpath(full_path, os.path.dirname(bundle_path))
            z.write(full_path, arcname=arcname)

print(f"BUNDLE: {bundle_path}")
print(f"ZIP: {zip_path}")
print(f"APPIMAGE: {os.environ.get('APPIMAGE_FINAL')}")
PY
