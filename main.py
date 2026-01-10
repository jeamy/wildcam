import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QPushButton, QLabel, 
                             QLineEdit, QSpinBox, QCheckBox, QFileDialog,
                             QMessageBox, QComboBox, QGroupBox, QScrollArea,
                             QProgressBar, QDialog, QDialogButtonBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSizePolicy, QSplitter,
                             QTabWidget)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QMimeData, QSize
from PyQt6.QtGui import QImage, QPixmap, QDrag, QIcon
from datetime import datetime
import json
import os
import socket
import requests
from requests.auth import HTTPDigestAuth
import ipaddress
import threading
from urllib.parse import urlparse
import struct
import time

try:
    import sip  # type: ignore
except Exception:  # pragma: no cover
    sip = None


CURRENT_LANG = "de"


def resource_path(relative_path: str) -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def load_svg_icon(name: str) -> QIcon:
    return QIcon(resource_path(os.path.join("assets", "icons", name)))


TRANSLATIONS = {
    "de": {
        "app.title": "Reolink Multi-Camera Viewer",
        "tab.cameras": "Kameras",
        "tab.config": "Konfiguration",
        "group.camera_config": "Kamera-Konfiguration",
        "label.rtsp_url": "RTSP URL:",
        "label.name": "Name:",
        "placeholder.rtsp_url": "rtsp://admin:password@192.168.1.100:554/h264Preview_01_main",
        "placeholder.name.short": "z.B. Eingang",
        "btn.add": "Hinzufügen",
        "btn.discover": "Auto-Suche",
        "btn.clear_all": "Alle entfernen",
        "btn.path": "Speicherort",
        "btn.start_all": "Alle Streams starten",
        "btn.stop_all": "Alle Streams stoppen",
        "btn.record_all": "Alle aufnehmen",
        "btn.record_all_stop": "Alle stoppen",
        "label.camera_count": "Kameras: {total} | Aktiv: {active}",
        "big.select_camera": "Kamera auswählen…",
        "status.ready": "Bereit - CPU-optimiert für parallele Streams",
        "status.auto_added": "{count} Kameras automatisch hinzugefügt",
        "status.camera_added": "{name} hinzugefügt",
        "status.camera_updated": "Kamera {name} aktualisiert",
        "status.stream_started": "Stream für {name} gestartet",
        "status.streams_starting": "{count} Streams werden parallel gestartet...",
        "status.streams_stopped": "Alle Streams gestoppt",
        "status.camera_removed": "Kamera {id} entfernt",
        "status.cameras_removed": "Alle Kameras entfernt",
        "dialog.title.info": "Info",
        "dialog.title.error": "Fehler",
        "dialog.title.confirm": "Bestätigung",
        "dialog.msg.no_cameras": "Keine Kameras konfiguriert!",
        "dialog.confirm.remove_all": "Alle Kameras entfernen?",
        "dialog.confirm.remove_one": "Kamera '{name}' wirklich entfernen?",
        "dialog.path.choose": "Speicherort wählen",
        "label.cameras_per_row": "Kameras pro Reihe:",
        "status.path": "Speicherort: {path}",
        "status.no_image": "Kein Bild verfügbar",
        "status.snapshot_saved": "Snapshot gespeichert: {name}",
        "status.snapshot_error": "Snapshot Fehler: {error}",
        "status.recording": "Aufnahme: {name}",
        "status.recording_stopped": "Aufnahme gestoppt: {name}",
        "status.recordings_started": "{count} Aufnahmen gestartet",
        "status.recordings_stopped": "{count} Aufnahmen gestoppt",
        "camera.preview.click_to_start": "Stream starten klicken",
        "camera.preview.waiting": "Warte auf Stream...",
        "camera.preview.retrying": "Versuche erneut...",
        "camera.status.offline": "Offline",
        "camera.status.stopped": "Gestoppt",
        "camera.status.connected": "Verbunden",
        "camera.status.sleep": "Sleep/Offline",
        "camera.default_name.id": "Kamera {id}",
        "camera.default_name.ip": "Kamera {ip}",
        "camera.meta.unknown": "Unbekannt",
        "camera.meta.rtsp_camera": "RTSP-Kamera",
        "camera.error.stream_unreachable": "Stream nicht erreichbar",
        "camera.error.stream_interrupted": "Stream unterbrochen",
        "camera.tooltip.record": "Aufzeichnung starten/stoppen",
        "camera.tooltip.stream": "Stream starten/stoppen",
        "camera.tooltip.snapshot": "Einzelbild speichern",
        "camera.tooltip.edit": "Kamera bearbeiten",
        "camera.tooltip.remove": "Kamera entfernen",
        "dialog.edit.title": "Kamera bearbeiten",
        "dialog.edit.name": "Name:",
        "dialog.edit.name_ph": "z.B. Eingang Haupttür",
        "dialog.edit.rtsp_url": "RTSP URL:",
        "dialog.edit.rtsp_ph": "rtsp://admin:password@192.168.1.100:554/h264Preview_01_main",
        "dialog.edit.help_group": "RTSP URL Format",
        "dialog.edit.help_text": "Standard Format: rtsp://username:password@ip:port/pfad\n\nReolink Beispiele:\n• Main Stream: rtsp://admin:pass@192.168.1.100:554/h264Preview_01_main\n• Sub Stream: rtsp://admin:pass@192.168.1.100:554/h264Preview_01_sub\n\nAndere Kameras:\n• ONVIF: rtsp://admin:pass@192.168.1.100:554/onvif1\n• Hikvision: rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/101",
        "dialog.edit.builder_group": "Schnell-Editor",
        "dialog.edit.ip": "IP:",
        "dialog.edit.ip_ph": "192.168.1.100",
        "dialog.edit.port": "Port:",
        "dialog.edit.username": "Username:",
        "dialog.edit.password": "Password:",
        "dialog.edit.path": "Pfad:",
        "dialog.edit.build_url": "→ URL Generieren",
        "dialog.edit.err_ip": "Bitte IP-Adresse eingeben!",
        "dialog.discovery.title": "Kamera-Suche im Netzwerk",
        "dialog.discovery.scan_config": "Scan-Konfiguration",
        "dialog.discovery.network": "Netzwerk:",
        "dialog.discovery.network_ph": "192.168.1.0/24",
        "dialog.discovery.username": "Benutzername:",
        "dialog.discovery.password": "Passwort:",
        "dialog.discovery.start": "🔍 Suche starten",
        "dialog.discovery.stop": "⏹ Stoppen",
        "dialog.discovery.ready": "Bereit zum Scannen",
        "dialog.discovery.found": "Gefundene Kameras",
        "dialog.discovery.col.select": "Auswählen",
        "dialog.discovery.col.ip": "IP-Adresse",
        "dialog.discovery.col.name": "Name",
        "dialog.discovery.col.model": "Modell",
        "dialog.discovery.col.manufacturer": "Hersteller",
        "dialog.discovery.col.ports": "Ports",
        "dialog.discovery.col.uid": "UID",
        "dialog.discovery.err_network": "Bitte Netzwerk-Bereich eingeben!",
        "dialog.discovery.scan_cancelled": "Scan abgebrochen - {count} Kameras gefunden",
        "dialog.discovery.scan_done": "Scan abgeschlossen - {count} Kameras gefunden",
        "label.uid": "UID (optional):",
        "placeholder.uid": "z.B. 9527000000000000",
        "scan.checking": "Prüfe {ip}...",
        "scan.error": "Fehler: {error}",
        "error.prefix": "Fehler: {error}",
        "label.language": "Sprache:",
        "language.de": "Deutsch",
        "language.en": "English",
    },
    "en": {
        "app.title": "Reolink Multi-Camera Viewer",
        "tab.cameras": "Cameras",
        "tab.config": "Settings",
        "group.camera_config": "Camera Configuration",
        "label.rtsp_url": "RTSP URL:",
        "label.name": "Name:",
        "placeholder.rtsp_url": "rtsp://admin:password@192.168.1.100:554/h264Preview_01_main",
        "placeholder.name.short": "e.g. Entrance",
        "btn.add": "➕ Add",
        "btn.discover": "🔍 Auto-Discover",
        "btn.clear_all": "Remove all",
        "btn.path": "📁 Storage",
        "btn.start_all": "▶ Start all streams",
        "btn.stop_all": "⏹ Stop all streams",
        "btn.record_all": "● Record all",
        "btn.record_all_stop": "■ Stop all",
        "label.camera_count": "Cameras: {total} | Active: {active}",
        "big.select_camera": "Select a camera…",
        "status.ready": "Ready - CPU-optimized for parallel streams",
        "status.auto_added": "{count} cameras added automatically",
        "status.camera_added": "{name} added",
        "status.camera_updated": "Camera {name} updated",
        "status.stream_started": "Stream started for {name}",
        "status.streams_starting": "Starting {count} streams in parallel...",
        "status.streams_stopped": "All streams stopped",
        "status.camera_removed": "Camera {id} removed",
        "status.cameras_removed": "All cameras removed",
        "dialog.title.info": "Info",
        "dialog.title.error": "Error",
        "dialog.title.confirm": "Confirm",
        "dialog.msg.no_cameras": "No cameras configured!",
        "dialog.confirm.remove_all": "Remove all cameras?",
        "dialog.confirm.remove_one": "Remove camera '{name}'?",
        "dialog.path.choose": "Choose storage folder",
        "label.cameras_per_row": "Cameras per row:",
        "status.path": "Storage: {path}",
        "status.no_image": "No image available",
        "status.snapshot_saved": "Snapshot saved: {name}",
        "status.snapshot_error": "Snapshot error: {error}",
        "status.recording": "Recording: {name}",
        "status.recording_stopped": "Recording stopped: {name}",
        "status.recordings_started": "{count} recordings started",
        "status.recordings_stopped": "{count} recordings stopped",
        "camera.preview.click_to_start": "Click start stream",
        "camera.preview.waiting": "Waiting for stream...",
        "camera.preview.retrying": "Retrying...",
        "camera.status.offline": "Offline",
        "camera.status.stopped": "Stopped",
        "camera.status.connected": "Connected",
        "camera.status.sleep": "Sleep/Offline",
        "camera.default_name.id": "Camera {id}",
        "camera.default_name.ip": "Camera {ip}",
        "camera.meta.unknown": "Unknown",
        "camera.meta.rtsp_camera": "RTSP camera",
        "camera.error.stream_unreachable": "Stream unreachable",
        "camera.error.stream_interrupted": "Stream interrupted",
        "camera.tooltip.record": "Start/stop recording",
        "camera.tooltip.stream": "Start/stop stream",
        "camera.tooltip.snapshot": "Save snapshot",
        "camera.tooltip.edit": "Edit camera",
        "camera.tooltip.remove": "Remove camera",
        "dialog.edit.title": "Edit camera",
        "dialog.edit.name": "Name:",
        "dialog.edit.name_ph": "e.g. Front door",
        "dialog.edit.rtsp_url": "RTSP URL:",
        "dialog.edit.rtsp_ph": "rtsp://admin:password@192.168.1.100:554/h264Preview_01_main",
        "dialog.edit.help_group": "RTSP URL format",
        "dialog.edit.help_text": "Standard format: rtsp://username:password@ip:port/path\n\nReolink examples:\n• Main stream: rtsp://admin:pass@192.168.1.100:554/h264Preview_01_main\n• Sub stream: rtsp://admin:pass@192.168.1.100:554/h264Preview_01_sub\n\nOther cameras:\n• ONVIF: rtsp://admin:pass@192.168.1.100:554/onvif1\n• Hikvision: rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/101",
        "dialog.edit.builder_group": "Quick editor",
        "dialog.edit.ip": "IP:",
        "dialog.edit.ip_ph": "192.168.1.100",
        "dialog.edit.port": "Port:",
        "dialog.edit.username": "Username:",
        "dialog.edit.password": "Password:",
        "dialog.edit.path": "Path:",
        "dialog.edit.build_url": "→ Build URL",
        "dialog.edit.err_ip": "Please enter an IP address!",
        "dialog.discovery.title": "Network camera discovery",
        "dialog.discovery.scan_config": "Scan configuration",
        "dialog.discovery.network": "Network:",
        "dialog.discovery.network_ph": "192.168.1.0/24",
        "dialog.discovery.username": "Username:",
        "dialog.discovery.password": "Password:",
        "dialog.discovery.start": "🔍 Start scan",
        "dialog.discovery.stop": "⏹ Stop",
        "dialog.discovery.ready": "Ready to scan",
        "dialog.discovery.found": "Found cameras",
        "dialog.discovery.col.select": "Select",
        "dialog.discovery.col.ip": "IP address",
        "dialog.discovery.col.name": "Name",
        "dialog.discovery.col.model": "Model",
        "dialog.discovery.col.manufacturer": "Vendor",
        "dialog.discovery.col.ports": "Ports",
        "dialog.discovery.col.uid": "UID",
        "dialog.discovery.err_network": "Please enter a network range!",
        "dialog.discovery.scan_cancelled": "Scan cancelled - {count} cameras found",
        "dialog.discovery.scan_done": "Scan finished - {count} cameras found",
        "label.uid": "UID (optional):", # Added by instruction
        "placeholder.uid": "e.g. 9527000000000000", # Added by instruction
        "scan.checking": "Checking {ip}...",
        "scan.error": "Error: {error}",
        "error.prefix": "Error: {error}",
        "label.language": "Language:",
        "language.de": "Deutsch",
        "language.en": "English",
    },
}


def set_language(lang: str):
    global CURRENT_LANG
    if lang in TRANSLATIONS:
        CURRENT_LANG = lang


def tr(key: str, **kwargs) -> str:
    lang_map = TRANSLATIONS.get(CURRENT_LANG) or TRANSLATIONS["de"]
    s = lang_map.get(key) or TRANSLATIONS["de"].get(key) or key
    try:
        return s.format(**kwargs)
    except Exception:
        return s


def _parse_rtsp_url(rtsp_url: str):
    """Best-effort RTSP URL parsing (host/port/user/pass)."""
    try:
        u = urlparse(rtsp_url)
        host = u.hostname
        port = u.port or 554
        user = u.username
        password = u.password
        return host, port, user, password
    except Exception:
        return None, 554, None, None


def _tcp_probe(host: str, port: int, timeout: float = 0.7) -> tuple[bool, str]:
    """Fast TCP reachability check.

    Returns (ok, reason) where reason is one of: ok, timeout, refused, unreachable, error.
    """
    if not host:
        return False, "error"
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        return True, "ok"
    except ConnectionRefusedError:
        return False, "refused"
    except TimeoutError:
        return False, "timeout"
    except OSError as e:
        # e.g. No route to host, network unreachable, etc.
        if getattr(e, "errno", None) in (101, 113):
            return False, "unreachable"
        return False, "error"


def _ws_discovery(timeout: float = 2.0) -> list[str]:
    """ONVIF/WS-Discovery (UDP 3702)."""
    msg = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Envelope xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns="http://www.w3.org/2003/05/soap-envelope">'
        '<Header><MessageID xmlns="http://schemas.xmlsoap.org/ws/2004/08/addressing">uuid:8253()</MessageID>'
        '<To xmlns="http://schemas.xmlsoap.org/ws/2004/08/addressing">urn:schemas-xmlsoap-org:ws:2004:08:discovery</To>'
        '<Action xmlns="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/discovery/Probe</Action></Header>'
        '<Body><Probe xmlns="http://schemas.xmlsoap.org/ws/2004/08/discovery"><Types>tds:Device</Types></Probe></Body></Envelope>'
    )
    ips = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(msg.encode(), ("239.255.255.250", 3702))
        
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                ips.add(addr[0])
            except socket.timeout:
                break
        sock.close()
    except: pass
    return list(ips)


def _ssdp_discovery(timeout: float = 2.0) -> list[str]:
    """UPnP/SSDP Discovery (UDP 1900)."""
    msg = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 2\r\n'
        'ST: ssdp:all\r\n'
        '\r\n'
    )
    ips = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.sendto(msg.encode(), ("239.255.255.250", 1900))
        
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                ips.add(addr[0])
            except socket.timeout:
                break
        sock.close()
    except: pass
    return list(ips)


def _udp_reolink_probe(ip: str, timeout: float = 2.0) -> list | dict | None:
    """Sendet ein Reolink UDP Discovery Paket an eine spezifische oder Broadcast IP."""
    ports = [9000, 10000, 2000]
    
    # Discovery JSON Payloads (GetDevInfo und Search)
    payloads = [
        [{"cmd": "GetDevInfo", "action": 0, "param": {}}],
        {"cmd": "GetDevInfo", "action": 0, "param": {}},
        [{"cmd": "Search", "action": 0, "param": {}}],
        {"cmd": "Search", "action": 0, "param": {}}
    ]
    
    results = []
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    if ip == "255.255.255.255":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    for port in ports:
        for cmd_data in payloads:
            data = json.dumps(cmd_data).encode('utf-8')
            for endian in ['<', '>']:
                header = struct.pack(endian + "2sHHHII", b"BC", 0, 1, 0, len(data), 0)
                payload = header + data
                try:
                    # Weck-Schuss
                    sock.sendto(b"\x00" * 32, (ip, port))
                    sock.sendto(payload, (ip, port))
                    
                    while True:
                        try:
                            resp_data, addr = sock.recvfrom(4096)
                        except socket.timeout:
                            break
                            
                        if len(resp_data) >= 16:
                            idx = -1
                            for i in range(len(resp_data) - 1):
                                if resp_data[i:i+2].lower() == b"bc":
                                    for j in range(i+2, min(i+48, len(resp_data))):
                                        if resp_data[j] in (ord('['), ord('{')):
                                            idx = j
                                            break
                                    if idx != -1: break
                            
                            if idx != -1:
                                content = resp_data[idx:].decode('utf-8', 'ignore')
                                if content.startswith('['): end = content.rfind(']')
                                else: end = content.rfind('}')
                                
                                if end != -1:
                                    try:
                                        res = json.loads(content[:end+1])
                                        info = None
                                        # Wir suchen nach DevInfo oder Search-Response
                                        val = res[0].get('value', {}) if isinstance(res, list) else res.get('value', {})
                                        info = val.get('DevInfo') or val.get('SearchResult') or val
                                        
                                        if info and (info.get('name') or info.get('serial') or info.get('mac')):
                                            info['remote_ip'] = addr[0]
                                            if ip != "255.255.255.255":
                                                sock.close()
                                                return info
                                            if info.get('remote_ip') not in [r.get('remote_ip') for r in results]:
                                                results.append(info)
                                    except: pass
                        if ip != "255.255.255.255": break
                except: break
            if ip != "255.255.255.255" and results: break
    
    sock.close()
    return results if ip == "255.255.255.255" else (results[0] if results else None)


def _udp_reolink_wake(ip: str, uid: str = ""):
    """Sendet einen intensiven Weck-Burst an eine Reolink Kamera."""
    if not ip: return
    try:
        # Falls UID vorhanden, bauen wir ein echtes Abfrage-Paket
        payload = b""
        if uid:
            msg = [{"cmd": "GetDevInfo", "action": 0, "param": {}}]
            data = json.dumps(msg).encode('utf-8')
            header = struct.pack("<2sHHHII", b"BC", 0, 1, 0, len(data), 0)
            payload = header + data

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Wir pingen alle relevanten Ports mehrfach
        for port in [9000, 10000, 8000]:
            for _ in range(5):
                # Null-Bytes zum "Aufwecken" des WLAN/PIR
                sock.sendto(b"\x00" * 64, (ip, port))
                if payload:
                    # Gezielte Abfrage mit UID (Baichuan)
                    sock.sendto(payload, (ip, port))
                else:
                    # Generischer Header
                    h = struct.pack("<2sHHHII", b"BC", 0, 1, 0, 0, 0)
                    sock.sendto(h, (ip, port))
                time.sleep(0.02)
        sock.close()
    except: pass


class CameraListContainer(QWidget):
    order_changed = pyqtSignal(object)  # list[int]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setContentsMargins(0, 0, 0, 0)

    @property
    def layout_ref(self) -> QVBoxLayout:
        return self._layout

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-wildcam-camera-id"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-wildcam-camera-id"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-wildcam-camera-id"):
            super().dropEvent(event)
            return

        data = bytes(event.mimeData().data("application/x-wildcam-camera-id")).decode("utf-8", "ignore")
        try:
            dragged_id = int(data)
        except Exception:
            event.ignore()
            return

        ordered_ids = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and hasattr(w, "camera_id"):
                ordered_ids.append(int(getattr(w, "camera_id")))

        if dragged_id not in ordered_ids:
            event.ignore()
            return

        drop_y = event.position().y() if hasattr(event, "position") else event.pos().y()
        insert_index = len(ordered_ids)
        for idx in range(self._layout.count()):
            item = self._layout.itemAt(idx)
            w = item.widget() if item else None
            if w is None:
                continue
            mid = w.y() + (w.height() / 2)
            if drop_y < mid:
                insert_index = idx
                break

        ordered_ids.remove(dragged_id)
        if insert_index > len(ordered_ids):
            insert_index = len(ordered_ids)
        ordered_ids.insert(insert_index, dragged_id)

        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.order_changed.emit(ordered_ids))


class CameraDiscoveryThread(QThread):
    """Thread für automatische Kamera-Suche im Netzwerk"""
    camera_found = pyqtSignal(dict)  # {ip, name, model, ports, uid}
    progress_update = pyqtSignal(int, str)
    scan_complete = pyqtSignal(int)
    
    def __init__(self, network_range, ports=None, username="admin", password=""):
        super().__init__()
        self.network_range = network_range
        self.ports = ports or [554, 8000, 80, 8554]  # Typische Reolink/RTSP Ports
        self.username = username
        self.password = password
        self.running = False
        self.found_cameras = []
        
    def run(self):
        """Netzwerk nach Kameras durchsuchen"""
        self.running = True
        self.found_cameras = []
        
        try:
            # 1. Multi-Discovery (UDP Broadcasts)
            self.progress_update.emit(5, "Starte Netzwerk-Suche (UDP/WS/SSDP)...")
            
            discovery_ips = set()
            
            # Reolink BC Discovery
            broadcast_results = _udp_reolink_probe("255.255.255.255", timeout=1.5)
            if broadcast_results and isinstance(broadcast_results, list):
                for info in broadcast_results:
                    discovery_ips.add(info['remote_ip'])
                    camera_info = {
                        'ip': info.get('remote_ip', ''),
                        'ports': [554, 8000, 9000],
                        'name': info.get('name', 'Reolink Camera'),
                        'model': info.get('model', 'Unknown'),
                        'manufacturer': "Reolink",
                        'uid': info.get('devNo', '') or info.get('serial', '')
                    }
                    if camera_info['ip'] not in [c['ip'] for c in self.found_cameras]:
                        self.found_cameras.append(camera_info)
                        self.camera_found.emit(camera_info)

            # ONVIF Discovery
            onvif_ips = _ws_discovery(timeout=1.0)
            discovery_ips.update(onvif_ips)
            
            # SSDP Discovery
            ssdp_ips = _ssdp_discovery(timeout=1.0)
            discovery_ips.update(ssdp_ips)

            # Wenn wir Kameras über Broadcast gefunden haben, prüfen wir diese zuerst
            for dip in discovery_ips:
                if dip not in [c['ip'] for c in self.found_cameras]:
                    # Hole Details für diese IP
                    c_info = self._get_camera_info(dip, [80, 8000, 554, 9000])
                    if c_info:
                        self.found_cameras.append(c_info)
                        self.camera_found.emit(c_info)

            network = ipaddress.ip_network(self.network_range, strict=False)
            total_hosts = network.num_addresses - 2  # Ohne Netzwerk- und Broadcast-Adresse
            checked = 0
            
            for ip in network.hosts():
                if not self.running:
                    break
                
                ip_str = str(ip)
                checked += 1
                self.progress_update.emit(int((checked / total_hosts) * 100), tr("scan.checking", ip=ip_str))
                
                # Schneller Port-Scan
                open_ports = self._scan_ports(ip_str)
                
                if open_ports:
                    # Versuche Kamera-Info abzurufen
                    camera_info = self._get_camera_info(ip_str, open_ports)
                    if camera_info:
                        self.found_cameras.append(camera_info)
                        self.camera_found.emit(camera_info)
            
            self.scan_complete.emit(len(self.found_cameras))
            
        except Exception as e:
            self.progress_update.emit(100, tr("scan.error", error=str(e)))
    
    def _scan_ports(self, ip, timeout=0.5):
        """Schneller Port-Scan für bestimmte IP"""
        open_ports = []
        
        for port in self.ports:
            if not self.running:
                break
            
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                
                if result == 0:
                    open_ports.append(port)
            except:
                pass
        
        return open_ports
    
    def _get_camera_info(self, ip, ports):
        """Versuche Kamera-Informationen abzurufen"""
        camera_info = {
            'ip': ip,
            'ports': ports,
            'name': tr("camera.default_name.ip", ip=ip),
            'model': tr("camera.meta.unknown"),
            'manufacturer': tr("camera.meta.unknown"),
            'uid': '',
        }
        
        # 1. Versuche UDP Reolink Probe (Port 9000) - am besten für UID & Standby
        udp_info = _udp_reolink_probe(ip)
        if udp_info:
            camera_info['name'] = udp_info.get('name', camera_info['name'])
            camera_info['model'] = udp_info.get('model', camera_info['model'])
            camera_info['manufacturer'] = "Reolink"
            camera_info['uid'] = udp_info.get('devNo', '') or udp_info.get('serial', '')
            return camera_info

        # 2. Versuche ONVIF/HTTP Zugriff
        if 80 in ports or 8000 in ports:
            for port in [80, 8000]:
                if port in ports:
                    try:
                        # Reolink API Versuch
                        url = f"http://{ip}:{port}/api.cgi?cmd=GetDevInfo"
                        response = requests.get(
                            url, 
                            auth=HTTPDigestAuth(self.username, self.password),
                            timeout=2
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if isinstance(data, list) and len(data) > 0:
                                info = data[0].get('value', {}).get('DevInfo', {})
                                camera_info['name'] = info.get('name', camera_info['name'])
                                camera_info['model'] = info.get('model', camera_info['model'])
                                camera_info['manufacturer'] = "Reolink"
                                camera_info['uid'] = info.get('devNo', '') or info.get('serial', '')
                                return camera_info
                    except:
                        pass
        
        # Wenn HTTP nicht funktioniert, aber RTSP Port offen ist
        if 554 in ports or 8554 in ports:
            camera_info['manufacturer'] = tr("camera.meta.rtsp_camera")
            return camera_info
        
        return None
    
    def stop(self):
        """Scan stoppen"""
        self.running = False


class CameraEditDialog(QDialog):
    """Dialog zum Bearbeiten einer Kamera"""
    def __init__(self, camera_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.edit.title"))
        self.setModal(True)
        self.resize(600, 300)
        
        self.camera_data = camera_data.copy()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel(tr("dialog.edit.name")))
        self.name_input = QLineEdit()
        self.name_input.setText(self.camera_data.get('name', ''))
        self.name_input.setPlaceholderText(tr("dialog.edit.name_ph"))
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # RTSP URL
        url_layout = QVBoxLayout()
        url_layout.addWidget(QLabel(tr("dialog.edit.rtsp_url")))
        self.url_input = QLineEdit()
        self.url_input.setText(self.camera_data.get('url', ''))
        self.url_input.setPlaceholderText(tr("dialog.edit.rtsp_ph"))
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)
        
        # UID
        uid_layout = QHBoxLayout()
        uid_layout.addWidget(QLabel(tr("label.uid")))
        self.uid_input = QLineEdit()
        self.uid_input.setText(self.camera_data.get('uid', ''))
        self.uid_input.setPlaceholderText(tr("placeholder.uid"))
        uid_layout.addWidget(self.uid_input)
        layout.addLayout(uid_layout)
        
        # Hilfe-Text
        help_group = QGroupBox(tr("dialog.edit.help_group"))
        help_layout = QVBoxLayout()
        help_text = QLabel(tr("dialog.edit.help_text"))
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #aaa; font-size: 10px;")
        help_layout.addWidget(help_text)
        help_group.setLayout(help_layout)
        layout.addWidget(help_group)
        
        # URL Builder Shortcut
        builder_group = QGroupBox(tr("dialog.edit.builder_group"))
        builder_layout = QGridLayout()
        
        builder_layout.addWidget(QLabel(tr("dialog.edit.ip")), 0, 0)
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText(tr("dialog.edit.ip_ph"))
        builder_layout.addWidget(self.ip_input, 0, 1)
        
        builder_layout.addWidget(QLabel(tr("dialog.edit.port")), 0, 2)
        self.port_input = QLineEdit()
        self.port_input.setText("554")
        self.port_input.setMaximumWidth(60)
        builder_layout.addWidget(self.port_input, 0, 3)
        
        builder_layout.addWidget(QLabel(tr("dialog.edit.username")), 1, 0)
        self.username_input = QLineEdit()
        self.username_input.setText("admin")
        builder_layout.addWidget(self.username_input, 1, 1)
        
        builder_layout.addWidget(QLabel(tr("dialog.edit.password")), 1, 2)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        builder_layout.addWidget(self.password_input, 1, 3)
        
        builder_layout.addWidget(QLabel(tr("dialog.edit.path")), 2, 0)
        self.path_combo = QComboBox()
        self.path_combo.addItems([
            "h264Preview_01_main",
            "h264Preview_01_sub",
            "onvif1",
            "Streaming/Channels/101",
            "stream1",
            "live"
        ])
        self.path_combo.setEditable(True)
        builder_layout.addWidget(self.path_combo, 2, 1, 1, 3)
        
        build_btn = QPushButton(tr("dialog.edit.build_url"))
        build_btn.clicked.connect(self.build_url)
        build_btn.setStyleSheet("background-color: #1976d2; color: white;")
        builder_layout.addWidget(build_btn, 3, 0, 1, 4)
        
        builder_group.setLayout(builder_layout)
        layout.addWidget(builder_group)
        
        # Aktuellen URL parsen
        self.parse_current_url()
        
        # Dialog Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    def parse_current_url(self):
        """Aktuellen URL in Felder zerlegen"""
        url = self.camera_data.get('url', '')
        
        try:
            # Format: rtsp://username:password@ip:port/path
            if url.startswith('rtsp://'):
                url = url[7:]  # "rtsp://" entfernen
                
                if '@' in url:
                    auth, rest = url.split('@', 1)
                    if ':' in auth:
                        username, password = auth.split(':', 1)
                        self.username_input.setText(username)
                        self.password_input.setText(password)
                    
                    if ':' in rest:
                        ip, port_path = rest.split(':', 1)
                        self.ip_input.setText(ip)
                        
                        if '/' in port_path:
                            port, path = port_path.split('/', 1)
                            self.port_input.setText(port)
                            self.path_combo.setCurrentText(path)
        except:
            pass
    
    def build_url(self):
        """URL aus Einzelteilen zusammenbauen"""
        ip = self.ip_input.text().strip()
        port = self.port_input.text().strip() or "554"
        username = self.username_input.text().strip() or "admin"
        password = self.password_input.text().strip()
        path = self.path_combo.currentText().strip()
        
        if not ip:
            QMessageBox.warning(self, tr("dialog.title.error"), tr("dialog.edit.err_ip"))
            return
        
        url = f"rtsp://{username}:{password}@{ip}:{port}/{path}"
        self.url_input.setText(url)
    
    def get_camera_data(self):
        """Geänderte Daten zurückgeben"""
        self.camera_data['name'] = self.name_input.text().strip()
        self.camera_data['url'] = self.url_input.text().strip()
        self.camera_data['uid'] = self.uid_input.text().strip()
        return self.camera_data


class CameraDiscoveryDialog(QDialog):
    """Dialog für Kamera-Suche"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.discovery.title"))
        self.setModal(True)
        self.resize(700, 500)
        
        self.found_cameras = []
        self.discovery_thread = None
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Netzwerk-Konfiguration
        config_group = QGroupBox(tr("dialog.discovery.scan_config"))
        config_layout = QVBoxLayout()
        
        # Netzwerk-Bereich
        network_layout = QHBoxLayout()
        network_layout.addWidget(QLabel(tr("dialog.discovery.network")))
        self.network_input = QLineEdit()
        self.network_input.setPlaceholderText(tr("dialog.discovery.network_ph"))
        self.network_input.setText(self._get_local_network())
        network_layout.addWidget(self.network_input)
        config_layout.addLayout(network_layout)
        
        # Zugangsdaten
        auth_layout = QHBoxLayout()
        auth_layout.addWidget(QLabel(tr("dialog.discovery.username")))
        self.username_input = QLineEdit()
        self.username_input.setText("admin")
        auth_layout.addWidget(self.username_input)
        
        auth_layout.addWidget(QLabel(tr("dialog.discovery.password")))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        auth_layout.addWidget(self.password_input)
        config_layout.addLayout(auth_layout)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Scan-Kontrolle
        scan_layout = QHBoxLayout()
        self.scan_btn = QPushButton(tr("dialog.discovery.start"))
        self.scan_btn.clicked.connect(self.start_scan)
        scan_layout.addWidget(self.scan_btn)
        
        self.stop_btn = QPushButton(tr("dialog.discovery.stop"))
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        scan_layout.addWidget(self.stop_btn)
        
        scan_layout.addStretch()
        layout.addLayout(scan_layout)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel(tr("dialog.discovery.ready"))
        layout.addWidget(self.status_label)
        
        # Gefundene Kameras Tabelle
        found_group = QGroupBox(tr("dialog.discovery.found"))
        found_layout = QVBoxLayout()
        
        self.camera_table = QTableWidget()
        self.camera_table.setColumnCount(7)
        self.camera_table.setHorizontalHeaderLabels([
            tr("dialog.discovery.col.select"),
            tr("dialog.discovery.col.ip"),
            tr("dialog.discovery.col.name"),
            tr("dialog.discovery.col.model"),
            tr("dialog.discovery.col.manufacturer"),
            tr("dialog.discovery.col.ports"),
            tr("dialog.discovery.col.uid"),
        ])
        self.camera_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.camera_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        found_layout.addWidget(self.camera_table)
        found_group.setLayout(found_layout)
        layout.addWidget(found_group)
        
        # Dialog Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    def _get_local_network(self):
        """Lokales Netzwerk ermitteln"""
        try:
            # Lokale IP ermitteln
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Netzwerk-Bereich ableiten (Class C)
            ip_parts = local_ip.split('.')
            network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
            return network
        except:
            return "192.168.1.0/24"
    
    def start_scan(self):
        """Scan starten"""
        network = self.network_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not network:
            QMessageBox.warning(self, tr("dialog.title.error"), tr("dialog.discovery.err_network"))
            return
        
        # UI anpassen
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.camera_table.setRowCount(0)
        self.found_cameras.clear()
        self.progress_bar.setValue(0)
        
        # Discovery Thread starten
        self.discovery_thread = CameraDiscoveryThread(network, username=username, password=password)
        self.discovery_thread.camera_found.connect(self.on_camera_found)
        self.discovery_thread.progress_update.connect(self.on_progress_update)
        self.discovery_thread.scan_complete.connect(self.on_scan_complete)
        self.discovery_thread.start()
    
    def stop_scan(self):
        """Scan stoppen"""
        if self.discovery_thread:
            self.discovery_thread.stop()
            self.discovery_thread.wait()
        
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(tr("dialog.discovery.scan_cancelled", count=len(self.found_cameras)))
    
    def on_camera_found(self, camera_info):
        """Kamera zur Tabelle hinzufügen"""
        self.found_cameras.append(camera_info)
        
        row = self.camera_table.rowCount()
        self.camera_table.insertRow(row)
        
        # Checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(True)
        checkbox_widget = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.addWidget(checkbox)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_table.setCellWidget(row, 0, checkbox_widget)
        
        # Daten
        self.camera_table.setItem(row, 1, QTableWidgetItem(camera_info['ip']))
        self.camera_table.setItem(row, 2, QTableWidgetItem(camera_info['name']))
        self.camera_table.setItem(row, 3, QTableWidgetItem(camera_info['model']))
        self.camera_table.setItem(row, 4, QTableWidgetItem(camera_info['manufacturer']))
        self.camera_table.setItem(row, 5, QTableWidgetItem(', '.join(map(str, camera_info['ports']))))
        self.camera_table.setItem(row, 6, QTableWidgetItem(camera_info.get('uid', '')))
    
    def on_progress_update(self, progress, message):
        """Progress aktualisieren"""
        self.progress_bar.setValue(progress)
        self.status_label.setText(message)
    
    def on_scan_complete(self, count):
        """Scan abgeschlossen"""
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText(tr("dialog.discovery.scan_done", count=count))
    
    def get_selected_cameras(self):
        """Ausgewählte Kameras zurückgeben"""
        selected = []
        
        for row in range(self.camera_table.rowCount()):
            checkbox_widget = self.camera_table.cellWidget(row, 0)
            checkbox = checkbox_widget.findChild(QCheckBox)
            
            if checkbox and checkbox.isChecked():
                camera_info = self.found_cameras[row]
                selected.append(camera_info)
        
        return selected


class CameraThread(QThread):
    """Thread für einzelne Kamera mit OpenCV - optimiert für parallele Streams"""
    frame_ready = pyqtSignal(np.ndarray, int)
    connection_status = pyqtSignal(bool, int, str)
    
    def __init__(self, camera_id, rtsp_url, uid=""):
        super().__init__()
        self.camera_id = camera_id
        # Versuche URLs zu normalisieren (Reolink ist oft empfindlich bei h264 vs h265)
        self.rtsp_url = rtsp_url
        self.uid = uid
        self.running = False
        self.recording = False
        self.video_writer = None
        self._writer_lock = threading.Lock()
        self.cap = None
        self.reconnect_delay = 5  # Mehr Zeit für Akku-Kameras
        self._host, self._port, self._user, self._password = _parse_rtsp_url(rtsp_url)
        
        # Alternative Pfade (Reolink Fallbacks)
        self._alt_paths = [
            "h264Preview_01_main",
            "h265Preview_01_main",
            "Preview_01_main",
            "h264Preview_01_sub",
            "Preview_01_sub"
        ]
        
    def run(self):
        """Hauptschleife mit automatischem Retry"""
        self.running = True
        
        while self.running:
            try:
                self._connect_and_stream()
            except Exception as e:
                self.connection_status.emit(False, self.camera_id, tr("error.prefix", error=str(e)))
                if self.running:
                    self.sleep(self.reconnect_delay)  # Warte vor erneutem Versuch
        
        self._cleanup()
    
    def _connect_and_stream(self):
        """Verbindung herstellen und streamen"""
        # Best-effort wake attempt for sleeping/battery cameras
        if self._host:
            # Intensiv-Weckphase (für Akku-Kameras wie Argus PT Ultra)
            # Wir wiederholen das Wecken und prüfen die Erreichbarkeit über mind. 10 Sek.
            self.connection_status.emit(False, self.camera_id, tr("camera.preview.waiting"))
            
            wake_ok = False
            for attempt in range(10): # 10 Versuche alle ~1s = ca. 10s total
                if not self.running: break
                
                # 1. UDP Wake Burst
                _udp_reolink_wake(self._host, self.uid)
                
                # 2. Optionaler HTTP Ping
                try: requests.get(f"http://{self._host}:8000/api.cgi?cmd=GetDevInfo", timeout=0.2)
                except: pass
                
                # 3. RTSP Erreichbarkeit prüfen (Port 554)
                for _ in range(3):
                    if not self.running: break
                    ok, _ = _tcp_probe(self._host, int(self._port or 554), timeout=0.2)
                    if ok:
                        wake_ok = True
                        break
                    time.sleep(0.3)
                
                if wake_ok: break
            
            if wake_ok:
                self.connection_status.emit(True, self.camera_id, tr("camera.status.connected")) # Wach!
                time.sleep(1.0)
            else:
                # Auch wenn TCP Probe fehlschlägt, versuchen wir es trotzdem 
                # (manchen Kameras antworten nicht auf Port-Checks, aber auf echte RTSP-Anfragen)
                self.connection_status.emit(False, self.camera_id, tr("camera.status.connecting"))

        # RTSP Stream öffnen (mit Fallback-Pfaden für Reolink)
        # Wir versuchen zuerst den konfigurierten URL
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        
        # Falls die Kamera nicht öffnet, probieren wir Reolink-typische Varianten (H.264/H.265/Sub)
        if not self.cap.isOpened():
            base_url = self.rtsp_url.rsplit('/', 1)[0] if '/' in self.rtsp_url else self.rtsp_url
            for path in self._alt_paths:
                test_url = f"{base_url}/{path}"
                if test_url == self.rtsp_url: continue
                
                self.connection_status.emit(False, self.camera_id, f"Prüfe Pfad: {path}...")
                self.cap = cv2.VideoCapture(test_url, cv2.CAP_FFMPEG)
                if self.cap.isOpened():
                    self.rtsp_url = test_url
                    break
        
        if not self.cap.isOpened():
            # Diagnostik: Wenn RTSP zu ist, aber Port 8000 offen, ist RTSP wahrscheinlich in der Kamera deaktiviert
            if self._host:
                ok_api, _ = _tcp_probe(self._host, 8000, timeout=0.5)
                if ok_api:
                    raise Exception("Kamera antwortet auf API (Port 8000), aber RTSP ist blockiert. Bitte 'RTSP' in den Kamera-Einstellungen (Netzwerk -> Fortgeschritten -> Servereinstellungen) aktivieren!")
            raise Exception(tr("camera.error.stream_unreachable"))
        
        # Optimierungen für geringe Latenz
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FPS, 25)
        
        self.connection_status.emit(True, self.camera_id, tr("camera.status.connected"))
        
        frame_skip = 0
        skip_interval = 1  # Jedes zweite Frame für CPU-Schonung
        
        while self.running:
            ret, frame = self.cap.read()
            
            if not ret:
                raise Exception(tr("camera.error.stream_interrupted"))
            
            # CPU-Schonung: nicht jedes Frame verarbeiten
            frame_skip += 1
            if frame_skip % skip_interval == 0:
                # Frame an UI senden
                self.frame_ready.emit(frame.copy(), self.camera_id)
            
            # Aufzeichnung (alle Frames)
            with self._writer_lock:
                if self.recording and self.video_writer is not None:
                    try:
                        self.video_writer.write(frame)
                    except Exception:
                        # Don't crash the streaming thread due to writer issues.
                        pass
            
            # CPU-Schonung: Kleine Pause
            self.msleep(33)  # ~30 FPS
    
    def _cleanup(self):
        """Ressourcen freigeben"""
        if self.cap:
            self.cap.release()
            self.cap = None
        with self._writer_lock:
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
            self.recording = False
    
    def start_recording(self, output_path):
        """Starte Aufzeichnung"""
        if not (self.cap and self.cap.isOpened()):
            return None

        with self._writer_lock:
            if self.recording and self.video_writer is not None:
                return None

            # Ensure any previous writer is closed before re-opening
            if self.video_writer is not None:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
                self.video_writer = None

            fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            if not fps or fps <= 0 or fps > 120:
                fps = 25.0
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width <= 0 or height <= 0:
                width, height = 640, 480

            os.makedirs(output_path, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Some streams behave badly with MPEG4/XVID timestamping (invalid PTS).
            # MJPG-in-AVI is usually more tolerant.
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            filename = os.path.join(output_path, f"camera_{self.camera_id}_{timestamp}.avi")

            vw = cv2.VideoWriter(filename, fourcc, fps, (width, height))
            if not vw.isOpened():
                return None

            self.video_writer = vw
            self.recording = True
            return filename
        return None
    
    def stop_recording(self):
        """Stoppe Aufzeichnung"""
        with self._writer_lock:
            self.recording = False
            if self.video_writer:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
                self.video_writer = None
    
    def stop(self):
        """Thread stoppen"""
        self.running = False
        self.wait()


class CameraWidget(QWidget):
    """Widget für einzelne Kamera-Anzeige"""
    clicked = pyqtSignal(int)
    stream_toggled = pyqtSignal(int, bool)
    snapshot_requested = pyqtSignal(int)

    def __init__(self, camera_id, camera_name=""):
        super().__init__()
        self.camera_id = camera_id
        self.camera_name = camera_name or tr("camera.default_name.id", id=camera_id)
        self.recording = False
        self.last_frame_time = datetime.now()
        self.stream_active = False
        self.last_frame = None
        self._drag_start_pos = None
        self._video_drag_start_pos = None
        self._video_dragging = False
        
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Video Label
        self.video_label = QLabel()
        self.video_label.setFixedSize(180, 120)
        self.video_label.setStyleSheet("border: 2px solid #555; background-color: black;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText(f"{self.camera_name}\n{tr('camera.preview.click_to_start')}")
        self.video_label.setScaledContents(False)
        self.video_label.mousePressEvent = self._on_video_mouse_press
        self.video_label.mouseMoveEvent = self._on_video_mouse_move
        self.video_label.mouseReleaseEvent = self._on_video_mouse_release
        
        # Info Label mit FPS
        self.info_label = QLabel(f"{self.camera_name} - {tr('camera.status.offline')}")
        self.info_label.setStyleSheet("color: red; font-weight: bold; font-size: 11px;")
        self.info_label.setWordWrap(False)
        self.info_label.setFixedHeight(18)
        
        # Button Layout
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        icon_size = QSize(18, 18)

        # Aufnahme Button
        self.record_btn = QPushButton()
        self.record_btn.setCheckable(True)
        self.record_btn.setEnabled(False)
        self.record_btn.setMaximumWidth(40)
        self.record_btn.setFixedHeight(24)
        self.record_btn.setIcon(load_svg_icon("record.svg"))
        self.record_btn.setIconSize(icon_size)
        self.record_btn.setToolTip(tr("camera.tooltip.record"))
        self.record_btn.clicked.connect(self.toggle_recording)

        self.stream_btn = QPushButton()
        self.stream_btn.setCheckable(True)
        self.stream_btn.setMaximumWidth(40)
        self.stream_btn.setFixedHeight(24)
        self.stream_btn.setIcon(load_svg_icon("play.svg"))
        self.stream_btn.setIconSize(icon_size)
        self.stream_btn.setToolTip(tr("camera.tooltip.stream"))
        self.stream_btn.clicked.connect(self.toggle_stream)

        self.snapshot_btn = QPushButton()
        self.snapshot_btn.setMaximumWidth(40)
        self.snapshot_btn.setFixedHeight(24)
        self.snapshot_btn.setIcon(load_svg_icon("camera.svg"))
        self.snapshot_btn.setIconSize(icon_size)
        self.snapshot_btn.setToolTip(tr("camera.tooltip.snapshot"))
        self.snapshot_btn.clicked.connect(self._request_snapshot)
        
        # Edit Button
        self.edit_btn = QPushButton()
        self.edit_btn.setMaximumWidth(40)
        self.edit_btn.setFixedHeight(24)
        self.edit_btn.setToolTip(tr("camera.tooltip.edit"))
        self.edit_btn.setIcon(load_svg_icon("pencil.svg"))
        self.edit_btn.setIconSize(icon_size)
        self.edit_btn.setStyleSheet("color: #64b5f6;")
        
        # Entfernen Button
        self.remove_btn = QPushButton()
        self.remove_btn.setMaximumWidth(40)
        self.remove_btn.setFixedHeight(24)
        self.remove_btn.setToolTip(tr("camera.tooltip.remove"))
        self.remove_btn.setIcon(load_svg_icon("trash.svg"))
        self.remove_btn.setIconSize(icon_size)
        self.remove_btn.setStyleSheet("color: #999;")
        
        btn_layout.addWidget(self.stream_btn)
        btn_layout.addWidget(self.record_btn)
        btn_layout.addWidget(self.snapshot_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        
        layout.addWidget(self.video_label)
        layout.addWidget(self.info_label)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(200)
        self.setFixedHeight(120 + 18 + 24 + 16)

        self.set_selected(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        if self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return

        if (event.pos() - self._drag_start_pos).manhattanLength() < 8:
            super().mouseMoveEvent(event)
            return

        mime = QMimeData()
        mime.setData("application/x-wildcam-camera-id", str(self.camera_id).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

        self._drag_start_pos = None
        super().mouseMoveEvent(event)
    
    def _on_video_clicked(self, event):
        self.clicked.emit(self.camera_id)

    def _on_video_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._video_drag_start_pos = event.pos()
            self._video_dragging = False

    def _on_video_mouse_move(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        if self._video_drag_start_pos is None:
            return

        if (event.pos() - self._video_drag_start_pos).manhattanLength() < 8:
            return

        if self._video_dragging:
            return

        self._video_dragging = True
        mime = QMimeData()
        mime.setData("application/x-wildcam-camera-id", str(self.camera_id).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def _on_video_mouse_release(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._video_dragging:
                self._on_video_clicked(event)
            self._video_drag_start_pos = None
            self._video_dragging = False

    def update_frame(self, frame):
        """Frame aktualisieren mit FPS-Berechnung"""
        self.last_frame = frame

        # FPS berechnen
        now = datetime.now()
        fps = 1.0 / (now - self.last_frame_time).total_seconds() if (now - self.last_frame_time).total_seconds() > 0 else 0
        self.last_frame_time = now
        
        # Resize für Display
        display_w = max(1, self.video_label.width())
        display_h = max(1, self.video_label.height())
        frame_resized = cv2.resize(frame, (display_w, display_h))
        
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
        
        # Aufnahme-Indikator
        if self.recording:
            cv2.circle(rgb_frame, (20, 20), 8, (255, 0, 0), -1)
            cv2.putText(rgb_frame, "REC", (35, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
        
        # FPS anzeigen
        cv2.putText(rgb_frame, f"{fps:.1f} FPS", (display_w - 80, 25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Convert to QImage
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        self.video_label.setPixmap(QPixmap.fromImage(qt_image))
    
    def update_status(self, connected, message):
        """Status aktualisieren"""
        if connected:
            self.info_label.setText(f"{self.camera_name} - {message}")
            self.info_label.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
            self.record_btn.setEnabled(True)
        else:
            self.info_label.setText(f"{self.camera_name} - {message}")
            self.info_label.setStyleSheet("color: red; font-weight: bold; font-size: 11px;")
            self.record_btn.setEnabled(False)
            if self.stream_active:
                self.video_label.setText(f"{self.camera_name}\n{message}\n{tr('camera.preview.retrying')}")
            else:
                self.video_label.setText(f"{self.camera_name}\n{tr('camera.preview.click_to_start')}")
    
    def toggle_recording(self):
        """Aufnahme umschalten"""
        self.recording = self.record_btn.isChecked()
        if self.recording:
            self.record_btn.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
        else:
            self.record_btn.setStyleSheet("")

    def toggle_stream(self):
        self.stream_active = self.stream_btn.isChecked()
        if self.stream_active:
            self.stream_btn.setIcon(load_svg_icon("stop.svg"))
        else:
            self.stream_btn.setIcon(load_svg_icon("play.svg"))
        self.stream_toggled.emit(self.camera_id, self.stream_active)

    def set_stream_active(self, active):
        self.stream_active = active
        self.stream_btn.blockSignals(True)
        self.stream_btn.setChecked(active)
        self.stream_btn.setIcon(load_svg_icon("stop.svg") if active else load_svg_icon("play.svg"))
        self.stream_btn.blockSignals(False)
        if not active:
            self.video_label.setText(f"{self.camera_name}\n{tr('camera.preview.click_to_start')}")

    def retranslate_ui(self):
        self.record_btn.setToolTip(tr("camera.tooltip.record"))
        self.stream_btn.setToolTip(tr("camera.tooltip.stream"))
        self.snapshot_btn.setToolTip(tr("camera.tooltip.snapshot"))
        self.edit_btn.setToolTip(tr("camera.tooltip.edit"))
        self.remove_btn.setToolTip(tr("camera.tooltip.remove"))
        if not self.stream_active:
            self.video_label.setText(f"{self.camera_name}\n{tr('camera.preview.click_to_start')}")

    def _request_snapshot(self):
        self.snapshot_requested.emit(self.camera_id)

    def set_selected(self, selected: bool):
        if selected:
            self.video_label.setStyleSheet("border: 2px solid #1976d2; background-color: black;")
        else:
            self.video_label.setStyleSheet("border: 2px solid #555; background-color: black;")


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung"""
    def __init__(self):
        super().__init__()
        self.language = "de"
        set_language(self.language)
        self.setWindowTitle(tr("app.title"))
        self.setGeometry(100, 100, 1200, 800)
        
        self.cameras = []
        self.camera_threads = {}  # Dict für parallele Thread-Verwaltung
        self.camera_widgets = {}  # Dict für Widget-Zugriff
        self.recording_path = os.path.expanduser("~/Videos/Reolink")
        self.snapshot_path = os.path.join(self.recording_path, "snapshots")
        self.cameras_per_row = 3  # Standard: 3 Kameras pro Reihe
        self.next_camera_id = 1
        self.selected_camera_id = None
        self._rebuilding_camera_list = False
        self._pending_order_apply = False
        self._closing = False
        self._order_custom = False
        
        # Erstelle Aufzeichnungsordner
        os.makedirs(self.recording_path, exist_ok=True)
        os.makedirs(self.snapshot_path, exist_ok=True)
        
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        """UI initialisieren"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        tabs = QTabWidget()
        tab_cameras = QWidget()
        tab_config = QWidget()
        self.tabs = tabs
        tabs.addTab(tab_cameras, tr("tab.cameras"))
        tabs.addTab(tab_config, tr("tab.config"))
        main_layout.addWidget(tabs)

        cameras_layout = QVBoxLayout(tab_cameras)
        config_tab_layout = QVBoxLayout(tab_config)
        cameras_layout.setContentsMargins(6, 6, 6, 6)
        cameras_layout.setSpacing(6)
        
        # Konfigurations-Panel
        config_group = QGroupBox(tr("group.camera_config"))
        self.config_group = config_group
        config_layout = QVBoxLayout()
        
        # Erste Zeile: URL und Name
        row1 = QHBoxLayout()
        self.url_label = QLabel(tr("label.rtsp_url"))
        row1.addWidget(self.url_label)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(tr("placeholder.rtsp_url"))
        self.url_input.setMinimumWidth(400)
        row1.addWidget(self.url_input)
        
        self.name_label = QLabel(tr("label.name"))
        row1.addWidget(self.name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("placeholder.name.short"))
        self.name_input.setMaximumWidth(150)
        row1.addWidget(self.name_input)
        
        self.uid_label = QLabel(tr("label.uid"))
        row1.addWidget(self.uid_label)
        self.uid_input = QLineEdit()
        self.uid_input.setPlaceholderText(tr("placeholder.uid"))
        self.uid_input.setMaximumWidth(150)
        row1.addWidget(self.uid_input)
        
        self.add_btn = QPushButton(tr("btn.add"))
        add_btn = self.add_btn
        add_btn.clicked.connect(self.add_camera)
        add_btn.setIcon(load_svg_icon("plus.svg"))
        add_btn.setIconSize(QSize(18, 18))
        row1.addWidget(add_btn)
        
        self.discover_btn = QPushButton(tr("btn.discover"))
        discover_btn = self.discover_btn
        discover_btn.clicked.connect(self.show_discovery_dialog)
        discover_btn.setIcon(load_svg_icon("search.svg"))
        discover_btn.setIconSize(QSize(18, 18))
        discover_btn.setStyleSheet("background-color: #1976d2; color: white; font-weight: bold;")
        row1.addWidget(discover_btn)
        
        config_layout.addLayout(row1)
        
        # Zweite Zeile: Grid-Einstellungen und Aktionen
        row2 = QHBoxLayout()
        self.grid_cols_label = QLabel(tr("label.cameras_per_row"))
        row2.addWidget(self.grid_cols_label)
        self.grid_cols_spin = QSpinBox()
        self.grid_cols_spin.setRange(1, 5)
        self.grid_cols_spin.setValue(3)
        self.grid_cols_spin.valueChanged.connect(self.update_grid_layout)
        row2.addWidget(self.grid_cols_spin)
        
        self.clear_btn = QPushButton(tr("btn.clear_all"))
        clear_btn = self.clear_btn
        clear_btn.clicked.connect(self.clear_cameras)
        row2.addWidget(clear_btn)
        
        self.path_btn = QPushButton(tr("btn.path"))
        path_btn = self.path_btn
        path_btn.clicked.connect(self.select_recording_path)
        path_btn.setIcon(load_svg_icon("folder.svg"))
        path_btn.setIconSize(QSize(18, 18))
        row2.addWidget(path_btn)

        self.language_label = QLabel(tr("label.language"))
        row2.addWidget(self.language_label)
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("language.de"), "de")
        self.language_combo.addItem(tr("language.en"), "en")
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.language_combo.setMaximumWidth(140)
        row2.addWidget(self.language_combo)
        
        row2.addStretch()
        config_layout.addLayout(row2)
        
        config_group.setLayout(config_layout)
        config_tab_layout.addWidget(config_group)
        config_tab_layout.addStretch()
        
        # Control Panel
        control_widget = QWidget()
        control_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        control_widget.setFixedHeight(36)

        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)
        
        self.start_all_btn = QPushButton(tr("btn.start_all"))
        self.start_all_btn.clicked.connect(self.start_all_streams)
        self.start_all_btn.setIcon(load_svg_icon("play.svg"))
        self.start_all_btn.setIconSize(QSize(18, 18))
        self.start_all_btn.setStyleSheet("font-weight: bold; padding: 4px 10px;")
        self.start_all_btn.setFixedHeight(28)
        
        self.stop_all_btn = QPushButton(tr("btn.stop_all"))
        self.stop_all_btn.clicked.connect(self.stop_all_streams)
        self.stop_all_btn.setIcon(load_svg_icon("stop.svg"))
        self.stop_all_btn.setIconSize(QSize(18, 18))
        self.stop_all_btn.setFixedHeight(28)
        
        self.record_all_btn = QPushButton(tr("btn.record_all"))
        self.record_all_btn.setCheckable(True)
        self.record_all_btn.clicked.connect(self.toggle_all_recording)
        self.record_all_btn.setIcon(load_svg_icon("record.svg"))
        self.record_all_btn.setIconSize(QSize(18, 18))
        self.record_all_btn.setFixedHeight(28)
        
        self.camera_count_label = QLabel(tr("label.camera_count", total=0, active=0))
        self.camera_count_label.setStyleSheet("font-weight: bold;")
        
        control_layout.addWidget(self.start_all_btn)
        control_layout.addWidget(self.stop_all_btn)
        control_layout.addWidget(self.record_all_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.camera_count_label)

        cameras_layout.addWidget(control_widget)

        self.grid_cols_label.setVisible(False)
        self.grid_cols_spin.setVisible(False)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.content_splitter = splitter

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.left_scroll.setMinimumWidth(260)

        self.camera_list_container = CameraListContainer()
        self.camera_list_container.order_changed.connect(self._on_camera_order_changed)
        self.left_scroll.setWidget(self.camera_list_container)
        splitter.addWidget(self.left_scroll)

        self.big_preview_container = QWidget()
        self.big_preview_layout = QVBoxLayout(self.big_preview_container)
        self.big_preview_layout.setContentsMargins(10, 0, 0, 0)
        self.big_preview_label = QLabel()
        self.big_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_preview_label.setText(tr("big.select_camera"))
        self.big_preview_label.setStyleSheet("border: 2px solid #555; background-color: black;")
        self.big_preview_label.setMinimumHeight(360)
        self.big_preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.big_preview_layout.addWidget(self.big_preview_label)

        splitter.addWidget(self.big_preview_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([300, 900])

        content_layout.addWidget(splitter)
        cameras_layout.addLayout(content_layout)
        
        # Status Bar
        self.statusBar().showMessage(tr("status.ready"))
        
        # Timer für Status-Updates
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status_display)
        self.status_timer.start(2000)  # Alle 2 Sekunden

    def _is_qobject_deleted(self, obj) -> bool:
        if obj is None:
            return True
        if sip is None:
            return False
        try:
            return bool(sip.isdeleted(obj))
        except Exception:
            return False

    def _get_or_create_camera_widget(self, camera: dict) -> CameraWidget:
        camera_id = int(camera.get('id'))
        camera_name = camera.get('name', tr("camera.default_name.id", id=camera_id))

        existing = self.camera_widgets.get(camera_id)
        if existing is not None and not self._is_qobject_deleted(existing):
            return existing

        widget = CameraWidget(camera_id, camera_name)
        widget.remove_btn.clicked.connect(lambda checked, cid=camera_id: self.remove_camera(cid))
        widget.edit_btn.clicked.connect(lambda checked, cid=camera_id: self.edit_camera(cid))
        widget.stream_toggled.connect(self.toggle_camera_stream)
        widget.clicked.connect(self.select_camera)
        widget.snapshot_requested.connect(self.save_camera_snapshot)
        widget.record_btn.clicked.connect(lambda checked, cid=camera_id, w=widget: self._on_record_btn_clicked(cid, w, checked))
        self.camera_widgets[camera_id] = widget
        return widget

    def _on_record_btn_clicked(self, camera_id: int, widget: CameraWidget, checked: bool):
        thread = self.camera_threads.get(camera_id)
        if thread is None:
            return
        self.toggle_camera_recording(thread, widget, checked)
    
    def show_discovery_dialog(self):
        """Kamera-Suche Dialog anzeigen"""
        dialog = CameraDiscoveryDialog(self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_cameras = dialog.get_selected_cameras()
            
            if not selected_cameras:
                return
            
            # Zugangsdaten aus Dialog
            username = dialog.username_input.text()
            password = dialog.password_input.text()
            
            added_count = 0
            for camera_info in selected_cameras:
                ip = camera_info['ip']
                name = camera_info['name']
                
                # RTSP Port bestimmen
                rtsp_port = 554 if 554 in camera_info['ports'] else (
                    8554 if 8554 in camera_info['ports'] else 554
                )
                
                # RTSP URL generieren (Reolink Standard)
                rtsp_url = f"rtsp://{username}:{password}@{ip}:{rtsp_port}/h264Preview_01_main"
                
                # Prüfe ob Kamera bereits existiert
                if any(c['url'] == rtsp_url for c in self.cameras):
                    continue
                
                # Kamera hinzufügen
                camera_id = self.next_camera_id
                self.next_camera_id += 1
                
                self.cameras.append({
                    'id': camera_id,
                    'url': rtsp_url,
                    'name': name,
                    'uid': camera_info.get('uid', '')
                })
                
                # Widget erstellen
                widget = CameraWidget(camera_id, name)
                widget.remove_btn.clicked.connect(lambda checked, cid=camera_id: self.remove_camera(cid))
                widget.edit_btn.clicked.connect(lambda checked, cid=camera_id: self.edit_camera(cid))
                widget.stream_toggled.connect(self.toggle_camera_stream)
                widget.clicked.connect(self.select_camera)
                widget.snapshot_requested.connect(self.save_camera_snapshot)
                self.camera_widgets[camera_id] = widget
                
                added_count += 1
            
            if added_count > 0:
                self.update_grid_layout()
                self.update_status_display()
                self.save_config()
                self.statusBar().showMessage(tr("status.auto_added", count=added_count))
    
    def add_camera(self):
        """Kamera hinzufügen"""
        url = self.url_input.text().strip()
        name = self.name_input.text().strip()
        uid = self.uid_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, tr("dialog.title.error"), tr("label.rtsp_url"))
            return
        
        camera_id = self.next_camera_id
        self.next_camera_id += 1
        
        camera_name = name if name else tr("camera.default_name.id", id=camera_id)
        
        # Kamera zur Liste hinzufügen
        self.cameras.append({
            'id': camera_id, 
            'url': url, 
            'name': camera_name,
            'uid': uid
        })
        
        # Widget erstellen
        widget = CameraWidget(camera_id, camera_name)
        widget.remove_btn.clicked.connect(lambda: self.remove_camera(camera_id))
        widget.edit_btn.clicked.connect(lambda: self.edit_camera(camera_id))
        widget.clicked.connect(self.select_camera)
        widget.stream_toggled.connect(self.toggle_camera_stream)
        widget.snapshot_requested.connect(self.save_camera_snapshot)
        self.camera_widgets[camera_id] = widget
        
        # Im Grid platzieren
        self.update_grid_layout()
        
        # Eingabe leeren
        self.url_input.clear()
        self.name_input.clear()
        self.uid_input.clear()
        
        self.update_status_display()
        self.statusBar().showMessage(tr("status.camera_added", name=camera_name))
        self.save_config()
    
    def edit_camera(self, camera_id):
        """Kamera bearbeiten"""
        # Kamera-Daten finden
        camera_data = next((c for c in self.cameras if c['id'] == camera_id), None)
        if not camera_data:
            return
        
        # Stream stoppen falls aktiv
        was_running = False
        if camera_id in self.camera_threads:
            thread = self.camera_threads[camera_id]
            if thread.isRunning():
                was_running = True
                thread.stop()
                del self.camera_threads[camera_id]
        
        # Edit Dialog öffnen
        dialog = CameraEditDialog(camera_data, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = dialog.get_camera_data()
            
            # Daten aktualisieren
            for camera in self.cameras:
                if camera['id'] == camera_id:
                    camera.update(updated_data)
                    break
            
            # Widget aktualisieren
            if camera_id in self.camera_widgets:
                widget = self.camera_widgets[camera_id]
                widget.camera_name = updated_data['name']
                widget.info_label.setText(f"{updated_data['name']} - {tr('camera.status.offline')}")
                if widget.stream_active:
                    widget.video_label.setText(f"{updated_data['name']}\n{tr('camera.preview.waiting')}")
                else:
                    widget.video_label.setText(f"{updated_data['name']}\n{tr('camera.preview.click_to_start')}")

            if self.selected_camera_id == camera_id:
                if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
                    self.big_preview_label.setText(f"{updated_data['name']}\n{tr('camera.preview.waiting')}")
                else:
                    self.big_preview_label.setText(f"{updated_data['name']}\n{tr('camera.preview.click_to_start')}")
            
            self.save_config()
            self.statusBar().showMessage(tr("status.camera_updated", name=updated_data['name']))
            
            # Stream neu starten falls vorher aktiv
            if was_running:
                QTimer.singleShot(500, lambda: self.start_single_stream(camera_id))
        else:
            # Bei Abbruch: Stream wieder starten falls vorher aktiv
            if was_running:
                QTimer.singleShot(500, lambda: self.start_single_stream(camera_id))
    
    def start_single_stream(self, camera_id):
        """Einzelnen Stream starten"""
        camera = next((c for c in self.cameras if c['id'] == camera_id), None)
        if not camera:
            return
        
        # Skip wenn bereits läuft
        if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
            return

        if camera_id in self.camera_widgets and self.camera_widgets[camera_id].record_btn.isChecked():
            self.camera_widgets[camera_id].record_btn.setChecked(False)
            self.camera_widgets[camera_id].toggle_recording()
        
        # Neuen Thread erstellen
        thread = CameraThread(camera_id, camera['url'], camera.get('uid', ''))
        
        # Signals verbinden
        thread.frame_ready.connect(lambda frame, cid=camera_id: self.update_camera_frame(frame, cid))
        thread.connection_status.connect(lambda connected, cid, msg: self.update_camera_status(connected, cid, msg))
        
        # Aufnahme-Button verbinden
        if camera_id in self.camera_widgets:
            widget = self.camera_widgets[camera_id]
            widget.record_btn.clicked.connect(
                lambda checked, t=thread, w=widget: self.toggle_camera_recording(t, w, checked)
            )
        
        # Thread starten
        thread.start()
        self.camera_threads[camera_id] = thread
        if camera_id in self.camera_widgets:
            self.camera_widgets[camera_id].set_stream_active(True)
        self.statusBar().showMessage(tr("status.stream_started", name=camera['name']))

    def stop_single_stream(self, camera_id):
        if camera_id in self.camera_threads:
            self.camera_threads[camera_id].stop()
            del self.camera_threads[camera_id]

        if camera_id in self.camera_widgets:
            widget = self.camera_widgets[camera_id]
            if widget.record_btn.isChecked():
                widget.record_btn.setChecked(False)
                widget.toggle_recording()
            widget.set_stream_active(False)
            widget.update_status(False, tr("camera.status.stopped"))

        if self.selected_camera_id == camera_id:
            self.big_preview_label.setPixmap(QPixmap())
            widget = self.camera_widgets.get(camera_id)
            if widget:
                self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.click_to_start')}")

    def toggle_camera_stream(self, camera_id, enabled):
        if enabled:
            self.start_single_stream(camera_id)
        else:
            self.stop_single_stream(camera_id)
    
    def remove_camera(self, camera_id):
        """Einzelne Kamera entfernen"""
        camera = next((c for c in self.cameras if c.get('id') == camera_id), None)
        camera_name = None
        if camera:
            camera_name = camera.get('name')
        if not camera_name and camera_id in self.camera_widgets:
            camera_name = self.camera_widgets[camera_id].camera_name
        if not camera_name:
            camera_name = tr("camera.default_name.id", id=camera_id)

        reply = QMessageBox.question(
            self,
            tr('dialog.title.confirm'),
            tr('dialog.confirm.remove_one', name=camera_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Thread stoppen falls aktiv
        if camera_id in self.camera_threads:
            self.camera_threads[camera_id].stop()
            del self.camera_threads[camera_id]
        
        # Widget entfernen
        if camera_id in self.camera_widgets:
            widget = self.camera_widgets[camera_id]
            self._remove_camera_list_item(camera_id)
            widget.deleteLater()
            del self.camera_widgets[camera_id]

        if self.selected_camera_id == camera_id:
            self.selected_camera_id = None
            self.big_preview_label.setPixmap(QPixmap())
            self.big_preview_label.setText(tr("big.select_camera"))
        
        # Aus Liste entfernen
        self.cameras = [c for c in self.cameras if c['id'] != camera_id]
        
        self.update_grid_layout()
        self.update_status_display()
        self.save_config()
        self.statusBar().showMessage(tr("status.camera_removed", id=camera_id))
    
    def update_grid_layout(self):
        """Kamera-Liste neu aufbauen"""
        if not hasattr(self, "camera_list_container"):
            return

        self._rebuilding_camera_list = True
        layout = self.camera_list_container.layout_ref

        # Detach existing widgets from layout without deleting them
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)

        for camera in self.cameras:
            widget = self._get_or_create_camera_widget(camera)
            if self._is_qobject_deleted(widget):
                continue
            layout.addWidget(widget)

        self._rebuilding_camera_list = False
    
    def clear_cameras(self):
        """Alle Kameras entfernen"""
        if not self.cameras:
            return
        
        reply = QMessageBox.question(self, tr('dialog.title.confirm'),
                                    tr('dialog.confirm.remove_all'),
                                    QMessageBox.StandardButton.Yes | 
                                    QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.stop_all_streams()
            
            for widget in self.camera_widgets.values():
                widget.deleteLater()
            
            self.camera_widgets.clear()
            self.cameras.clear()
            self.next_camera_id = 1
            self.selected_camera_id = None
            self.big_preview_label.setPixmap(QPixmap())
            self.big_preview_label.setText(tr("big.select_camera"))
            if hasattr(self, "camera_list_container"):
                layout = self.camera_list_container.layout_ref
                while layout.count():
                    item = layout.takeAt(0)
                    w = item.widget() if item else None
                    if w is not None:
                        w.setParent(None)
            self.update_status_display()
            self.save_config()
            self.statusBar().showMessage(tr("status.cameras_removed"))
    
    def start_all_streams(self):
        """Alle Streams parallel starten"""
        if not self.cameras:
            QMessageBox.information(self, tr("dialog.title.info"), tr("dialog.msg.no_cameras"))
            return
        
        # Threads parallel starten
        for camera in self.cameras:
            camera_id = camera['id']
            
            # Skip wenn bereits läuft
            if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
                continue
            
            # Neuen Thread erstellen
            thread = CameraThread(camera_id, camera['url'], camera.get('uid', ''))
            
            # Signals verbinden
            thread.frame_ready.connect(lambda frame, cid=camera_id: self.update_camera_frame(frame, cid))
            thread.connection_status.connect(lambda connected, cid, msg: self.update_camera_status(connected, cid, msg))
            
            # Thread starten (parallel)
            thread.start()
            self.camera_threads[camera_id] = thread

            if camera_id in self.camera_widgets:
                self.camera_widgets[camera_id].set_stream_active(True)
        
        self.statusBar().showMessage(tr("status.streams_starting", count=len(self.cameras)))
    
    def stop_all_streams(self):
        """Alle Streams stoppen"""
        for thread in list(self.camera_threads.values()):
            thread.stop()
        self.camera_threads.clear()

        for camera_id, widget in list(self.camera_widgets.items()):
            try:
                if widget.record_btn.isChecked():
                    widget.record_btn.setChecked(False)
                    widget.toggle_recording()
                widget.set_stream_active(False)
                widget.update_status(False, tr("camera.status.stopped"))
            except RuntimeError:
                # Widget already deleted during shutdown/rebuild
                continue

        if self.selected_camera_id is not None:
            widget = self.camera_widgets.get(self.selected_camera_id)
            if widget:
                self.big_preview_label.setPixmap(QPixmap())
                self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.click_to_start')}")

        self.update_status_display()
        self.statusBar().showMessage(tr("status.streams_stopped"))
    
    def update_camera_frame(self, frame, camera_id):
        """Frame einer Kamera aktualisieren"""
        widget = self.camera_widgets.get(camera_id)
        if widget is not None:
            try:
                widget.update_frame(frame)
            except RuntimeError:
                return

        if self.selected_camera_id == camera_id:
            self._update_big_preview_frame(frame)
    
    def update_camera_status(self, connected, camera_id, message):
        """Status einer Kamera aktualisieren"""
        widget = self.camera_widgets.get(camera_id)
        if widget is not None:
            try:
                widget.update_status(connected, message)
            except RuntimeError:
                return
    
    def toggle_camera_recording(self, thread, widget, checked):
        """Aufnahme einer einzelnen Kamera umschalten"""
        if checked:
            filename = thread.start_recording(self.recording_path)
            if filename:
                self.statusBar().showMessage(tr("status.recording", name=os.path.basename(filename)))
        else:
            thread.stop_recording()
            self.statusBar().showMessage(tr("status.recording_stopped", name=widget.camera_name))
    
    def toggle_all_recording(self):
        """Alle Aufnahmen umschalten"""
        recording = self.record_all_btn.isChecked()
        
        count = 0
        for camera_id, widget in self.camera_widgets.items():
            if widget.record_btn.isEnabled() and camera_id in self.camera_threads:
                widget.record_btn.setChecked(recording)
                widget.toggle_recording()
                
                thread = self.camera_threads[camera_id]
                if recording:
                    thread.start_recording(self.recording_path)
                else:
                    thread.stop_recording()
                count += 1
        
        if recording:
            self.record_all_btn.setText(tr("btn.record_all_stop"))
            self.record_all_btn.setIcon(load_svg_icon("stop.svg"))
            self.record_all_btn.setIconSize(QSize(18, 18))
            self.record_all_btn.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
            self.statusBar().showMessage(tr("status.recordings_started", count=count))
        else:
            self.record_all_btn.setText(tr("btn.record_all"))
            self.record_all_btn.setIcon(load_svg_icon("record.svg"))
            self.record_all_btn.setIconSize(QSize(18, 18))
            self.record_all_btn.setStyleSheet("")
            self.statusBar().showMessage(tr("status.recordings_stopped", count=count))
    
    def update_status_display(self):
        """Statusanzeige aktualisieren"""
        total = len(self.cameras)
        active = len([t for t in self.camera_threads.values() if t.isRunning()])
        self.camera_count_label.setText(tr("label.camera_count", total=total, active=active))
    
    def select_recording_path(self):
        """Speicherort für Aufnahmen wählen"""
        path = QFileDialog.getExistingDirectory(self, tr("dialog.path.choose"), self.recording_path)
        if path:
            self.recording_path = path
            self.snapshot_path = os.path.join(self.recording_path, "snapshots")
            os.makedirs(self.snapshot_path, exist_ok=True)
            self.save_config()
            self.statusBar().showMessage(tr("status.path", path=path))

    def save_camera_snapshot(self, camera_id):
        widget = self.camera_widgets.get(camera_id)
        if not widget or widget.last_frame is None:
            self.statusBar().showMessage(tr("status.no_image"))
            return

        os.makedirs(self.snapshot_path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if (c.isalnum() or c in "-_") else "_" for c in widget.camera_name)
        filename = os.path.join(self.snapshot_path, f"{safe_name}_{camera_id}_{timestamp}.jpg")

        try:
            cv2.imwrite(filename, widget.last_frame)
            self.statusBar().showMessage(tr("status.snapshot_saved", name=os.path.basename(filename)))
        except Exception as e:
            self.statusBar().showMessage(tr("status.snapshot_error", error=e))
    
    def save_config(self):
        """Konfiguration speichern"""
        config = {
            'cameras': self.cameras,
            'recording_path': self.recording_path,
            'cameras_per_row': self.cameras_per_row,
            'next_camera_id': self.next_camera_id,
            'language': self.language,
            'order_custom': self._order_custom,
        }
        try:
            with open('camera_config.json', 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Fehler beim Speichern: {e}")
    
    def load_config(self):
        """Konfiguration laden"""
        try:
            with open('camera_config.json', 'r') as f:
                config = json.load(f)
                self.language = config.get('language', self.language)
                set_language(self.language)
                loaded_cameras = config.get('cameras', [])
                fixed_config = False

                # Deduplicate IDs: duplicate IDs lead to widget reuse, gaps, and crashes.
                used_ids = set()
                max_id = 0
                for c in loaded_cameras:
                    try:
                        cid = int(c.get('id'))
                    except Exception:
                        cid = None
                    if cid is not None:
                        max_id = max(max_id, cid)

                deduped = []
                for c in loaded_cameras:
                    try:
                        cid = int(c.get('id'))
                    except Exception:
                        cid = None

                    if cid is None:
                        max_id += 1
                        c['id'] = max_id
                        used_ids.add(max_id)
                        deduped.append(c)
                        fixed_config = True
                        continue

                    if cid in used_ids:
                        max_id += 1
                        c['id'] = max_id
                        used_ids.add(max_id)
                        deduped.append(c)
                        fixed_config = True
                    else:
                        used_ids.add(cid)
                        deduped.append(c)

                # Deduplicate by URL as well (older drag&drop/config corruption could
                # duplicate entire camera entries).
                seen_urls = set()
                deduped_by_url = []
                for c in deduped:
                    url = (c.get('url') or '').strip()
                    if not url:
                        deduped_by_url.append(c)
                        continue
                    if url in seen_urls:
                        fixed_config = True
                        continue
                    seen_urls.add(url)
                    # UID explizit sicherstellen (falls vorhanden)
                    if 'uid' not in c:
                        c['uid'] = ''
                        fixed_config = True # Sorgen wir dafür, dass es gespeichert wird
                    deduped_by_url.append(c)

                self.cameras = deduped_by_url
                self.recording_path = config.get('recording_path', self.recording_path)
                self.snapshot_path = os.path.join(self.recording_path, "snapshots")
                self.cameras_per_row = config.get('cameras_per_row', 3)
                self._order_custom = bool(config.get('order_custom', False))
                if not self._order_custom:
                    try:
                        self.cameras.sort(key=lambda c: int(c.get('id', 0)))
                    except Exception:
                        pass
                repaired_next_id = max([c.get('id', 0) for c in self.cameras] + [0]) + 1
                if config.get('next_camera_id') != repaired_next_id:
                    fixed_config = True
                self.next_camera_id = repaired_next_id
                
                self.grid_cols_spin.setValue(self.cameras_per_row)
                if hasattr(self, "language_combo"):
                    idx = self.language_combo.findData(self.language)
                    if idx >= 0:
                        self.language_combo.blockSignals(True)
                        self.language_combo.setCurrentIndex(idx)
                        self.language_combo.blockSignals(False)
                
                # Widgets erstellen
                for camera in self.cameras:
                    widget = self._get_or_create_camera_widget(camera)
                    widget.retranslate_ui()
                
                self.update_grid_layout()
                self.update_status_display()
                self.retranslate_ui()

                if fixed_config:
                    self.save_config()
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
    
    def closeEvent(self, event):
        """Beim Schließen alle Threads sauber beenden"""
        self._closing = True
        self.save_config()
        self.stop_all_streams()
        event.accept()

    def select_camera(self, camera_id):
        self.selected_camera_id = camera_id

        for cid, widget in self.camera_widgets.items():
            if cid == camera_id:
                widget.set_selected(True)
            else:
                widget.set_selected(False)

        widget = self.camera_widgets.get(camera_id)
        if widget:
            if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
                self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.waiting')}")
            else:
                self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.click_to_start')}")

        if camera_id not in self.camera_threads or not self.camera_threads[camera_id].isRunning():
            self.start_single_stream(camera_id)

    def _on_language_changed(self):
        if not hasattr(self, "language_combo"):
            return
        lang = self.language_combo.currentData()
        if not lang:
            return
        self.language = lang
        set_language(lang)
        self.retranslate_ui()
        for w in self.camera_widgets.values():
            w.retranslate_ui()
        self.save_config()

    def retranslate_ui(self):
        self.setWindowTitle(tr("app.title"))
        if hasattr(self, "tabs"):
            self.tabs.setTabText(0, tr("tab.cameras"))
            self.tabs.setTabText(1, tr("tab.config"))
        if hasattr(self, "config_group"):
            self.config_group.setTitle(tr("group.camera_config"))
        if hasattr(self, "url_label"):
            self.url_label.setText(tr("label.rtsp_url"))
        if hasattr(self, "name_label"):
            self.name_label.setText(tr("label.name"))
        if hasattr(self, "grid_cols_label"):
            self.grid_cols_label.setText(tr("label.cameras_per_row"))
        if hasattr(self, "url_input"):
            self.url_input.setPlaceholderText(tr("placeholder.rtsp_url"))
        if hasattr(self, "name_input"):
            self.name_input.setPlaceholderText(tr("placeholder.name.short"))
        if hasattr(self, "add_btn"):
            self.add_btn.setText(tr("btn.add"))
        if hasattr(self, "discover_btn"):
            self.discover_btn.setText(tr("btn.discover"))
        if hasattr(self, "clear_btn"):
            self.clear_btn.setText(tr("btn.clear_all"))
        if hasattr(self, "path_btn"):
            self.path_btn.setText(tr("btn.path"))
        if hasattr(self, "language_label"):
            self.language_label.setText(tr("label.language"))
        if hasattr(self, "language_combo"):
            current = self.language_combo.currentData()
            self.language_combo.blockSignals(True)
            self.language_combo.clear()
            self.language_combo.addItem(tr("language.de"), "de")
            self.language_combo.addItem(tr("language.en"), "en")
            idx = self.language_combo.findData(current or self.language)
            if idx >= 0:
                self.language_combo.setCurrentIndex(idx)
            self.language_combo.blockSignals(False)
        if hasattr(self, "start_all_btn"):
            self.start_all_btn.setText(tr("btn.start_all"))
        if hasattr(self, "stop_all_btn"):
            self.stop_all_btn.setText(tr("btn.stop_all"))
        if hasattr(self, "record_all_btn"):
            if self.record_all_btn.isChecked():
                self.record_all_btn.setText(tr("btn.record_all_stop"))
            else:
                self.record_all_btn.setText(tr("btn.record_all"))
        self.update_status_display()
        if self.selected_camera_id is None and hasattr(self, "big_preview_label"):
            if not self.big_preview_label.pixmap() or self.big_preview_label.pixmap().isNull():
                self.big_preview_label.setText(tr("big.select_camera"))

    def _on_camera_order_changed(self, ordered_ids):
        if getattr(self, "_closing", False):
            return
        if getattr(self, "_rebuilding_camera_list", False):
            return

        try:
            ordered_ids = [int(x) for x in ordered_ids]
        except Exception:
            return

        if not ordered_ids:
            return

        camera_by_id = {int(c.get('id')): c for c in self.cameras if c.get('id') is not None}
        new_cameras = []
        for cid in ordered_ids:
            cam = camera_by_id.get(cid)
            if cam:
                new_cameras.append(cam)

        leftover = [c for c in self.cameras if int(c.get('id', -1)) not in set(ordered_ids)]
        self.cameras = new_cameras + leftover
        self._order_custom = True
        self.save_config()
        self.update_grid_layout()

    def _update_big_preview_frame(self, frame):
        display_w = max(1, self.big_preview_label.width())
        display_h = max(1, self.big_preview_label.height())

        src_h, src_w = frame.shape[:2]
        if src_w <= 0 or src_h <= 0:
            return

        scale = min(display_w / src_w, display_h / src_h)
        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))

        frame_resized = cv2.resize(frame, (new_w, new_h))
        rgb_small = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
        rgb_frame = np.zeros((display_h, display_w, 3), dtype=np.uint8)
        x = (display_w - new_w) // 2
        y = (display_h - new_h) // 2
        rgb_frame[y:y + new_h, x:x + new_w] = rgb_small

        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.big_preview_label.setPixmap(QPixmap.fromImage(qt_image))


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Dark Theme (optional)
    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #2b2b2b;
            color: #e0e0e0;
        }
        QGroupBox {
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QPushButton {
            background-color: #404040;
            border: 1px solid #555;
            padding: 5px 15px;
            border-radius: 3px;
        }
        QPushButton:hover {
            background-color: #4a4a4a;
        }
        QPushButton:pressed {
            background-color: #353535;
        }
        QLineEdit, QSpinBox {
            background-color: #353535;
            border: 1px solid #555;
            padding: 5px;
            border-radius: 3px;
        }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()