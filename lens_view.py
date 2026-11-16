from PyQt6.QtCore import QEvent, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QVBoxLayout, QWidget

from i18n import tr
from v380 import is_v380_url
from widgets import PreviewLabel, PtzPad, letterbox_rgb, rgb_to_pixmap


def has_split_lenses(camera):
    return bool(camera and is_v380_url(camera.get('url', ''))
                and str(camera.get('model', '')).upper() == 'D57')


class LensView(QWidget):
    move_requested = pyqtSignal(str)
    stop_requested = pyqtSignal()
    close_requested = pyqtSignal()
    expand_requested = pyqtSignal()

    def __init__(self, camera_id, camera_name, half, *, ptz=False, parent=None):
        super().__init__(parent)
        if half not in ('upper', 'lower'):
            raise ValueError('Invalid lens half')
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.half = half
        self.frame = None
        self.crop_rect = None
        self.setMinimumSize(0, 180)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        controls = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self.title_label, 1)
        self.zoom_in_button = QPushButton('+')
        self.zoom_out_button = QPushButton('−')
        self.reset_button = QPushButton()
        self.expand_button = QPushButton()
        self.expand_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
        self.close_button = QPushButton()
        self.close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_button.setStyleSheet('background-color: #dc3545; border-radius: 12px;')
        for button in (self.zoom_out_button, self.zoom_in_button, self.expand_button, self.close_button):
            button.setFixedSize(28, 24)
        for button in (self.zoom_out_button, self.zoom_in_button, self.reset_button,
                       self.expand_button, self.close_button):
            controls.addWidget(button)
        self.zoom_in_button.clicked.connect(lambda: self.zoom(1.5))
        self.zoom_out_button.clicked.connect(lambda: self.zoom(1 / 1.5))
        self.reset_button.clicked.connect(self.reset_zoom)
        self.expand_button.clicked.connect(self.expand_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)
        layout.addLayout(controls)
        self.label = PreviewLabel(camera_id, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet('background-color: black; color: white;')
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.label.set_selection_enabled(True)
        self.label.region_selected.connect(self._select_region)
        self.label.double_clicked.connect(self._double_clicked)
        self.label.installEventFilter(self)
        self.window().installEventFilter(self)
        layout.addWidget(self.label, 1)
        self.ptz_pad = PtzPad(self.label) if half == 'lower' and ptz else None
        if self.ptz_pad is not None:
            self.ptz_pad.move_requested.connect(self.move_requested.emit)
            self.ptz_pad.stop_requested.connect(self.stop_requested.emit)
            self.ptz_pad.visibility_toggled.connect(self._toggle_ptz)
            self.ptz_pad.setEnabled(False)
        self.retranslate_ui()
        self.label.setText(tr('camera.preview.waiting'))

    def retranslate_ui(self):
        title = f"{self.camera_name} — {tr('lens.' + self.half)}"
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.reset_button.setText(tr('lens.reset'))
        self.zoom_in_button.setToolTip(tr('lens.zoom_in'))
        self.zoom_out_button.setToolTip(tr('lens.zoom_out'))
        self.expand_button.setToolTip(tr('lens.expand'))
        self.close_button.setToolTip(tr('lens.close'))
        self.label.setToolTip(tr('lens.zoom_hint'))
        if self.ptz_pad is not None:
            self.ptz_pad.retranslate_ui()

    def update_frame(self, frame):
        if frame is None or frame.ndim != 3 or frame.shape[0] < 2 or frame.shape[1] < 1:
            self.set_status(False, tr('status.no_image'))
            return
        middle = frame.shape[0] // 2
        half_frame = frame[:middle] if self.half == 'upper' else frame[middle:]
        if self.frame is None or self.frame.shape != half_frame.shape:
            self.crop_rect = None
        self.frame = half_frame
        if self.ptz_pad is not None:
            self.ptz_pad.setEnabled(True)
        self._render()

    def set_status(self, connected, message):
        if connected:
            return
        self.stop_requested.emit()
        self.frame = None
        self.crop_rect = None
        self.label.clear_frame_display_rect()
        self.label.setText(message)
        if self.ptz_pad is not None:
            self.ptz_pad.setEnabled(False)

    def _source_rect(self):
        if self.crop_rect is not None:
            return QRect(self.crop_rect)
        return QRect(0, 0, self.frame.shape[1], self.frame.shape[0])

    def zoom(self, factor, anchor=None):
        if self.frame is None or factor <= 0:
            return
        source = self._source_rect()
        height, width = self.frame.shape[:2]
        x_ratio, y_ratio = anchor if anchor is not None else (0.5, 0.5)
        new_width = max(min(16, width), min(width, round(source.width() / factor)))
        new_height = max(min(16, height), min(height, round(source.height() / factor)))
        x = round(source.x() + x_ratio * (source.width() - new_width))
        y = round(source.y() + y_ratio * (source.height() - new_height))
        self.crop_rect = QRect(max(0, min(width - new_width, x)),
                               max(0, min(height - new_height, y)), new_width, new_height)
        if new_width == width and new_height == height:
            self.crop_rect = None
        self._render()

    def reset_zoom(self, *_args):
        self.crop_rect = None
        self.label.clear_selection()
        self._render()

    def _double_clicked(self, *_args):
        if self.crop_rect is not None:
            self.reset_zoom()
        else:
            self.expand_requested.emit()

    def _select_region(self, _camera_id, selection):
        if self.frame is None:
            return
        display = self.label.frame_display_rect()
        selection = selection.intersected(display)
        if display.isEmpty() or selection.width() < 8 or selection.height() < 8:
            return
        source = self._source_rect()
        x = source.x() + round((selection.x() - display.x()) * source.width() / display.width())
        y = source.y() + round((selection.y() - display.y()) * source.height() / display.height())
        width = max(1, round(selection.width() * source.width() / display.width()))
        height = max(1, round(selection.height() * source.height() / display.height()))
        crop = QRect(x, y, width, height).intersected(source)
        if not crop.isEmpty():
            self.crop_rect = crop
            self._render()

    def _render(self):
        if self.frame is None:
            return
        rgb, rect = letterbox_rgb(self.frame, self.label.width(), self.label.height(), self.crop_rect)
        if rgb is not None:
            self.label.setPixmap(rgb_to_pixmap(rgb))
            self.label.set_frame_display_rect(rect)

    def _position_ptz(self):
        if self.ptz_pad is not None:
            self.ptz_pad.adjustSize()
            self.ptz_pad.move(max(0, self.label.width() - self.ptz_pad.width() - 10),
                              max(0, self.label.height() - self.ptz_pad.height() - 10))
            self.ptz_pad.raise_()

    def _toggle_ptz(self, expanded):
        if not expanded:
            self.stop_requested.emit()
        self._position_ptz()

    def eventFilter(self, obj, event):
        if obj is self.window() and event.type() == QEvent.Type.WindowDeactivate:
            self.stop_requested.emit()
        if obj is self.label:
            if event.type() == QEvent.Type.Resize:
                self._render()
                self._position_ptz()
            elif event.type() == QEvent.Type.Wheel:
                display = self.label.frame_display_rect()
                pos = event.position().toPoint()
                delta = event.angleDelta().y()
                if display.contains(pos) and delta:
                    self.zoom(1.25 if delta > 0 else 0.8,
                              ((pos.x() - display.x()) / display.width(),
                               (pos.y() - display.y()) / display.height()))
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate:
            self.stop_requested.emit()
        return super().event(event)

    def hideEvent(self, event):
        self.stop_requested.emit()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.stop_requested.emit()
        self.frame = None
        super().closeEvent(event)
