import sys
import os

os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'
os.environ['AV_LOG_FORCE_NOCOLOR'] = '1'
os.environ['AV_LOG_FORCE_LEVEL'] = '-8'
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|loglevel;quiet'

import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from datetime import datetime
import time

from camera_utils import (
    _build_rtsp_url,
    _is_battery_camera,
    normalize_reolinkproxy_camera,
)
from config import DEFAULT_RECORDING_PATH, config_payload, load_config_data, save_config_data, snapshot_path_for
from dialogs import CameraDiscoveryDialog, CameraEditDialog
from i18n import set_language, tr
from stream import CameraThread
from ui_resources import load_svg_icon
from widgets import CameraListContainer, CameraWidget, PreviewLabel

try:
    import sip  # type: ignore
except Exception:  # pragma: no cover
    try:
        from PyQt6 import sip  # type: ignore
    except Exception:  # pragma: no cover
        sip = None


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
        self.recording_path = DEFAULT_RECORDING_PATH
        self.snapshot_path = snapshot_path_for(self.recording_path)
        self.cameras_per_row = 3  # Standard: 3 Kameras pro Reihe
        self.next_camera_id = 1
        self.selected_camera_id = None
        self.selected_camera_ids = []  # Multi-Kamera-Auswahl
        self._restore_preview_camera_ids = []
        self.multi_view_labels = {}  # Labels für Multi-Kamera-Ansicht
        self.zoomed_camera_id = None
        self.preview_crop_camera_id = None
        self.preview_crop_rect = None
        self._rebuilding_camera_list = False
        self._closing = False
        self._shutdown_started_at = None
        self._shutdown_dialog = None
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
        self.big_preview_label = PreviewLabel()
        self.big_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_preview_label.setText(tr("big.select_camera"))
        self.big_preview_label.setStyleSheet("border: 2px solid #555; background-color: black;")
        self.big_preview_label.setMinimumHeight(360)
        self.big_preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._connect_preview_label(self.big_preview_label)
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

    def _connect_preview_label(self, label: PreviewLabel):
        label.double_clicked.connect(self._on_big_preview_label_double_clicked)
        label.region_selected.connect(self._on_big_preview_region_selected)

    def _get_active_big_preview_camera_id(self):
        if self.selected_camera_ids:
            if self.zoomed_camera_id is not None and self.zoomed_camera_id in self.selected_camera_ids:
                return self.zoomed_camera_id
            if len(self.selected_camera_ids) == 1:
                return self.selected_camera_ids[0]
            return None
        return self.selected_camera_id

    def _get_preview_label_for_camera(self, camera_id):
        if camera_id is None:
            return None

        label = getattr(self, "big_preview_label", None)
        if label is not None and not self._is_qobject_deleted(label):
            try:
                if getattr(label, "camera_id", None) == camera_id:
                    return label
            except RuntimeError:
                pass

        label = self.multi_view_labels.get(camera_id)
        if label is not None and not self._is_qobject_deleted(label):
            return label
        return None

    def _clear_big_preview_crop(self):
        self.preview_crop_camera_id = None
        self.preview_crop_rect = None

    def _sync_big_preview_crop_state(self, active_camera_id):
        if active_camera_id is None or self.preview_crop_camera_id != active_camera_id:
            self._clear_big_preview_crop()

    def _update_big_preview_selection_state(self):
        active_camera_id = self._get_active_big_preview_camera_id()
        known_labels = []
        label = getattr(self, "big_preview_label", None)
        if label is not None and not self._is_qobject_deleted(label):
            known_labels.append(label)
        for multi_label in self.multi_view_labels.values():
            if multi_label is not None and not self._is_qobject_deleted(multi_label):
                known_labels.append(multi_label)
        for known_label in known_labels:
            try:
                known_label.set_selection_enabled(False)
            except RuntimeError:
                continue

        label = self._get_preview_label_for_camera(active_camera_id)
        if label is not None:
            try:
                label.set_selection_enabled(
                    self.preview_crop_rect is None and self.preview_crop_camera_id is None
                )
            except RuntimeError:
                pass

    def _refresh_big_preview_from_last_frame(self, camera_id):
        widget = self.camera_widgets.get(camera_id)
        if widget is None or widget.last_frame is None:
            return

        if self.selected_camera_ids:
            self._update_multi_view_frame(widget.last_frame, camera_id)
        elif self.selected_camera_id == camera_id:
            self._update_big_preview_frame(widget.last_frame)

    def _render_frame_to_label(self, label, frame, crop_rect=None):
        if label is None or self._is_qobject_deleted(label):
            return

        display_w = max(1, label.width())
        display_h = max(1, label.height())

        src_h, src_w = frame.shape[:2]
        if src_w <= 0 or src_h <= 0:
            label.clear_frame_display_rect()
            return

        crop_x = 0
        crop_y = 0
        crop_w = src_w
        crop_h = src_h

        if crop_rect is not None:
            crop_x = max(0, min(src_w - 1, crop_rect.x()))
            crop_y = max(0, min(src_h - 1, crop_rect.y()))
            max_crop_w = max(1, src_w - crop_x)
            max_crop_h = max(1, src_h - crop_y)
            crop_w = max(1, min(max_crop_w, crop_rect.width()))
            crop_h = max(1, min(max_crop_h, crop_rect.height()))

        frame_view = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
        if frame_view.size == 0:
            label.clear_frame_display_rect()
            return

        scale = min(display_w / crop_w, display_h / crop_h)
        new_w = max(1, int(crop_w * scale))
        new_h = max(1, int(crop_h * scale))

        frame_resized = cv2.resize(frame_view, (new_w, new_h))
        rgb_small = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
        rgb_frame = np.zeros((display_h, display_w, 3), dtype=np.uint8)
        x = (display_w - new_w) // 2
        y = (display_h - new_h) // 2
        rgb_frame[y:y + new_h, x:x + new_w] = rgb_small

        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qt_image)
        pixmap.setDevicePixelRatio(1.0)
        label.setPixmap(pixmap)
        label.set_frame_display_rect(QRect(x, y, new_w, new_h))

    def _get_or_create_camera_widget(self, camera: dict) -> CameraWidget:
        camera_id = int(camera.get('id'))
        camera_name = camera.get('name', tr("camera.default_name.id", id=camera_id))

        existing = self.camera_widgets.get(camera_id)
        if existing is not None and not self._is_qobject_deleted(existing):
            return existing

        # Check if battery camera
        model = camera.get('model', '')
        is_battery = _is_battery_camera(model, camera_name)
        
        widget = CameraWidget(camera_id, camera_name, is_battery=is_battery)
        widget.remove_btn.clicked.connect(lambda checked, cid=camera_id: self.remove_camera(cid))
        widget.edit_btn.clicked.connect(lambda checked, cid=camera_id: self.edit_camera(cid))
        widget.stream_toggled.connect(self.toggle_camera_stream)
        widget.clicked.connect(self.select_camera)
        widget.snapshot_requested.connect(self.save_camera_snapshot)
        widget.selection_changed.connect(self.on_camera_selection_changed)
        widget.record_btn.clicked.connect(lambda checked, cid=camera_id, w=widget: self._on_record_btn_clicked(cid, w, checked))
        self.camera_widgets[camera_id] = widget
        return widget

    def _remove_camera_list_item(self, camera_id: int):
        if not hasattr(self, "camera_list_container"):
            return
        layout = self.camera_list_container.layout_ref
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item else None
            if widget is not None and getattr(widget, "camera_id", None) == camera_id:
                layout.takeAt(index)
                widget.setParent(None)
                return

    def _on_record_btn_clicked(self, camera_id: int, widget: CameraWidget, checked: bool):
        thread = self.camera_threads.get(camera_id)
        if thread is None:
            return
        self.toggle_camera_recording(thread, widget, checked)

    def _allocate_camera_id(self) -> int:
        camera_id = self.next_camera_id
        self.next_camera_id += 1
        return camera_id

    def _add_camera_entry(self, camera_entry: dict):
        self.cameras.append(camera_entry)
        self._get_or_create_camera_widget(camera_entry)

    def _build_discovered_camera_entry(self, camera_info: dict, username: str, password: str) -> dict:
        rtsp_port = 554 if 554 in camera_info['ports'] else (
            8554 if 8554 in camera_info['ports'] else 554
        )
        camera_entry = {
            'id': self._allocate_camera_id(),
            'url': _build_rtsp_url(
                host=camera_info['ip'],
                port=rtsp_port,
                username=username,
                password=password,
                path="h264Preview_01_main"
            ),
            'name': camera_info['name'],
            'uid': camera_info.get('uid', ''),
            'model': camera_info.get('model', ''),
            'manufacturer': camera_info.get('manufacturer', '')
        }
        normalize_reolinkproxy_camera(camera_entry, username=username, password=password)
        return camera_entry

    def _build_manual_camera_entry(self, url: str, name: str, uid: str) -> dict:
        camera_id = self._allocate_camera_id()
        camera_entry = {
            'id': camera_id,
            'url': url,
            'name': name if name else tr("camera.default_name.id", id=camera_id),
            'uid': uid,
            'model': ''
        }
        normalize_reolinkproxy_camera(camera_entry)
        return camera_entry

    def _normalize_edited_camera_data(self, camera_data: dict, updated_data: dict) -> dict:
        normalized = dict(updated_data)
        normalized.setdefault('model', camera_data.get('model', ''))
        normalized.setdefault('manufacturer', camera_data.get('manufacturer', ''))
        normalize_reolinkproxy_camera(normalized)
        return normalized

    def _start_camera_thread(self, camera: dict) -> CameraThread:
        camera_id = camera['id']
        thread = CameraThread(camera_id, camera['url'], camera.get('uid', ''))
        thread.frame_ready.connect(lambda frame, cid=camera_id: self.update_camera_frame(frame, cid))
        thread.connection_status.connect(lambda connected, cid, msg: self.update_camera_status(connected, cid, msg))
        thread.start()
        self.camera_threads[camera_id] = thread
        if camera_id in self.camera_widgets:
            self.camera_widgets[camera_id].set_stream_active(True)
        return thread

    def _clear_big_preview_label(self, text: str = ""):
        self.big_preview_label.setPixmap(QPixmap())
        self.big_preview_label.clear_frame_display_rect()
        if text:
            self.big_preview_label.setText(text)

    def _camera_waiting_text(self, camera_name: str) -> str:
        return f"{camera_name}\n{tr('camera.preview.waiting')}"

    def _camera_click_to_start_text(self, camera_name: str) -> str:
        return f"{camera_name}\n{tr('camera.preview.click_to_start')}"
    
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
            battery_cameras = []
            
            for camera_info in selected_cameras:
                name = camera_info['name']
                model = camera_info.get('model', '')
                
                # Check if battery camera
                if _is_battery_camera(model, name):
                    battery_cameras.append((name, model))

                camera_entry = self._build_discovered_camera_entry(camera_info, username, password)
                
                # Prüfe ob Kamera bereits existiert
                if any(c['url'] == camera_entry['url'] for c in self.cameras):
                    continue

                self._add_camera_entry(camera_entry)
                
                added_count += 1
            
            if added_count > 0:
                self.update_grid_layout()
                self.update_status_display()
                self.save_config()
                self.statusBar().showMessage(tr("status.auto_added", count=added_count))
                
                # Show battery camera warning if any detected
                if battery_cameras:
                    cam_list = "\n".join([f"• {name} ({model})" for name, model in battery_cameras])
                    QMessageBox.warning(
                        self,
                        tr("battery.warning.title"),
                        f"{len(battery_cameras)} {tr('battery.indicator')}:\n\n{cam_list}\n\n" + 
                        tr("battery.warning.message", name="", model="").replace("Die Kamera '' () ist eine Akku-betriebene Kamera.", 
                           "Diese Kameras sind Akku-betrieben.").replace("Camera '' () is battery-powered.", 
                           "These cameras are battery-powered.")
                    )
    
    def add_camera(self):
        """Kamera hinzufügen"""
        url = self.url_input.text().strip()
        name = self.name_input.text().strip()
        uid = self.uid_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, tr("dialog.title.error"), tr("label.rtsp_url"))
            return
        
        camera_name = name if name else tr("camera.default_name.id", id=self.next_camera_id)
        
        # Check if battery camera and show warning
        if _is_battery_camera("", camera_name):
            reply = QMessageBox.question(
                self,
                tr("battery.warning.title"),
                tr("battery.warning.message", name=camera_name, model="Battery Camera"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        camera_entry = self._build_manual_camera_entry(url, name, uid)
        self._add_camera_entry(camera_entry)
        camera_name = camera_entry['name']
        
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
                if thread.stop(timeout_ms=3000):
                    del self.camera_threads[camera_id]
                else:
                    QMessageBox.warning(self, tr("dialog.title.error"), "Stream wird noch beendet. Bitte gleich erneut versuchen.")
                    return
        
        # Edit Dialog öffnen
        dialog = CameraEditDialog(camera_data, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = self._normalize_edited_camera_data(camera_data, dialog.get_camera_data())
            
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
                    widget.video_label.setText(self._camera_waiting_text(updated_data['name']))
                else:
                    widget.video_label.setText(self._camera_click_to_start_text(updated_data['name']))

            if self.selected_camera_id == camera_id:
                if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
                    self.big_preview_label.setText(self._camera_waiting_text(updated_data['name']))
                else:
                    self.big_preview_label.setText(self._camera_click_to_start_text(updated_data['name']))
            
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
        
        self._start_camera_thread(camera)
        self.statusBar().showMessage(tr("status.stream_started", name=camera['name']))

    def stop_single_stream(self, camera_id):
        if camera_id in self.camera_threads:
            if self.camera_threads[camera_id].stop(timeout_ms=3000):
                del self.camera_threads[camera_id]
            else:
                self.statusBar().showMessage("Stream wird noch beendet...")
                return

        if self.preview_crop_camera_id == camera_id:
            self._clear_big_preview_crop()

        if camera_id in self.camera_widgets:
            widget = self.camera_widgets[camera_id]
            if widget.record_btn.isChecked():
                widget.record_btn.setChecked(False)
                widget.toggle_recording()
            widget.set_stream_active(False)
            widget.update_status(False, tr("camera.status.stopped"))

        if self.selected_camera_id == camera_id:
            widget = self.camera_widgets.get(camera_id)
            if widget:
                self._clear_big_preview_label(self._camera_click_to_start_text(widget.camera_name))

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
            if self.camera_threads[camera_id].stop(timeout_ms=3000):
                del self.camera_threads[camera_id]
            else:
                QMessageBox.warning(self, tr("dialog.title.error"), "Stream wird noch beendet. Bitte gleich erneut versuchen.")
                return
        
        # Widget entfernen
        if camera_id in self.camera_widgets:
            widget = self.camera_widgets[camera_id]
            self._remove_camera_list_item(camera_id)
            widget.deleteLater()
            del self.camera_widgets[camera_id]

        if self.selected_camera_id == camera_id:
            self.selected_camera_id = None
            if self.preview_crop_camera_id == camera_id:
                self._clear_big_preview_crop()
            self._clear_big_preview_label(tr("big.select_camera"))

        if camera_id in self.selected_camera_ids:
            self.selected_camera_ids.remove(camera_id)
            if self.zoomed_camera_id == camera_id:
                self.zoomed_camera_id = None
            self._sync_big_preview_crop_state(self._get_active_big_preview_camera_id())
            self._rebuild_multi_view_layout()
        
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
            self.selected_camera_ids = []
            self.zoomed_camera_id = None
            self._clear_big_preview_crop()
            self._clear_big_preview_label(tr("big.select_camera"))
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
            
            self._start_camera_thread(camera)
        
        self.statusBar().showMessage(tr("status.streams_starting", count=len(self.cameras)))
    
    def stop_all_streams(self):
        """Alle Streams stoppen"""
        threads = list(self.camera_threads.values())
        force_stop = bool(getattr(self, "_closing", False))

        for thread in threads:
            thread.request_stop()

        deadline = time.monotonic() + (2.5 if force_stop else 5.0)
        for thread in threads:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if thread.isRunning():
                thread.wait(remaining_ms)
        self.camera_threads = {
            camera_id: thread
            for camera_id, thread in self.camera_threads.items()
            if thread.isRunning()
        }
        if self.camera_threads:
            self.statusBar().showMessage("Streams werden noch beendet...")
            return
        self._clear_big_preview_crop()

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
                self._clear_big_preview_label(self._camera_click_to_start_text(widget.camera_name))
        self._update_big_preview_selection_state()

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

        # Update big preview for single camera selection (old behavior)
        if self.selected_camera_id == camera_id and len(self.selected_camera_ids) == 0:
            self._update_big_preview_frame(frame)
        
        # Update multi-view if camera is selected via checkbox
        if camera_id in self.selected_camera_ids:
            self._update_multi_view_frame(frame, camera_id)
    
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
            self.snapshot_path = snapshot_path_for(self.recording_path)
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
        try:
            save_config_data(config_payload(self))
        except Exception as e:
            print(f"Fehler beim Speichern: {e}")
    
    def load_config(self):
        """Konfiguration laden"""
        try:
            config, fixed_config = load_config_data()
            if config is None:
                return

            self.language = config.get('language', self.language)
            set_language(self.language)
            self.cameras = config.get('cameras', [])
            self.recording_path = config.get('recording_path', self.recording_path)
            self.snapshot_path = config.get('snapshot_path', snapshot_path_for(self.recording_path))
            self.cameras_per_row = config.get('cameras_per_row', 3)
            self._restore_preview_camera_ids = config.get('preview_camera_ids', [])
            self.selected_camera_id = config.get('selected_camera_id')
            self._order_custom = bool(config.get('order_custom', False))
            self.next_camera_id = config.get('next_camera_id', 1)

            self.grid_cols_spin.setValue(self.cameras_per_row)
            if hasattr(self, "language_combo"):
                idx = self.language_combo.findData(self.language)
                if idx >= 0:
                    self.language_combo.blockSignals(True)
                    self.language_combo.setCurrentIndex(idx)
                    self.language_combo.blockSignals(False)

            for camera in self.cameras:
                widget = self._get_or_create_camera_widget(camera)
                widget.retranslate_ui()

            self.update_grid_layout()
            self.update_status_display()
            self.retranslate_ui()
            self._restore_preview_state()

            if fixed_config:
                self.save_config()
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
    
    def closeEvent(self, event):
        """Beim Schließen alle Threads sauber beenden"""
        running_threads = [t for t in self.camera_threads.values() if t.isRunning()]
        if not running_threads:
            event.accept()
            return

        if not self._closing:
            self._closing = True
            self._shutdown_started_at = time.monotonic()
            self.save_config()
            for thread in running_threads:
                thread.request_stop()
            self.setEnabled(False)
            self._show_shutdown_dialog()
            QTimer.singleShot(100, self._finish_close_when_streams_stopped)

        event.ignore()

    def _finish_close_when_streams_stopped(self):
        self.camera_threads = {
            camera_id: thread
            for camera_id, thread in self.camera_threads.items()
            if thread.isRunning()
        }
        if self.camera_threads:
            elapsed = time.monotonic() - (self._shutdown_started_at or time.monotonic())
            message = f"Closing app. Please wait...\nStopping camera streams ({elapsed:.1f}s)"
            self.statusBar().showMessage(message.replace("\n", " "))
            if self._shutdown_dialog is not None:
                self._shutdown_dialog.setLabelText(message)
            QTimer.singleShot(100, self._finish_close_when_streams_stopped)
            return

        if self._shutdown_dialog is not None:
            self._shutdown_dialog.close()
            self._shutdown_dialog = None
        self.close()

    def _show_shutdown_dialog(self):
        self.statusBar().showMessage("Closing app. Please wait...")
        dialog = QProgressDialog("Closing app. Please wait...\nStopping camera streams", None, 0, 0, self)
        dialog.setWindowTitle("Closing app")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.show()
        self._shutdown_dialog = dialog

    def select_camera(self, camera_id):
        # If multi-view is active (checkboxes), don't use old single-camera selection
        if len(self.selected_camera_ids) > 0:
            return
        
        self.selected_camera_id = camera_id
        self._sync_big_preview_crop_state(camera_id)

        for cid, widget in self.camera_widgets.items():
            if cid == camera_id:
                widget.set_selected(True)
            else:
                widget.set_selected(False)

        widget = self.camera_widgets.get(camera_id)
        if widget and hasattr(self, 'big_preview_label') and self.big_preview_label is not None:
            try:
                self.big_preview_label.clear_frame_display_rect()
                if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
                    self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.waiting')}")
                else:
                    self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.click_to_start')}")
            except RuntimeError:
                # Label was deleted during multi-view rebuild
                pass

        if camera_id not in self.camera_threads or not self.camera_threads[camera_id].isRunning():
            self.start_single_stream(camera_id)
        else:
            self._refresh_big_preview_from_last_frame(camera_id)
        self.save_config()

    def _restore_preview_state(self):
        restore_ids = [
            cid for cid in getattr(self, "_restore_preview_camera_ids", [])
            if cid in self.camera_widgets
        ]
        if restore_ids:
            self.selected_camera_ids = restore_ids
            self.selected_camera_id = None
            for cid, widget in self.camera_widgets.items():
                checked = cid in restore_ids
                widget.view_checkbox.blockSignals(True)
                widget.view_checkbox.setChecked(checked)
                widget.is_selected_for_view = checked
                widget.view_checkbox.blockSignals(False)
                widget.set_selected(False)
                if checked:
                    widget.video_label.setPixmap(QPixmap())
                    widget.video_label.setText(f"{widget.camera_name}\n{tr('camera.preview.waiting')}")
            self._rebuild_multi_view_layout()
            QTimer.singleShot(300, self._start_restored_preview_streams)
            return

        if self.selected_camera_id in self.camera_widgets:
            camera_id = self.selected_camera_id
            for cid, widget in self.camera_widgets.items():
                widget.set_selected(cid == camera_id)
            widget = self.camera_widgets.get(camera_id)
            if widget and hasattr(self, "big_preview_label"):
                self.big_preview_label.clear_frame_display_rect()
                self.big_preview_label.setText(f"{widget.camera_name}\n{tr('camera.preview.waiting')}")
            QTimer.singleShot(300, lambda cid=camera_id: self.start_single_stream(cid))

    def _start_restored_preview_streams(self):
        for cid in list(self.selected_camera_ids):
            if cid not in self.camera_threads or not self.camera_threads[cid].isRunning():
                self.start_single_stream(cid)

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

    def on_camera_selection_changed(self, camera_id, selected):
        """Handle checkbox selection change for multi-camera view"""
        if selected:
            if camera_id not in self.selected_camera_ids:
                self.selected_camera_ids.append(camera_id)
        else:
            if camera_id in self.selected_camera_ids:
                self.selected_camera_ids.remove(camera_id)

        if self.zoomed_camera_id is not None and self.zoomed_camera_id not in self.selected_camera_ids:
            self.zoomed_camera_id = None

        self._sync_big_preview_crop_state(self._get_active_big_preview_camera_id())
        
        self._rebuild_multi_view_layout()
        self.save_config()
        
        # Start streams for selected cameras
        for cid in self.selected_camera_ids:
            if cid not in self.camera_threads or not self.camera_threads[cid].isRunning():
                self.start_single_stream(cid)

    def _create_multi_view_close_button(self, camera_id, label):
        close_btn = QPushButton()
        close_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        close_btn.setIconSize(QSize(14, 14))
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(220, 53, 69, 220);
                border: 2px solid white;
                border-radius: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 35, 51, 255);
                border: 2px solid #ffcccc;
            }
        """)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(lambda checked, cid=camera_id: self._close_multi_view_camera(cid))
        close_btn.setParent(label)
        close_btn.raise_()
        if not hasattr(self, 'multi_view_close_buttons'):
            self.multi_view_close_buttons = {}
        self.multi_view_close_buttons[camera_id] = close_btn
        label.installEventFilter(self)
        return close_btn
    
    def _rebuild_multi_view_layout(self):
        """Rebuild the big preview layout based on selected cameras"""
        # Clear existing layout
        while self.big_preview_layout.count():
            item = self.big_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        
        self.multi_view_labels.clear()
        if hasattr(self, 'multi_view_close_buttons'):
            self.multi_view_close_buttons.clear()
        
        selected_ids = list(self.selected_camera_ids)
        if self.zoomed_camera_id is not None and self.zoomed_camera_id in selected_ids:
            selected_ids = [self.zoomed_camera_id]

        self._sync_big_preview_crop_state(selected_ids[0] if len(selected_ids) == 1 else None)

        num_selected = len(selected_ids)
        
        if num_selected == 0:
            # No selection - show default message
            label = PreviewLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setText(tr("big.select_camera"))
            label.setStyleSheet("border: 2px solid #555; background-color: black;")
            label.setMinimumHeight(360)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            self._connect_preview_label(label)
            self.big_preview_layout.addWidget(label)
            self.big_preview_label = label
        elif num_selected == 1:
            # Single camera - full view
            camera_id = selected_ids[0]
            label = PreviewLabel(camera_id)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("border: 2px solid #555; background-color: black;")
            label.setMinimumHeight(360)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            self._connect_preview_label(label)
            self.big_preview_layout.addWidget(label)
            self.big_preview_label = label
            self.multi_view_labels[camera_id] = label

            self._create_multi_view_close_button(camera_id, label)
        else:
            # Multi-camera grid view
            # Calculate grid: 2 cameras = 1 row x 2 cols, 3-4 = 2 rows, 5-6 = 3 rows, etc.
            cols = 2
            rows = (num_selected + 1) // 2
            
            for row in range(rows):
                row_layout = QHBoxLayout()
                row_layout.setSpacing(4)
                
                # No left spacer - single camera should be on left side
                
                for col in range(cols):
                    idx = row * cols + col
                    if idx >= num_selected:
                        # Add right spacer to fill remaining space (makes single camera take 1/2 width)
                        spacer = QWidget()
                        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                        row_layout.addWidget(spacer, 1)
                        continue
                    
                    camera_id = selected_ids[idx]
                    
                    # Container for label + close button
                    container = QWidget()
                    container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    container_layout = QVBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.setSpacing(0)
                    
                    # Label for video
                    label = PreviewLabel(camera_id)
                    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    label.setStyleSheet("border: 2px solid #555; background-color: black;")
                    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    label.setMinimumHeight(180)
                    label.setMinimumWidth(0)
                    label.setMaximumWidth(16777215)  # Qt max
                    label.setScaledContents(False)
                    self._connect_preview_label(label)
                    
                    widget = self.camera_widgets.get(camera_id)
                    if widget:
                        label.setText(f"{widget.camera_name}\n{tr('camera.preview.waiting')}")
                    
                    self._create_multi_view_close_button(camera_id, label)
                    
                    container_layout.addWidget(label)
                    row_layout.addWidget(container, 1)
                    self.multi_view_labels[camera_id] = label
                    if self.big_preview_label is None or self._is_qobject_deleted(self.big_preview_label):
                        self.big_preview_label = label
                
                # Set equal stretch for all rows
                self.big_preview_layout.addLayout(row_layout, 1)

        self._update_big_preview_selection_state()

        for camera_id in selected_ids:
            widget = self.camera_widgets.get(camera_id)
            if widget is not None and widget.last_frame is not None:
                self._update_multi_view_frame(widget.last_frame, camera_id)
    
    def eventFilter(self, obj, event):
        """Event filter to reposition close buttons on label resize"""
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            # Check if this is a multi-view label
            for camera_id, label in self.multi_view_labels.items():
                if obj == label and hasattr(self, 'multi_view_close_buttons'):
                    close_btn = self.multi_view_close_buttons.get(camera_id)
                    if close_btn:
                        # Position button at top-right corner
                        close_btn.move(label.width() - close_btn.width() - 4, 4)
                        close_btn.raise_()
        return super().eventFilter(obj, event)
    
    def _close_multi_view_camera(self, camera_id):
        """Close a camera from multi-view and rebuild grid"""
        # Remove from selected list
        if camera_id in self.selected_camera_ids:
            self.selected_camera_ids.remove(camera_id)

        if self.zoomed_camera_id == camera_id:
            self.zoomed_camera_id = None

        self._sync_big_preview_crop_state(self._get_active_big_preview_camera_id())
        
        # Uncheck the checkbox in the camera widget
        widget = self.camera_widgets.get(camera_id)
        if widget and widget.view_checkbox:
            widget.view_checkbox.blockSignals(True)
            widget.view_checkbox.setChecked(False)
            widget.view_checkbox.blockSignals(False)
        
        # Clear close button reference
        if hasattr(self, 'multi_view_close_buttons') and camera_id in self.multi_view_close_buttons:
            del self.multi_view_close_buttons[camera_id]
        
        # Rebuild the multi-view layout
        self._rebuild_multi_view_layout()
        self.save_config()

    def _on_big_preview_label_double_clicked(self, camera_id):
        if self.zoomed_camera_id is None:
            if len(self.selected_camera_ids) > 1 and camera_id in self.selected_camera_ids:
                self.zoomed_camera_id = camera_id
                self._rebuild_multi_view_layout()
                self.save_config()
            return

        active_camera_id = self._get_active_big_preview_camera_id()
        if active_camera_id is None or camera_id != active_camera_id:
            return

        if self.preview_crop_camera_id == camera_id and self.preview_crop_rect is not None:
            self._clear_big_preview_crop()
            self._update_big_preview_selection_state()
            self._refresh_big_preview_from_last_frame(camera_id)
            return

        if self.zoomed_camera_id is not None:
            self.zoomed_camera_id = None
            self._rebuild_multi_view_layout()
            self.save_config()

    def _on_big_preview_region_selected(self, camera_id, selection_rect):
        active_camera_id = self._get_active_big_preview_camera_id()
        if active_camera_id is None or camera_id != active_camera_id:
            return
        if self.preview_crop_rect is not None:
            return

        label = self._get_preview_label_for_camera(camera_id)
        widget = self.camera_widgets.get(camera_id)
        if label is None or widget is None or widget.last_frame is None:
            return

        frame_rect = label.frame_display_rect()
        if frame_rect.isNull():
            return

        selection_rect = selection_rect.intersected(frame_rect)
        if selection_rect.width() < 8 or selection_rect.height() < 8:
            return

        frame_h, frame_w = widget.last_frame.shape[:2]
        rel_x = (selection_rect.x() - frame_rect.x()) / frame_rect.width()
        rel_y = (selection_rect.y() - frame_rect.y()) / frame_rect.height()
        rel_w = selection_rect.width() / frame_rect.width()
        rel_h = selection_rect.height() / frame_rect.height()

        crop_x = int(round(rel_x * frame_w))
        crop_y = int(round(rel_y * frame_h))
        crop_w = int(round(rel_w * frame_w))
        crop_h = int(round(rel_h * frame_h))

        crop_x = max(0, min(frame_w - 1, crop_x))
        crop_y = max(0, min(frame_h - 1, crop_y))
        crop_w = max(24, min(frame_w - crop_x, crop_w))
        crop_h = max(24, min(frame_h - crop_y, crop_h))

        if crop_w <= 0 or crop_h <= 0:
            return

        self.preview_crop_camera_id = camera_id
        self.preview_crop_rect = QRect(crop_x, crop_y, crop_w, crop_h)
        self._update_big_preview_selection_state()
        self._refresh_big_preview_from_last_frame(camera_id)
    
    def _clear_layout(self, layout):
        """Recursively clear a layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _update_big_preview_frame(self, frame):
        label = getattr(self, "big_preview_label", None)
        if label is None or self._is_qobject_deleted(label):
            return

        crop_rect = None
        active_camera_id = self._get_active_big_preview_camera_id()
        if (
            active_camera_id is not None
            and self.preview_crop_camera_id == active_camera_id
            and self.preview_crop_rect is not None
        ):
            crop_rect = self.preview_crop_rect

        self._render_frame_to_label(label, frame, crop_rect=crop_rect)
        self._update_big_preview_selection_state()
    
    def _update_multi_view_frame(self, frame, camera_id):
        """Update frame in multi-camera view with aspect ratio preservation"""
        label = self.multi_view_labels.get(camera_id)
        if not label:
            return

        crop_rect = None
        if self.zoomed_camera_id == camera_id and self.preview_crop_rect is not None:
            if self.preview_crop_camera_id == camera_id:
                crop_rect = self.preview_crop_rect

        self._render_frame_to_label(label, frame, crop_rect=crop_rect)
        label.set_selection_enabled(
            camera_id == self._get_active_big_preview_camera_id()
            and len(self.multi_view_labels) == 1
            and self.preview_crop_rect is None
            and self.preview_crop_camera_id is None
        )



def main():
    # Try to reduce OpenCV logging noise if the function exists in this build
    try:
        cv2.setLogLevel(0)
    except AttributeError:
        # Older Fedora/OpenCV builds may not provide setLogLevel; ignore in that case
        pass
    
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
