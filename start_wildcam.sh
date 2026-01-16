#!/bin/bash
# WildCam Start-Script mit automatischem Neolink-Setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎥 WildCam Startup"
echo "=================================="

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

# Generiere Neolink Config wenn Battery-Kameras vorhanden
echo ""
echo "🔋 Prüfe auf Battery-Kameras (Port 9000)..."
python3 neolink_manager.py

# Starte Neolink wenn neolink.toml existiert
if [ -f "neolink.toml" ]; then
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
    echo "⏳ Warte auf Neolink..."
    sleep 3
    
    # Prüfe ob Container läuft
    if docker ps | grep -q wildcam-neolink; then
        echo "✅ Neolink läuft (localhost:8554)"
    else
        echo "⚠️  Neolink Container nicht gestartet"
        echo "   Logs: docker logs wildcam-neolink"
    fi
else
    echo "ℹ️  Keine Battery-Kameras - Neolink nicht benötigt"
fi

# Starte WildCam
echo ""
echo "=================================="
echo "🚀 Starte WildCam..."
echo ""

# Prüfe ob venv existiert
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Starte Anwendung
python3 main.py "$@"
