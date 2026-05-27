from datetime import datetime

import cv2
from PyQt6.QtCore import QMimeData, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from ui_resources import load_svg_icon


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


class CameraWidget(QWidget):
    """Widget für einzelne Kamera-Anzeige"""
    clicked = pyqtSignal(int)
    stream_toggled = pyqtSignal(int, bool)
    snapshot_requested = pyqtSignal(int)
    selection_changed = pyqtSignal(int, bool)

    def __init__(self, camera_id, camera_name="", is_battery=False):
        super().__init__()
        self.camera_id = camera_id
        self.camera_name = camera_name or tr("camera.default_name.id", id=camera_id)
        self.is_battery = is_battery
        self.recording = False
        self.last_frame_time = datetime.now()
        self.stream_active = False
        self.last_frame = None
        self._drag_start_pos = None
        self._video_drag_start_pos = None
        self._video_dragging = False
        self.is_selected_for_view = False
        
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Checkbox für Multi-Kamera-Auswahl
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setContentsMargins(4, 2, 4, 2)
        self.view_checkbox = QCheckBox("✓")
        self.view_checkbox.setToolTip("Kamera in großer Ansicht anzeigen")
        self.view_checkbox.setStyleSheet("""
            QCheckBox {
                font-weight: bold;
                font-size: 10px;
                color: #4CAF50;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 2px solid #4CAF50;
                border-radius: 2px;
                background-color: #2b2b2b;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
            }
            QCheckBox::indicator:hover {
                border-color: #66BB6A;
            }
        """)
        self.view_checkbox.stateChanged.connect(self._on_checkbox_changed)
        checkbox_layout.addWidget(self.view_checkbox)
        checkbox_layout.addStretch()
        layout.addLayout(checkbox_layout)
        
        # Video Label
        self.video_label = QLabel()
        self.video_label.setFixedSize(180, 120)
        border_color = "#ff9800" if is_battery else "#555"
        self.video_label.setStyleSheet(f"border: 2px solid {border_color}; background-color: black;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText(f"{self.camera_name}\n{tr('camera.preview.click_to_start')}")
        self.video_label.setScaledContents(False)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.video_label.mousePressEvent = self._on_video_mouse_press
        self.video_label.mouseMoveEvent = self._on_video_mouse_move
        self.video_label.mouseReleaseEvent = self._on_video_mouse_release
        
        # Info Label mit FPS und Battery-Indikator
        battery_indicator = f" {tr('battery.indicator')}" if is_battery else ""
        self.info_label = QLabel(f"{self.camera_name}{battery_indicator} - {tr('camera.status.offline')}")
        label_color = "#ff9800" if is_battery else "red"
        self.info_label.setStyleSheet(f"color: {label_color}; font-weight: bold; font-size: 11px;")
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
        self.setFixedHeight(120 + 18 + 24 + 16 + 24)

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
        if self.is_selected_for_view:
            return

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

    def _on_checkbox_changed(self, state):
        self.is_selected_for_view = (state == Qt.CheckState.Checked.value)
        if self.is_selected_for_view:
            self.video_label.setPixmap(QPixmap())
            self.video_label.setText(f"{self.camera_name}\n{tr('camera.preview.waiting')}")
        self.selection_changed.emit(self.camera_id, self.is_selected_for_view)
    
    def set_selected(self, selected):
        if selected:
            self.video_label.setStyleSheet("border: 2px solid #4CAF50; background-color: black;")
        else:
            border_color = "#ff9800" if self.is_battery else "#555"
            self.video_label.setStyleSheet(f"border: 2px solid {border_color}; background-color: black;")


class PreviewLabel(QLabel):
    clicked = pyqtSignal(int)
    double_clicked = pyqtSignal(int)
    region_selected = pyqtSignal(int, QRect)

    def __init__(self, camera_id=None, parent=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self._selection_enabled = False
        self._selection_origin = None
        self._selection_rect = QRect()
        self._frame_display_rect = QRect()

    def set_selection_enabled(self, enabled: bool):
        self._selection_enabled = bool(enabled)
        self.setCursor(
            Qt.CursorShape.CrossCursor if self._selection_enabled else Qt.CursorShape.ArrowCursor
        )
        if not self._selection_enabled:
            self.clear_selection()

    def clear_selection(self):
        if not self._selection_rect.isNull():
            self._selection_rect = QRect()
            self.update()
        self._selection_origin = None

    def set_frame_display_rect(self, rect: QRect):
        self._frame_display_rect = QRect(rect)

    def clear_frame_display_rect(self):
        self._frame_display_rect = QRect()
        self.clear_selection()

    def frame_display_rect(self) -> QRect:
        return QRect(self._frame_display_rect)

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.camera_id is not None
            and self._selection_enabled
        ):
            pos = event.position().toPoint()
            if self._frame_display_rect.contains(pos):
                self._selection_origin = pos
                self._selection_rect = QRect(pos, pos)
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._selection_enabled and self._selection_origin is not None:
            pos = event.position().toPoint()
            self._selection_rect = QRect(self._selection_origin, pos).normalized()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selection_origin is not None:
            selection_rect = QRect(self._selection_origin, event.position().toPoint()).normalized()
            selection_rect = selection_rect.intersected(self._frame_display_rect)
            self.clear_selection()
            if (
                self.camera_id is not None
                and selection_rect.width() >= 8
                and selection_rect.height() >= 8
            ):
                self.region_selected.emit(int(self.camera_id), selection_rect)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.camera_id is not None:
            self.clear_selection()
            self.double_clicked.emit(int(self.camera_id))
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._selection_rect.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(76, 175, 80), 2))
        painter.fillRect(self._selection_rect, QColor(76, 175, 80, 45))
        painter.drawRect(self._selection_rect)

