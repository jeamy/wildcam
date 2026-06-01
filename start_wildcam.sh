#!/bin/bash
# WildCam Start-Script mit automatischem ReolinkProxy-Setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎥 WildCam Startup"
echo "=================================="

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python3"
fi

# Aktiviere/erstelle venv und stelle sicher, dass Requirements installiert sind.
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "🐍 .venv nicht gefunden - erstelle virtuelle Umgebung..."
    "$PYTHON_BIN" -m venv .venv
    source .venv/bin/activate
fi

echo "📦 Prüfe Python-Pakete..."
python3 -m pip install -r requirements.txt

# Prüfe ob camera_config.json existiert
if [ ! -f "camera_config.json" ]; then
    echo "⚠️  camera_config.json nicht gefunden!"
    echo "   Erstelle aus Example..."
    if [ -f "camera_config.json.example" ]; then
        cp camera_config.json.example camera_config.json
        echo "✅ camera_config.json erstellt"
    else
        echo "❌ Fehler: Keine Config-Vorlage gefunden!"
        exit 1
    fi
fi

# Generiere ReolinkProxy Config wenn Battery-Kameras vorhanden
echo ""
echo "🔋 Prüfe auf Battery-Kameras (Port 9000)..."
python3 reolinkproxy_manager.py --auto-update

# Starte ReolinkProxy wenn reolinkproxy.env existiert
if [ -f "reolinkproxy.env" ]; then
    echo ""
    
    # Prüfe ob Docker läuft
    if ! docker info >/dev/null 2>&1; then
        echo "❌ Docker ist nicht erreichbar!"
        echo "   Bitte Docker starten oder manuell installieren."
        exit 1
    fi
    
    # Starte/Aktualisiere Container
    docker compose up -d
    
    # Warte kurz für Container-Start
    echo "⏳ Warte auf ReolinkProxy..."
    sleep 3
    
    # Prüfe ob Container läuft
    if docker ps | grep -q wildcam-reolinkproxy; then
        echo "✅ ReolinkProxy läuft (localhost:8554)"
    else
        echo "⚠️  ReolinkProxy Container nicht gestartet"
        echo "   Logs: docker logs wildcam-reolinkproxy"
    fi
else
    echo "ℹ️  Keine Battery-Kameras - ReolinkProxy nicht benötigt"
fi

# Starte WildCam
echo ""
echo "=================================="
echo "🚀 Starte WildCam..."
echo ""

# Starte Anwendung
python3 main.py "$@"
