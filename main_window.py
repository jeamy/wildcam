import os

os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'
os.environ['AV_LOG_FORCE_NOCOLOR'] = '1'
os.environ['AV_LOG_FORCE_LEVEL'] = '-8'
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|loglevel;quiet'

import cv2
import threading
from PyQt6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
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
from PyQt6.QtCore import QEvent, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPixmap
from datetime import datetime
import time

from camera_utils import (
    _build_rtsp_url,
    _is_battery_camera,
    find_matching_camera,
    is_proxy_stream_url,
    is_reolink_camera,
    normalize_reolinkproxy_camera,
    with_credentials,
)
from config import CONFIG_PATH, DEFAULT_RECORDING_PATH, config_payload, load_config_data, save_config_data, snapshot_path_for
from detection import DEFAULT_DETECTION_CONFIG, DetectionWorker, default_model_dir, prepare_model_path
from dialogs import CameraDiscoveryDialog, CameraEditDialog
from i18n import set_language, tr
from notifications import DEFAULT_EMAIL_CONFIG, send_detection_email
from proxy_status import check_proxy_streams
from netvue import is_netvue_url
from reolinkproxy_manager import ProxyConfigError, generate_proxy_files
from ptz import PtzController, backend_for_camera, camera_has_ptz, detect_ptz, needs_ptz_detection
from stream import CameraThread
from sysstats import NetworkMonitor, format_bytes, process_memory_bytes
from ui_resources import load_svg_icon
from widgets import CameraListContainer, CameraWidget, PreviewLabel, PtzPad, letterbox_rgb, rgb_to_pixmap

try:
    import sip  # type: ignore
except Exception:  # pragma: no cover
    try:
        from PyQt6 import sip  # type: ignore
    except Exception:  # pragma: no cover
        sip = None


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung"""
    email_test_finished = pyqtSignal(bool, str)
    model_test_finished = pyqtSignal(bool, str, str)
    proxy_status_ready = pyqtSignal(int, str)
    ptz_detected = pyqtSignal(int, str, object)  # camera_id, url at detection time, result dict
    ptz_error = pyqtSignal(str)
    PROXY_STATUS_INTERVAL_MS = 60_000

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
        self.event_path = os.path.join(self.recording_path, "events")
        self.detection_config = dict(DEFAULT_DETECTION_CONFIG)
        self.email_config = dict(DEFAULT_EMAIL_CONFIG)
        self.detection_worker = None
        self._model_retry_delays = [30, 120, 300]
        self._model_retry_attempt = 0
        self._model_retry_scheduled = False
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
        self.email_test_finished.connect(self._on_email_test_finished)
        self.model_test_finished.connect(self._on_model_test_finished)
        self.proxy_status_ready.connect(self._on_proxy_status)
        self._proxy_checks_pending = set()
        self.ptz_pad_visible = True
        self._ptz_controllers = {}
        self._ptz_moving_camera_id = None
        self._ptz_detection_pending = set()
        self.ptz_detected.connect(self._on_ptz_detected)
        self.ptz_error.connect(lambda message: self.statusBar().showMessage(message, 5000))
        
        # Erstelle Aufzeichnungsordner
        os.makedirs(self.recording_path, exist_ok=True)
        os.makedirs(self.snapshot_path, exist_ok=True)
        os.makedirs(self.event_path, exist_ok=True)
        
        self.init_ui()
        self.load_config()

        self._proxy_status_timer = QTimer(self)
        self._proxy_status_timer.timeout.connect(self.refresh_proxy_status)
        self._proxy_status_timer.start(self.PROXY_STATUS_INTERVAL_MS)
        QTimer.singleShot(1000, self.refresh_proxy_status)
    
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

        self.proxy_config_btn = QPushButton(tr("btn.proxy_config"))
        self.proxy_config_btn.setToolTip(tr("tooltip.proxy_config"))
        self.proxy_config_btn.clicked.connect(self.generate_proxy_config)
        row2.addWidget(self.proxy_config_btn)

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
        config_tab_layout.addWidget(self._create_detection_config_group())
        config_tab_layout.addWidget(self._create_email_config_group())
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

        # Statistiken: Speicher, Netzwerk, übertragene Daten, FPS der aktiven Kamera
        self._network_monitor = NetworkMonitor()
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("color: #9e9e9e;")
        self.stats_label.setToolTip(tr("tooltip.stats"))
        
        control_layout.addWidget(self.start_all_btn)
        control_layout.addWidget(self.stop_all_btn)
        control_layout.addWidget(self.record_all_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.stats_label)
        control_layout.addSpacing(12)
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
        self.big_preview_label.setStyleSheet(self._preview_label_style())
        self.big_preview_label.setMinimumHeight(360)
        self.big_preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._connect_preview_label(self.big_preview_label)
        self.big_preview_layout.addWidget(self.big_preview_label)

        # Pan/tilt cross overlay (child of the persistent container, the
        # preview labels themselves are recreated on every layout change).
        self.ptz_pad = PtzPad(self.big_preview_container)
        self.ptz_pad.move_requested.connect(self._on_ptz_move)
        self.ptz_pad.stop_requested.connect(self._on_ptz_stop)
        self.ptz_pad.visibility_toggled.connect(self._on_ptz_pad_toggled)
        self.ptz_pad.hide()
        self.big_preview_container.installEventFilter(self)

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
        self.status_timer.start(1000)  # Jede Sekunde (FPS/Netzwerk)

    def _create_detection_config_group(self):
        group = QGroupBox(tr("group.detection_config"))
        self.detection_group = group
        layout = QVBoxLayout()

        row1 = QHBoxLayout()
        self.detection_model_label = QLabel(tr("label.detection_model"))
        self.detection_model_input = QLineEdit(str(self.detection_config.get("model", DEFAULT_DETECTION_CONFIG["model"])))
        self.detection_model_input.setMaximumWidth(180)
        row1.addWidget(self.detection_model_label)
        row1.addWidget(self.detection_model_input)
        self.detection_model_test_btn = QPushButton(tr("btn.model_test"))
        self.detection_model_test_btn.clicked.connect(self.test_detection_model)
        row1.addWidget(self.detection_model_test_btn)

        self.detection_device_label = QLabel(tr("label.detection_device"))
        self.detection_device_combo = QComboBox()
        for label, value in (
            (tr("detection.device.auto"), "auto"),
            (tr("detection.device.cuda"), "cuda:0"),
            (tr("detection.device.cpu"), "cpu"),
        ):
            self.detection_device_combo.addItem(label, value)
        row1.addWidget(self.detection_device_label)
        row1.addWidget(self.detection_device_combo)

        self.detection_imgsz_label = QLabel(tr("label.detection_imgsz"))
        self.detection_imgsz_spin = QSpinBox()
        self.detection_imgsz_spin.setRange(320, 1536)
        self.detection_imgsz_spin.setSingleStep(32)
        self.detection_imgsz_spin.setValue(int(self.detection_config.get("imgsz", 640)))
        row1.addWidget(self.detection_imgsz_label)
        row1.addWidget(self.detection_imgsz_spin)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.detection_conf_label = QLabel(tr("label.detection_conf"))
        self.detection_conf_spin = QDoubleSpinBox()
        self.detection_conf_spin.setRange(0.05, 0.95)
        self.detection_conf_spin.setSingleStep(0.05)
        self.detection_conf_spin.setDecimals(2)
        self.detection_conf_spin.setValue(float(self.detection_config.get("confidence", 0.4)))
        row2.addWidget(self.detection_conf_label)
        row2.addWidget(self.detection_conf_spin)

        self.detection_fps_label = QLabel(tr("label.detection_fps"))
        self.detection_fps_spin = QDoubleSpinBox()
        self.detection_fps_spin.setRange(0.2, 15.0)
        self.detection_fps_spin.setSingleStep(0.5)
        self.detection_fps_spin.setDecimals(1)
        self.detection_fps_spin.setValue(float(self.detection_config.get("analysis_fps_per_camera", 3.0)))
        row2.addWidget(self.detection_fps_label)
        row2.addWidget(self.detection_fps_spin)

        self.detection_cooldown_label = QLabel(tr("label.detection_cooldown"))
        self.detection_cooldown_spin = QSpinBox()
        self.detection_cooldown_spin.setRange(0, 3600)
        self.detection_cooldown_spin.setValue(int(self.detection_config.get("cooldown_seconds", 180)))
        row2.addWidget(self.detection_cooldown_label)
        row2.addWidget(self.detection_cooldown_spin)

        self.detection_suppress_label = QLabel(tr("label.detection_suppress"))
        self.detection_suppress_spin = QSpinBox()
        self.detection_suppress_spin.setRange(0, 600)
        self.detection_suppress_spin.setValue(int(self.detection_config.get("event_suppress_seconds", 30)))
        row2.addWidget(self.detection_suppress_label)
        row2.addWidget(self.detection_suppress_spin)

        self.detection_clip_label = QLabel(tr("label.detection_clip"))
        self.detection_clip_spin = QSpinBox()
        self.detection_clip_spin.setRange(1, 180)
        self.detection_clip_spin.setValue(int(self.detection_config.get("event_clip_seconds", 30)))
        row2.addWidget(self.detection_clip_label)
        row2.addWidget(self.detection_clip_spin)
        row2.addStretch()
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.detection_classes_label = QLabel(tr("label.detection_classes"))
        self.detection_classes_input = QLineEdit(", ".join(self.detection_config.get("classes", [])))
        row3.addWidget(self.detection_classes_label)
        row3.addWidget(self.detection_classes_input)
        layout.addLayout(row3)

        row4 = QHBoxLayout()
        self.detection_motion_classes_label = QLabel(tr("label.detection_motion_classes"))
        self.detection_motion_classes_input = QLineEdit(", ".join(self.detection_config.get("motion_required_classes", [])))
        row4.addWidget(self.detection_motion_classes_label)
        row4.addWidget(self.detection_motion_classes_input)

        self.detection_motion_pixels_label = QLabel(tr("label.detection_motion_pixels"))
        self.detection_motion_pixels_spin = QDoubleSpinBox()
        self.detection_motion_pixels_spin.setRange(0.0, 200.0)
        self.detection_motion_pixels_spin.setSingleStep(1.0)
        self.detection_motion_pixels_spin.setDecimals(1)
        self.detection_motion_pixels_spin.setValue(float(self.detection_config.get("motion_min_pixels", 12.0)))
        row4.addWidget(self.detection_motion_pixels_label)
        row4.addWidget(self.detection_motion_pixels_spin)
        layout.addLayout(row4)

        group.setLayout(layout)
        for widget in (
            self.detection_model_input,
            self.detection_device_combo,
            self.detection_imgsz_spin,
            self.detection_conf_spin,
            self.detection_fps_spin,
            self.detection_cooldown_spin,
            self.detection_suppress_spin,
            self.detection_clip_spin,
            self.detection_classes_input,
            self.detection_motion_classes_input,
            self.detection_motion_pixels_spin,
        ):
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._save_detection_config_from_ui)
            else:
                widget.valueChanged.connect(self._save_detection_config_from_ui) if hasattr(widget, "valueChanged") else widget.currentIndexChanged.connect(self._save_detection_config_from_ui)
        return group

    def _create_email_config_group(self):
        group = QGroupBox(tr("group.email_config"))
        self.email_group = group
        layout = QVBoxLayout()

        row1 = QHBoxLayout()
        self.email_enabled_check = QCheckBox(tr("label.email_enabled"))
        self.email_enabled_check.setChecked(bool(self.email_config.get("enabled", False)))
        row1.addWidget(self.email_enabled_check)
        self.email_host_label = QLabel(tr("label.smtp_host"))
        self.email_host_input = QLineEdit(str(self.email_config.get("smtp_host", "")))
        row1.addWidget(self.email_host_label)
        row1.addWidget(self.email_host_input)
        self.email_port_label = QLabel(tr("label.smtp_port"))
        self.email_port_spin = QSpinBox()
        self.email_port_spin.setRange(1, 65535)
        self.email_port_spin.setValue(int(self.email_config.get("smtp_port", 587)))
        row1.addWidget(self.email_port_label)
        row1.addWidget(self.email_port_spin)
        self.email_tls_check = QCheckBox(tr("label.smtp_tls"))
        self.email_tls_check.setChecked(bool(self.email_config.get("use_tls", True)))
        row1.addWidget(self.email_tls_check)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.email_user_label = QLabel(tr("label.smtp_username"))
        self.email_user_input = QLineEdit(str(self.email_config.get("smtp_username", "")))
        row2.addWidget(self.email_user_label)
        row2.addWidget(self.email_user_input)
        self.email_password_label = QLabel(tr("label.smtp_password"))
        self.email_password_input = QLineEdit(str(self.email_config.get("smtp_password", "")))
        self.email_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        row2.addWidget(self.email_password_label)
        row2.addWidget(self.email_password_input)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.email_from_label = QLabel(tr("label.email_from"))
        self.email_from_input = QLineEdit(str(self.email_config.get("from", "")))
        row3.addWidget(self.email_from_label)
        row3.addWidget(self.email_from_input)
        self.email_to_label = QLabel(tr("label.email_to"))
        to_value = self.email_config.get("to", [])
        if isinstance(to_value, list):
            to_value = ", ".join(to_value)
        self.email_to_input = QLineEdit(str(to_value))
        row3.addWidget(self.email_to_label)
        row3.addWidget(self.email_to_input)
        self.email_test_btn = QPushButton(tr("btn.email_test"))
        self.email_test_btn.clicked.connect(self.send_test_email)
        row3.addWidget(self.email_test_btn)
        layout.addLayout(row3)

        group.setLayout(layout)
        for widget in (
            self.email_enabled_check,
            self.email_tls_check,
            self.email_host_input,
            self.email_port_spin,
            self.email_user_input,
            self.email_password_input,
            self.email_from_input,
            self.email_to_input,
        ):
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._save_email_config_from_ui)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._save_email_config_from_ui)
            else:
                widget.valueChanged.connect(self._save_email_config_from_ui)
        return group

    def _is_qobject_deleted(self, obj) -> bool:
        if obj is None:
            return True
        if sip is None:
            return False
        try:
            return bool(sip.isdeleted(obj))
        except Exception:
            return False

    def _save_detection_config_from_ui(self):
        if not hasattr(self, "detection_model_input"):
            return
        classes = [
            item.strip()
            for item in self.detection_classes_input.text().split(",")
            if item.strip()
        ]
        motion_classes = [
            item.strip()
            for item in self.detection_motion_classes_input.text().split(",")
            if item.strip()
        ]
        self.detection_config.update({
            "model": self.detection_model_input.text().strip() or DEFAULT_DETECTION_CONFIG["model"],
            "device": self.detection_device_combo.currentData() or "auto",
            "imgsz": int(self.detection_imgsz_spin.value()),
            "confidence": float(self.detection_conf_spin.value()),
            "analysis_fps_per_camera": float(self.detection_fps_spin.value()),
            "cooldown_seconds": int(self.detection_cooldown_spin.value()),
            "event_suppress_seconds": int(self.detection_suppress_spin.value()),
            "event_clip_seconds": int(self.detection_clip_spin.value()),
            "classes": classes,
            "motion_required_classes": motion_classes,
            "motion_min_pixels": float(self.detection_motion_pixels_spin.value()),
            "recording_path": self.recording_path,
            "model_dir": str(default_model_dir(self.recording_path)),
        })
        self._apply_prebuffer()
        self.save_config()

    def _save_email_config_from_ui(self):
        if not hasattr(self, "email_enabled_check"):
            return
        recipients = [
            item.strip()
            for item in self.email_to_input.text().split(",")
            if item.strip()
        ]
        self.email_config.update({
            "enabled": bool(self.email_enabled_check.isChecked()),
            "smtp_host": self.email_host_input.text().strip(),
            "smtp_port": int(self.email_port_spin.value()),
            "smtp_username": self.email_user_input.text().strip(),
            "smtp_password": self.email_password_input.text(),
            "use_tls": bool(self.email_tls_check.isChecked()),
            "from": self.email_from_input.text().strip(),
            "to": recipients,
        })
        self.save_config()

    def _sync_detection_config_ui(self):
        if not hasattr(self, "detection_model_input"):
            return
        widgets = [
            self.detection_model_input,
            self.detection_device_combo,
            self.detection_imgsz_spin,
            self.detection_conf_spin,
            self.detection_fps_spin,
            self.detection_cooldown_spin,
            self.detection_suppress_spin,
            self.detection_clip_spin,
            self.detection_classes_input,
            self.detection_motion_classes_input,
            self.detection_motion_pixels_spin,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.detection_model_input.setText(str(self.detection_config.get("model", DEFAULT_DETECTION_CONFIG["model"])))
            idx = self.detection_device_combo.findData(str(self.detection_config.get("device", "auto")))
            if idx >= 0:
                self.detection_device_combo.setCurrentIndex(idx)
            self.detection_imgsz_spin.setValue(int(self.detection_config.get("imgsz", 640)))
            self.detection_conf_spin.setValue(float(self.detection_config.get("confidence", 0.4)))
            self.detection_fps_spin.setValue(float(self.detection_config.get("analysis_fps_per_camera", 3.0)))
            self.detection_cooldown_spin.setValue(int(self.detection_config.get("cooldown_seconds", 180)))
            self.detection_suppress_spin.setValue(int(self.detection_config.get("event_suppress_seconds", 30)))
            self.detection_clip_spin.setValue(int(self.detection_config.get("event_clip_seconds", 30)))
            self.detection_classes_input.setText(", ".join(self.detection_config.get("classes", [])))
            self.detection_motion_classes_input.setText(", ".join(self.detection_config.get("motion_required_classes", [])))
            self.detection_motion_pixels_spin.setValue(float(self.detection_config.get("motion_min_pixels", 12.0)))
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _sync_email_config_ui(self):
        if not hasattr(self, "email_enabled_check"):
            return
        widgets = [
            self.email_enabled_check,
            self.email_host_input,
            self.email_port_spin,
            self.email_tls_check,
            self.email_user_input,
            self.email_password_input,
            self.email_from_input,
            self.email_to_input,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.email_enabled_check.setChecked(bool(self.email_config.get("enabled", False)))
            self.email_host_input.setText(str(self.email_config.get("smtp_host", "")))
            self.email_port_spin.setValue(int(self.email_config.get("smtp_port", 587)))
            self.email_tls_check.setChecked(bool(self.email_config.get("use_tls", True)))
            self.email_user_input.setText(str(self.email_config.get("smtp_username", "")))
            self.email_password_input.setText(str(self.email_config.get("smtp_password", "")))
            self.email_from_input.setText(str(self.email_config.get("from", "")))
            to_value = self.email_config.get("to", [])
            if isinstance(to_value, list):
                to_value = ", ".join(to_value)
            self.email_to_input.setText(str(to_value))
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _runtime_detection_config(self):
        config = dict(self.detection_config)
        config["recording_path"] = self.recording_path
        config["model_dir"] = str(default_model_dir(self.recording_path))
        return config

    def test_detection_model(self):
        self._save_detection_config_from_ui()
        if hasattr(self, "detection_model_test_btn"):
            self.detection_model_test_btn.setEnabled(False)
        self.statusBar().showMessage(tr("status.model_test_running"))

        model_name = str(self.detection_config.get("model", DEFAULT_DETECTION_CONFIG["model"]))
        model_dir = default_model_dir(self.recording_path)

        def run():
            try:
                model_path = prepare_model_path(model_name, model_dir)
                self.model_test_finished.emit(
                    True,
                    tr("status.model_test_ok", path=model_path),
                    str(model_path),
                )
            except Exception as exc:
                self.model_test_finished.emit(
                    False,
                    tr("status.model_test_failed", error=exc),
                    "",
                )

        threading.Thread(target=run, daemon=True).start()

    def _on_model_test_finished(self, ok: bool, message: str, model_path: str):
        if hasattr(self, "detection_model_test_btn"):
            self.detection_model_test_btn.setEnabled(True)
        if ok and model_path:
            self.detection_config["model"] = model_path
            if hasattr(self, "detection_model_input"):
                self.detection_model_input.setText(model_path)
            self.save_config()
        self.statusBar().showMessage(message)

    def send_test_email(self):
        self._save_email_config_from_ui()
        if hasattr(self, "email_test_btn"):
            self.email_test_btn.setEnabled(False)
        self.statusBar().showMessage(tr("status.email_test_sending"))

        config = dict(self.email_config)
        subject = tr("email.test.subject")
        body = tr("email.test.body")

        def send():
            try:
                send_detection_email(config, subject, body, require_enabled=False)
                self.email_test_finished.emit(True, tr("status.email_test_sent"))
            except Exception as exc:
                self.email_test_finished.emit(False, tr("status.email_test_failed", error=exc))

        threading.Thread(target=send, daemon=True).start()

    def _on_email_test_finished(self, ok: bool, message: str):
        if hasattr(self, "email_test_btn"):
            self.email_test_btn.setEnabled(True)
        self.statusBar().showMessage(message)

    def _connect_preview_label(self, label: PreviewLabel):
        label.double_clicked.connect(self._on_big_preview_label_double_clicked)
        label.region_selected.connect(self._on_big_preview_region_selected)

    def _detection_worker_is_running(self) -> bool:
        return bool(self.detection_worker is not None and self.detection_worker.isRunning())

    def _camera_detection_enabled(self, camera_id) -> bool:
        camera = self._camera_by_id(camera_id)
        return bool(camera and camera.get("detection_enabled", False))

    def _any_camera_detection_enabled(self) -> bool:
        return any(bool(camera.get("detection_enabled", False)) for camera in self.cameras)

    def _preview_label_style(self, camera_id=None):
        border_color = "#2196f3" if camera_id is not None and self._camera_detection_enabled(camera_id) else "#555"
        return f"border: 2px solid {border_color}; background-color: black;"

    def _apply_detection_visual_state(self):
        for widget in self.camera_widgets.values():
            try:
                widget.set_detection_active(self._camera_detection_enabled(widget.camera_id))
            except RuntimeError:
                continue
        labels = []
        label = getattr(self, "big_preview_label", None)
        if label is not None and not self._is_qobject_deleted(label):
            labels.append(label)
        for label in self.multi_view_labels.values():
            if label is not None and not self._is_qobject_deleted(label):
                labels.append(label)
        for label in labels:
            try:
                camera_id = getattr(label, "camera_id", None)
                if camera_id is None:
                    camera_id = self._get_active_big_preview_camera_id()
                label.setStyleSheet(self._preview_label_style(camera_id))
            except RuntimeError:
                pass

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
        rgb_frame, content_rect = letterbox_rgb(frame, label.width(), label.height(), crop_rect)
        if rgb_frame is None:
            label.clear_frame_display_rect()
            return
        label.setPixmap(rgb_to_pixmap(rgb_frame))
        label.set_frame_display_rect(content_rect)

    def _get_or_create_camera_widget(self, camera: dict) -> CameraWidget:
        camera_id = int(camera.get('id'))
        camera_name = camera.get('name', tr("camera.default_name.id", id=camera_id))

        existing = self.camera_widgets.get(camera_id)
        if existing is not None and not self._is_qobject_deleted(existing):
            return existing

        widget = CameraWidget(camera_id, camera_name, is_battery=self._is_battery_entry(camera))
        widget.remove_btn.clicked.connect(lambda checked, cid=camera_id: self.remove_camera(cid))
        widget.edit_btn.clicked.connect(lambda checked, cid=camera_id: self.edit_camera(cid))
        widget.stream_toggled.connect(self.toggle_camera_stream)
        widget.clicked.connect(self.select_camera)
        widget.snapshot_requested.connect(self.save_camera_snapshot)
        widget.selection_changed.connect(self.on_camera_selection_changed)
        widget.detection_toggled.connect(self.toggle_camera_detection)
        widget.record_btn.clicked.connect(lambda checked, cid=camera_id, w=widget: self._on_record_btn_clicked(cid, w, checked))
        widget.set_detection_active(self._camera_detection_enabled(camera_id))
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
        ports = camera_info.get('ports', [])
        is_reolink = (camera_info.get('manufacturer') or '').lower() == 'reolink'
        if is_netvue_url(camera_info.get('stream_uri', '')):
            # No credentials from the scan dialog: Netvue needs the app's local key.
            url = camera_info['stream_uri']
        elif camera_info.get('stream_uri'):
            # Exact RTSP URL reported by the camera via ONVIF GetStreamUri.
            url = with_credentials(camera_info['stream_uri'], username, password)
        else:
            if 554 in ports:
                port = 554
            elif 8554 in ports:
                port = 8554
            elif is_reolink and 9000 in ports:
                # Battery/WLAN Reolink without RTSP -> normalized to ReolinkProxy below.
                port = 9000
            else:
                port = 554
            url = _build_rtsp_url(
                host=camera_info['ip'],
                port=port,
                username=username,
                password=password,
                path="h264Preview_01_main" if is_reolink else "",
            )
        camera_entry = {
            'id': self._allocate_camera_id(),
            'url': url,
            'name': camera_info['name'],
            'uid': camera_info.get('uid', ''),
            'model': camera_info.get('model', ''),
            'manufacturer': camera_info.get('manufacturer', ''),
            'detection_enabled': False,
        }
        if camera_info.get('mac'):
            camera_entry['mac'] = camera_info['mac']
        normalize_reolinkproxy_camera(camera_entry, username=username, password=password)
        return camera_entry

    def _build_manual_camera_entry(self, url: str, name: str, uid: str) -> dict:
        camera_id = self._allocate_camera_id()
        camera_entry = {
            'id': camera_id,
            'url': url,
            'name': name if name else tr("camera.default_name.id", id=camera_id),
            'uid': uid,
            'model': '',
            'detection_enabled': False,
        }
        normalize_reolinkproxy_camera(camera_entry)
        return camera_entry

    def _normalize_edited_camera_data(self, camera_data: dict, updated_data: dict) -> dict:
        normalized = dict(updated_data)
        normalized.setdefault('model', camera_data.get('model', ''))
        normalized.setdefault('manufacturer', camera_data.get('manufacturer', ''))
        normalize_reolinkproxy_camera(normalized)
        return normalized

    def _camera_by_id(self, camera_id) -> dict | None:
        try:
            camera_id = int(camera_id)
        except (TypeError, ValueError):
            return None
        return next((c for c in self.cameras if int(c.get('id', -1)) == camera_id), None)

    def _stop_camera_thread(self, camera_id, timeout_ms: int = 3000) -> bool:
        """Stop and forget a camera thread. False if it is still shutting down."""
        thread = self.camera_threads.get(camera_id)
        if thread is None:
            return True
        if not thread.stop(timeout_ms=timeout_ms):
            return False
        del self.camera_threads[camera_id]
        return True

    def _event_clip_timing(self) -> tuple[float, float, float]:
        """(clip, pre, post) seconds for detection event clips."""
        clip_seconds = min(180.0, max(1.0, float(self.detection_config.get("event_clip_seconds", 30))))
        pre_seconds = min(clip_seconds - 1.0, max(0.0, float(self.detection_config.get("pre_event_seconds", 8))))
        return clip_seconds, pre_seconds, max(1.0, clip_seconds - pre_seconds)

    def _prebuffer_seconds(self, camera_id) -> float:
        """Pre-event buffer only for cameras with detection enabled."""
        if not self._camera_detection_enabled(camera_id):
            return 0.0
        _clip, pre_seconds, _post = self._event_clip_timing()
        return pre_seconds + 1.0 if pre_seconds > 0 else 0.0

    def _apply_prebuffer(self, camera_id=None):
        camera_ids = [camera_id] if camera_id is not None else list(self.camera_threads)
        for cid in camera_ids:
            thread = self.camera_threads.get(cid)
            if thread is not None:
                thread.set_prebuffer_seconds(self._prebuffer_seconds(cid))

    def _stream_running(self, camera_id) -> bool:
        thread = self.camera_threads.get(camera_id)
        return thread is not None and thread.isRunning()

    def refresh_proxy_status(self):
        """Ask ReolinkProxy (RTSP DESCRIBE) about every idle proxy camera."""
        if self._closing:
            return
        targets = [
            (camera['id'], camera['url'])
            for camera in self.cameras
            if is_proxy_stream_url(camera.get('url', ''))
            and not self._stream_running(camera['id'])
            and camera['id'] not in self._proxy_checks_pending
        ]
        if not targets:
            return
        self._proxy_checks_pending.update(camera_id for camera_id, _url in targets)
        check_proxy_streams(targets, self.proxy_status_ready.emit)

    def _on_proxy_status(self, camera_id: int, status: str):
        self._proxy_checks_pending.discard(camera_id)
        widget = self.camera_widgets.get(camera_id)
        if widget is None or self._is_qobject_deleted(widget):
            return
        widget.set_proxy_status(status)

    # ------------------------------------------------------------------
    # PTZ (pan/tilt)
    # ------------------------------------------------------------------

    def detect_missing_ptz(self, camera_ids=None):
        """Detect pan/tilt support in the background for cameras without a stored value."""
        for camera in list(self.cameras):
            camera_id = camera['id']
            if camera_ids is not None and camera_id not in camera_ids:
                continue
            if not needs_ptz_detection(camera) or camera_id in self._ptz_detection_pending:
                continue
            self._ptz_detection_pending.add(camera_id)
            snapshot = dict(camera)

            def worker(cam=snapshot):
                try:
                    result = detect_ptz(cam)
                except Exception:
                    result = None
                try:
                    self.ptz_detected.emit(int(cam['id']), cam.get('url', ''), result)
                except (RuntimeError, AttributeError):
                    pass

            threading.Thread(target=worker, daemon=True).start()

    def _on_ptz_detected(self, camera_id: int, url: str, result):
        self._ptz_detection_pending.discard(camera_id)
        camera = self._camera_by_id(camera_id)
        if not result or camera is None or camera.get('url') != url or camera.get('ptz_manual'):
            return
        camera.update(result)
        self._drop_ptz_controller(camera_id)
        self.save_config()
        self._update_ptz_pad()

    def _reset_ptz_detection(self, camera: dict):
        for key in ('ptz', 'ptz_backend', 'onvif_url', 'ptz_manual'):
            camera.pop(key, None)

    def _drop_ptz_controller(self, camera_id):
        controller = self._ptz_controllers.pop(camera_id, None)
        if controller is not None:
            controller.close()

    def _ptz_controller(self, camera_id):
        controller = self._ptz_controllers.get(camera_id)
        if controller is None:
            camera = self._camera_by_id(camera_id)
            if camera is None:
                return None
            name = camera.get('name', str(camera_id))

            def on_error(message, name=name):
                try:
                    self.ptz_error.emit(tr("ptz.error", name=name, error=message))
                except (RuntimeError, AttributeError):
                    pass

            controller = PtzController(backend_for_camera(camera), on_error)
            self._ptz_controllers[camera_id] = controller
        return controller

    def _active_ptz_camera_id(self):
        camera_id = self._get_active_big_preview_camera_id()
        camera = self._camera_by_id(camera_id) if camera_id is not None else None
        if camera is None or not camera_has_ptz(camera):
            return None
        return camera['id']

    def _on_ptz_move(self, direction: str):
        camera_id = self._active_ptz_camera_id()
        if camera_id is None:
            return
        controller = self._ptz_controller(camera_id)
        if controller is not None:
            self._ptz_moving_camera_id = camera_id
            controller.move(direction)

    def _on_ptz_stop(self):
        camera_id = self._ptz_moving_camera_id or self._active_ptz_camera_id()
        self._ptz_moving_camera_id = None
        if camera_id is None:
            return
        controller = self._ptz_controller(camera_id)
        if controller is not None:
            controller.stop()

    def _on_ptz_pad_toggled(self, expanded: bool):
        self.ptz_pad_visible = bool(expanded)
        if not expanded and self._ptz_moving_camera_id is not None:
            self._on_ptz_stop()
        self._position_ptz_pad()
        self.save_config()

    def _update_ptz_pad(self):
        pad = getattr(self, "ptz_pad", None)
        if pad is None:
            return
        active = self._active_ptz_camera_id()
        if self._ptz_moving_camera_id is not None and self._ptz_moving_camera_id != active:
            self._on_ptz_stop()
        if active is None:
            pad.hide()
            return
        pad.set_expanded(self.ptz_pad_visible)
        pad.show()
        self._position_ptz_pad()

    def _position_ptz_pad(self):
        pad = getattr(self, "ptz_pad", None)
        container = getattr(self, "big_preview_container", None)
        if pad is None or container is None or not pad.isVisible():
            return
        pad.adjustSize()
        margin = 12
        pad.move(max(0, container.width() - pad.width() - margin), max(0, container.height() - pad.height() - margin))
        pad.raise_()

    def _start_camera_thread(self, camera: dict) -> CameraThread:
        camera_id = camera['id']
        thread = CameraThread(
            camera_id,
            camera['url'],
            camera.get('uid', ''),
            is_reolink=is_reolink_camera(camera),
            prebuffer_seconds=self._prebuffer_seconds(camera_id),
        )
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
        dialog = CameraDiscoveryDialog(self.cameras, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_cameras = dialog.get_selected_cameras()
        if not selected_cameras:
            return

        # Zugangsdaten aus Dialog
        username = dialog.username_input.text()
        password = dialog.password_input.text()

        added = []
        for camera_info in selected_cameras:
            if find_matching_camera(camera_info, self.cameras) is not None:
                continue
            camera_entry = self._build_discovered_camera_entry(camera_info, username, password)
            if any(c['url'] == camera_entry['url'] for c in self.cameras):
                continue
            self._add_camera_entry(camera_entry)
            added.append(camera_entry)

        if not added:
            return

        self.update_grid_layout()
        self.update_status_display()
        self.save_config()

        proxied = [c for c in added if c.get('proxy')]
        netvue_cameras = [c for c in added if is_netvue_url(c.get('url', ''))]
        message = tr("status.auto_added", count=len(added))
        if proxied:
            message += " " + tr("dialog.discovery.proxy_hint", count=len(proxied))
        self.statusBar().showMessage(message)
        self.refresh_proxy_status()
        self.detect_missing_ptz([c['id'] for c in added])

        if netvue_cameras:
            QMessageBox.information(
                self,
                tr("netvue.key_needed.title"),
                tr("netvue.key_needed.message",
                   cameras="\n".join(f"• {c['name']}" for c in netvue_cameras)),
            )

        battery_cameras = [c for c in added if self._is_battery_entry(c)]
        if battery_cameras:
            cam_list = "\n".join(f"• {c['name']} ({c.get('model') or '-'})" for c in battery_cameras)
            QMessageBox.warning(
                self,
                tr("battery.warning.title"),
                tr("battery.warning.multi", count=len(battery_cameras), cameras=cam_list),
            )

    @staticmethod
    def _is_battery_entry(camera: dict) -> bool:
        proxy = camera.get('proxy') or {}
        if proxy.get('type') == 'reolinkproxy' and proxy.get('battery'):
            return True
        return _is_battery_camera(camera.get('model', ''), camera.get('name', ''))

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
        self.detect_missing_ptz([camera_entry['id']])
    
    def edit_camera(self, camera_id):
        """Kamera bearbeiten"""
        # Kamera-Daten finden
        camera_data = self._camera_by_id(camera_id)
        if not camera_data:
            return
        
        # Stream stoppen falls aktiv
        was_running = self._stream_running(camera_id)
        if was_running and not self._stop_camera_thread(camera_id):
            QMessageBox.warning(self, tr("dialog.title.error"), tr("camera.status.still_stopping"))
            return
        
        # Edit Dialog öffnen
        dialog = CameraEditDialog(camera_data, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = self._normalize_edited_camera_data(camera_data, dialog.get_camera_data())
            
            # Daten aktualisieren
            url_changed = updated_data.get('url') != camera_data.get('url')
            camera_data.update(updated_data)
            if url_changed and not camera_data.get('ptz_manual'):
                self._reset_ptz_detection(camera_data)
            self._drop_ptz_controller(camera_id)
            
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
            self._update_ptz_pad()
            self.detect_missing_ptz([camera_id])
            
            # Stream neu starten falls vorher aktiv
            if was_running:
                QTimer.singleShot(500, lambda: self.start_single_stream(camera_id))
        else:
            # Bei Abbruch: Stream wieder starten falls vorher aktiv
            if was_running:
                QTimer.singleShot(500, lambda: self.start_single_stream(camera_id))
    
    def start_single_stream(self, camera_id):
        """Einzelnen Stream starten"""
        camera = self._camera_by_id(camera_id)
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
        if not self._stop_camera_thread(camera_id):
            self.statusBar().showMessage(tr("camera.status.still_stopping"))
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
        camera = self._camera_by_id(camera_id)
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
        if not self._stop_camera_thread(camera_id):
            QMessageBox.warning(self, tr("dialog.title.error"), tr("camera.status.still_stopping"))
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
        self._drop_ptz_controller(camera_id)
        self.cameras = [c for c in self.cameras if c['id'] != camera_id]
        self._update_ptz_pad()
        if not self._any_camera_detection_enabled():
            self.stop_detection()
        
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
            for camera_id in list(self._ptz_controllers):
                self._drop_ptz_controller(camera_id)
            self.cameras.clear()
            self.next_camera_id = 1
            self.selected_camera_id = None
            self.selected_camera_ids = []
            self.zoomed_camera_id = None
            self._clear_big_preview_crop()
            self._clear_big_preview_label(tr("big.select_camera"))
            self._update_ptz_pad()
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
            self.statusBar().showMessage(tr("status.streams_still_stopping"))
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

        if self._detection_worker_is_running() and self._camera_detection_enabled(camera_id):
            camera_name = widget.camera_name if widget is not None else str(camera_id)
            self.detection_worker.submit_frame(camera_id, camera_name, frame)

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
        self._update_stats_label()

    def _update_stats_label(self):
        label = getattr(self, "stats_label", None)
        if label is None:
            return
        recv_rate, sent_rate = self._network_monitor.update()
        received = self._network_monitor.total_received

        fps_text = "–"
        camera_id = self._get_active_big_preview_camera_id()
        thread = self.camera_threads.get(camera_id) if camera_id is not None else None
        if thread is not None and thread.isRunning():
            fps_text = f"{thread.measured_fps:.1f}"
        else:
            running = [t for t in self.camera_threads.values() if t.isRunning()]
            if running:
                fps_text = "Σ " + f"{sum(t.measured_fps for t in running):.0f}"

        label.setText(tr(
            "label.stats",
            mem=format_bytes(process_memory_bytes()),
            down=format_bytes(recv_rate, per_second=True),
            up=format_bytes(sent_rate, per_second=True),
            total=format_bytes(received),
            fps=fps_text,
        ))
    
    def select_recording_path(self):
        """Speicherort für Aufnahmen wählen"""
        path = QFileDialog.getExistingDirectory(self, tr("dialog.path.choose"), self.recording_path)
        if path:
            self.recording_path = path
            self.snapshot_path = snapshot_path_for(self.recording_path)
            self.event_path = os.path.join(self.recording_path, "events")
            os.makedirs(self.snapshot_path, exist_ok=True)
            os.makedirs(self.event_path, exist_ok=True)
            self.save_config()
            self.statusBar().showMessage(tr("status.path", path=path))

    def generate_proxy_config(self):
        """reolinkproxy.env (und docker-compose.yml) neben camera_config.json schreiben."""
        self.save_config()
        target_dir = os.path.dirname(os.path.abspath(CONFIG_PATH))
        cameras = config_payload(self).get("cameras", [])
        try:
            env_path, _compose_path, names = generate_proxy_files(cameras, target_dir)
        except ProxyConfigError as e:
            if e.reason == "incomplete":
                message = tr("dialog.proxy_config.incomplete", cameras=", ".join(e.cameras))
            else:
                message = tr("dialog.proxy_config.none")
            QMessageBox.warning(self, tr("dialog.proxy_config.title"), message)
            return
        except OSError as e:
            QMessageBox.critical(self, tr("dialog.proxy_config.title"),
                                 tr("dialog.proxy_config.failed", error=e))
            return

        QMessageBox.information(
            self,
            tr("dialog.proxy_config.title"),
            tr(
                "dialog.proxy_config.done",
                count=len(names),
                cameras="\n".join(f"• {name}" for name in names),
                path=str(env_path),
                dir=target_dir,
            ),
        )
        self.statusBar().showMessage(tr("status.proxy_config_written", path=str(env_path)))
        QTimer.singleShot(1000, self.refresh_proxy_status)

    def toggle_camera_detection(self, camera_id: int, enabled: bool):
        camera = self._camera_by_id(camera_id)
        if camera is None:
            return
        camera["detection_enabled"] = bool(enabled)
        self._apply_prebuffer(camera_id)
        widget = self.camera_widgets.get(camera_id)
        if widget is not None:
            widget.set_detection_active(enabled)

        if enabled:
            self._model_retry_attempt = 0
            self._model_retry_scheduled = False
            self._ensure_detection_worker()
            if camera_id not in self.camera_threads or not self.camera_threads[camera_id].isRunning():
                self.start_single_stream(camera_id)
        elif not self._any_camera_detection_enabled():
            self.stop_detection()
        self._apply_detection_visual_state()
        self.save_config()

    def _ensure_detection_worker(self):
        if self._detection_worker_is_running():
            return
        self.detection_worker = DetectionWorker(self._runtime_detection_config(), self)
        self.detection_worker.detected.connect(self.handle_detection_event)
        self.detection_worker.status.connect(self._on_detection_status)
        self.detection_worker.start()

    def stop_detection(self):
        worker = self.detection_worker
        self.detection_worker = None
        if worker is not None:
            worker.stop(timeout_ms=3000)
        self._apply_detection_visual_state()
        self.save_config()
        self.statusBar().showMessage(tr("status.detection_stopped"))

    def _on_detection_status(self, message: str):
        if "deaktiviert" in message or "disabled" in message or "Modell-Laden fehlgeschlagen" in message:
            self.detection_worker = None
            self._schedule_detection_retry()
            self._apply_detection_visual_state()
            self.save_config()
            return
        elif "aktiv" in message or "active" in message:
            self._model_retry_attempt = 0
            self._model_retry_scheduled = False
        self.statusBar().showMessage(message)

    def _schedule_detection_retry(self):
        if not self._any_camera_detection_enabled():
            return
        if self._model_retry_scheduled:
            return
        delay = self._model_retry_delays[min(self._model_retry_attempt, len(self._model_retry_delays) - 1)]
        self._model_retry_attempt += 1
        self._model_retry_scheduled = True
        self.statusBar().showMessage(tr("status.model_retry_scheduled", seconds=delay))
        QTimer.singleShot(delay * 1000, self._retry_detection_worker)

    def _retry_detection_worker(self):
        self._model_retry_scheduled = False
        if not self._any_camera_detection_enabled():
            return
        if self._detection_worker_is_running():
            return
        self._ensure_detection_worker()

    def handle_detection_event(self, event):
        os.makedirs(self.snapshot_path, exist_ok=True)
        os.makedirs(self.event_path, exist_ok=True)
        timestamp = datetime.fromtimestamp(event.timestamp).strftime("%Y%m%d_%H%M%S")
        safe_camera = "".join(c if (c.isalnum() or c in "-_") else "_" for c in event.camera_name)
        safe_label = "".join(c if (c.isalnum() or c in "-_") else "_" for c in event.label)
        snapshot_file = os.path.join(
            self.snapshot_path,
            f"detect_{safe_camera}_{event.camera_id}_{safe_label}_{timestamp}.jpg",
        )

        try:
            cv2.imwrite(snapshot_file, event.annotated_frame)
        except Exception as exc:
            self.statusBar().showMessage(tr("status.snapshot_error", error=exc))
            return

        clip_file = None
        thread = self.camera_threads.get(event.camera_id)
        if thread is not None:
            clip_seconds, pre_seconds, post_seconds = self._event_clip_timing()
            clip_file = thread.start_event_clip(
                self.event_path,
                event.label,
                camera_name=event.camera_name,
                pre_seconds=pre_seconds,
                post_seconds=post_seconds,
                max_seconds=clip_seconds,
            )

        self.statusBar().showMessage(
            tr(
                "status.detection_event",
                label=event.label,
                camera=event.camera_name,
                confidence=f"{event.confidence:.2f}",
            )
        )
        self._send_detection_email_async(event, snapshot_file, clip_file)

    def _send_detection_email_async(self, event, snapshot_file: str, clip_file: str | None):
        if not self.email_config.get("enabled"):
            return

        subject = tr("email.detection.subject", label=event.label, camera=event.camera_name)
        lines = [
            tr(
                "email.detection.body",
                label=event.label,
                camera=event.camera_name,
                confidence=f"{event.confidence:.2f}",
            ),
            "",
            f"Snapshot: {snapshot_file}",
        ]
        if clip_file:
            lines.append(f"Clip: {clip_file}")

        def send():
            try:
                send_detection_email(self.email_config, subject, "\n".join(lines), snapshot_file)
            except Exception as exc:
                print(f"Detection email failed: {exc}")

        threading.Thread(target=send, daemon=True).start()

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
    
    def window_geometry_payload(self):
        """Fensterposition/-größe für die Konfiguration (normale Geometrie, nicht maximiert)."""
        geometry = self.normalGeometry() if (self.isMaximized() or self.isFullScreen()) else self.geometry()
        return {
            "x": geometry.x(),
            "y": geometry.y(),
            "width": geometry.width(),
            "height": geometry.height(),
            "maximized": bool(self.isMaximized() or self.isFullScreen()),
        }

    def _restore_window_geometry(self, payload):
        """Gespeicherte Fensterposition/-größe wiederherstellen (nur wenn auf einem Bildschirm sichtbar)."""
        if not isinstance(payload, dict):
            return
        try:
            rect = QRect(int(payload["x"]), int(payload["y"]), int(payload["width"]), int(payload["height"]))
        except Exception:
            return
        if rect.width() < 400 or rect.height() < 300:
            return
        visible = False
        for screen in QGuiApplication.screens():
            overlap = screen.availableGeometry().intersected(rect)
            if overlap.width() >= 200 and overlap.height() >= 100:
                visible = True
                break
        if visible:
            self.setGeometry(rect)
        else:
            self.resize(rect.width(), rect.height())
        if payload.get("maximized"):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

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
            self.event_path = os.path.join(self.recording_path, "events")
            self.detection_config = {**DEFAULT_DETECTION_CONFIG, **config.get('detection', {})}
            self.email_config = {**DEFAULT_EMAIL_CONFIG, **config.get('email', {})}
            self._sync_detection_config_ui()
            self._sync_email_config_ui()
            self.cameras_per_row = config.get('cameras_per_row', 3)
            self._restore_preview_camera_ids = config.get('preview_camera_ids', [])
            self.selected_camera_id = config.get('selected_camera_id')
            self._order_custom = bool(config.get('order_custom', False))
            self.next_camera_id = config.get('next_camera_id', 1)
            self.ptz_pad_visible = bool(config.get('ptz_pad_visible', True))
            self._restore_window_geometry(config.get('window_geometry'))

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
            if self._any_camera_detection_enabled():
                QTimer.singleShot(300, self._ensure_detection_worker)
            QTimer.singleShot(2000, self.detect_missing_ptz)
            self._update_ptz_pad()
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
    
    def closeEvent(self, event):
        """Beim Schließen alle Threads sauber beenden"""
        running_threads = [t for t in self.camera_threads.values() if t.isRunning()]
        if self.detection_worker is not None:
            self.detection_worker.stop(timeout_ms=3000)
            self.detection_worker = None
        if not running_threads:
            self.save_config()
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
        self._apply_detection_visual_state()

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
        self._update_ptz_pad()
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
        if hasattr(self, "ptz_pad"):
            self.ptz_pad.retranslate_ui()
        if hasattr(self, "tabs"):
            self.tabs.setTabText(0, tr("tab.cameras"))
            self.tabs.setTabText(1, tr("tab.config"))
        if hasattr(self, "config_group"):
            self.config_group.setTitle(tr("group.camera_config"))
        if hasattr(self, "stats_label"):
            self.stats_label.setToolTip(tr("tooltip.stats"))
            self._update_stats_label()
        if hasattr(self, "detection_group"):
            self.detection_group.setTitle(tr("group.detection_config"))
        if hasattr(self, "email_group"):
            self.email_group.setTitle(tr("group.email_config"))
        if hasattr(self, "url_label"):
            self.url_label.setText(tr("label.rtsp_url"))
        if hasattr(self, "name_label"):
            self.name_label.setText(tr("label.name"))
        if hasattr(self, "detection_model_label"):
            self.detection_model_label.setText(tr("label.detection_model"))
            self.detection_device_label.setText(tr("label.detection_device"))
            self.detection_imgsz_label.setText(tr("label.detection_imgsz"))
            self.detection_conf_label.setText(tr("label.detection_conf"))
            self.detection_fps_label.setText(tr("label.detection_fps"))
            self.detection_cooldown_label.setText(tr("label.detection_cooldown"))
            self.detection_suppress_label.setText(tr("label.detection_suppress"))
            self.detection_clip_label.setText(tr("label.detection_clip"))
            self.detection_classes_label.setText(tr("label.detection_classes"))
            self.detection_motion_classes_label.setText(tr("label.detection_motion_classes"))
            self.detection_motion_pixels_label.setText(tr("label.detection_motion_pixels"))
            if hasattr(self, "detection_model_test_btn"):
                self.detection_model_test_btn.setText(tr("btn.model_test"))
            current_device = self.detection_device_combo.currentData()
            self.detection_device_combo.blockSignals(True)
            self.detection_device_combo.clear()
            self.detection_device_combo.addItem(tr("detection.device.auto"), "auto")
            self.detection_device_combo.addItem(tr("detection.device.cuda"), "cuda:0")
            self.detection_device_combo.addItem(tr("detection.device.cpu"), "cpu")
            idx = self.detection_device_combo.findData(current_device or self.detection_config.get("device", "auto"))
            if idx >= 0:
                self.detection_device_combo.setCurrentIndex(idx)
            self.detection_device_combo.blockSignals(False)
        if hasattr(self, "email_enabled_check"):
            self.email_enabled_check.setText(tr("label.email_enabled"))
            self.email_host_label.setText(tr("label.smtp_host"))
            self.email_port_label.setText(tr("label.smtp_port"))
            self.email_tls_check.setText(tr("label.smtp_tls"))
            self.email_user_label.setText(tr("label.smtp_username"))
            self.email_password_label.setText(tr("label.smtp_password"))
            self.email_from_label.setText(tr("label.email_from"))
            self.email_to_label.setText(tr("label.email_to"))
            if hasattr(self, "email_test_btn"):
                self.email_test_btn.setText(tr("btn.email_test"))
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
        if hasattr(self, "proxy_config_btn"):
            self.proxy_config_btn.setText(tr("btn.proxy_config"))
            self.proxy_config_btn.setToolTip(tr("tooltip.proxy_config"))
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
            label.setStyleSheet(self._preview_label_style())
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
            label.setStyleSheet(self._preview_label_style(camera_id))
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
                    label.setStyleSheet(self._preview_label_style(camera_id))
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
        self._apply_detection_visual_state()
        self._update_ptz_pad()

        for camera_id in selected_ids:
            widget = self.camera_widgets.get(camera_id)
            if widget is not None and widget.last_frame is not None:
                self._update_multi_view_frame(widget.last_frame, camera_id)
    
    def eventFilter(self, obj, event):
        """Event filter to reposition close buttons on label resize"""
        if obj is getattr(self, "big_preview_container", None) and event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            self._position_ptz_pad()
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
        label.setStyleSheet(self._preview_label_style(active_camera_id))
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
