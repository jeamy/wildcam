import socket
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from camera_utils import _build_rtsp_url, camera_hosts, find_matching_camera
from netvue import DEFAULT_PORT as NETVUE_PORT, build_netvue_url, is_netvue_url, parse_netvue_url

# Pseudo path in the URL builder that switches to a netvue:// URL.
NETVUE_PATH = "netvue"
from discovery import CameraDiscoveryThread
from ptz import camera_has_ptz
from i18n import tr


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

        # PTZ (Steuerkreuz)
        self.ptz_checkbox = QCheckBox(tr("dialog.edit.ptz"))
        self._initial_ptz = camera_has_ptz(self.camera_data)
        self.ptz_checkbox.setChecked(self._initial_ptz)
        layout.addWidget(self.ptz_checkbox)
        
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
            "live",
            NETVUE_PATH,
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
        """Aktuellen URL in Felder zerlegen (Zugangsdaten URL-dekodiert)."""
        url = self.camera_data.get('url', '')
        if is_netvue_url(url):
            try:
                params = parse_netvue_url(url)
            except Exception:
                return
            self.ip_input.setText(params['host'])
            self.port_input.setText(str(params['port']))
            self.username_input.setText(params['user'])
            self.password_input.setText(params['key'])
            self.path_combo.setCurrentText(NETVUE_PATH)
            return
        if not url.lower().startswith(('rtsp://', 'rtsps://')):
            return
        sanitized = url.replace('#', '%23')
        try:
            u = urlparse(sanitized, allow_fragments=False)
            port = u.port
        except ValueError:
            return
        if not u.hostname:
            return
        self.ip_input.setText(u.hostname)
        self.port_input.setText(str(port or 554))
        self.username_input.setText(unquote(u.username or ''))
        self.password_input.setText(unquote(u.password or ''))
        path = u.path.lstrip('/')
        if u.query:
            path = f"{path}?{u.query}"
        self.path_combo.setCurrentText(path)
    
    def build_url(self):
        """URL aus Einzelteilen zusammenbauen"""
        ip = self.ip_input.text().strip()
        port = self.port_input.text().strip() or "554"
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        path = self.path_combo.currentText().strip()
        
        if not ip:
            QMessageBox.warning(self, tr("dialog.title.error"), tr("dialog.edit.err_ip"))
            return

        if path == NETVUE_PATH:
            # Netvue: user id + local key from the Netvue app (see README).
            if port == "554":
                port = str(NETVUE_PORT)
            self.url_input.setText(build_netvue_url(ip, username, password, int(port)))
            return
        
        url = _build_rtsp_url(
            host=ip,
            port=int(port),
            username=username,
            password=password,
            path=path
        )
        self.url_input.setText(url)
    
    def get_camera_data(self):
        """Geänderte Daten zurückgeben"""
        self.camera_data['name'] = self.name_input.text().strip()
        self.camera_data['url'] = self.url_input.text().strip()
        self.camera_data['uid'] = self.uid_input.text().strip()
        if self.ptz_checkbox.isChecked() != self._initial_ptz:
            # Manual choice wins over automatic detection.
            self.camera_data['ptz'] = self.ptz_checkbox.isChecked()
            self.camera_data['ptz_manual'] = True
        return self.camera_data


class CameraDiscoveryDialog(QDialog):
    """Dialog für Kamera-Suche"""
    def __init__(self, existing_cameras=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.discovery.title"))
        self.setModal(True)
        self.resize(820, 500)

        self.existing_cameras = list(existing_cameras or [])
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
        self.camera_table.setColumnCount(8)
        self.camera_table.setHorizontalHeaderLabels([
            tr("dialog.discovery.col.select"),
            tr("dialog.discovery.col.ip"),
            tr("dialog.discovery.col.name"),
            tr("dialog.discovery.col.model"),
            tr("dialog.discovery.col.manufacturer"),
            tr("dialog.discovery.col.ports"),
            tr("dialog.discovery.col.uid"),
            tr("dialog.discovery.col.in_list"),
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
        except Exception:
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
        known_hosts = sorted({host for camera in self.existing_cameras for host in camera_hosts(camera)})
        self.discovery_thread = CameraDiscoveryThread(
            network, username=username, password=password, known_hosts=known_hosts
        )
        self.discovery_thread.camera_found.connect(self.on_camera_found)
        self.discovery_thread.progress_update.connect(self.on_progress_update)
        self.discovery_thread.scan_complete.connect(self.on_scan_complete)
        self.discovery_thread.start()
    
    def done(self, result):
        # Never drop a running QThread (OK/Cancel during a scan would crash).
        if self.discovery_thread is not None and self.discovery_thread.isRunning():
            self.discovery_thread.stop()
            self.discovery_thread.wait(10000)
        super().done(result)

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
        existing = find_matching_camera(camera_info, self.existing_cameras)
        camera_info = {**camera_info, 'existing_id': existing.get('id') if existing else None}
        self.found_cameras.append(camera_info)

        row = self.camera_table.rowCount()
        self.camera_table.insertRow(row)

        # Checkbox (bereits vorhandene Kameras nicht vorauswählen)
        checkbox = QCheckBox()
        checkbox.setChecked(existing is None)
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
        self.camera_table.setItem(row, 7, QTableWidgetItem(existing.get('name', '') if existing else ''))
    
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
