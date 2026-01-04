import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QPushButton, QLabel, 
                             QLineEdit, QSpinBox, QCheckBox, QFileDialog,
                             QMessageBox, QComboBox, QGroupBox, QScrollArea)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from datetime import datetime
import json
import os


class CameraThread(QThread):
    """Thread für einzelne Kamera mit OpenCV - optimiert für parallele Streams"""
    frame_ready = pyqtSignal(np.ndarray, int)
    connection_status = pyqtSignal(bool, int, str)
    
    def __init__(self, camera_id, rtsp_url):
        super().__init__()
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.running = False
        self.recording = False
        self.video_writer = None
        self.cap = None
        self.reconnect_delay = 3  # Sekunden zwischen Reconnects
        
    def run(self):
        """Hauptschleife mit automatischem Retry"""
        self.running = True
        
        while self.running:
            try:
                self._connect_and_stream()
            except Exception as e:
                self.connection_status.emit(False, self.camera_id, f"Fehler: {str(e)}")
                if self.running:
                    self.sleep(self.reconnect_delay)  # Warte vor erneutem Versuch
        
        self._cleanup()
    
    def _connect_and_stream(self):
        """Verbindung herstellen und streamen"""
        # RTSP Stream öffnen mit optimierten Parametern
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        
        # Optimierungen für geringe Latenz und CPU-Schonung
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimaler Buffer
        self.cap.set(cv2.CAP_PROP_FPS, 25)  # FPS begrenzen
        
        if not self.cap.isOpened():
            raise Exception("Stream nicht erreichbar")
        
        self.connection_status.emit(True, self.camera_id, "Verbunden")
        
        frame_skip = 0
        skip_interval = 1  # Jedes zweite Frame für CPU-Schonung
        
        while self.running:
            ret, frame = self.cap.read()
            
            if not ret:
                raise Exception("Stream unterbrochen")
            
            # CPU-Schonung: nicht jedes Frame verarbeiten
            frame_skip += 1
            if frame_skip % skip_interval == 0:
                # Frame an UI senden
                self.frame_ready.emit(frame.copy(), self.camera_id)
            
            # Aufzeichnung (alle Frames)
            if self.recording and self.video_writer:
                self.video_writer.write(frame)
            
            # CPU-Schonung: Kleine Pause
            self.msleep(33)  # ~30 FPS
    
    def _cleanup(self):
        """Ressourcen freigeben"""
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
    
    def start_recording(self, output_path):
        """Starte Aufzeichnung"""
        if self.cap and self.cap.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps = int(self.cap.get(cv2.CAP_PROP_FPS)) or 25
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{output_path}/camera_{self.camera_id}_{timestamp}.mp4"
            
            self.video_writer = cv2.VideoWriter(filename, fourcc, fps, (width, height))
            self.recording = True
            return filename
        return None
    
    def stop_recording(self):
        """Stoppe Aufzeichnung"""
        self.recording = False
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
    
    def stop(self):
        """Thread stoppen"""
        self.running = False
        self.wait()


class CameraWidget(QWidget):
    """Widget für einzelne Kamera-Anzeige"""
    def __init__(self, camera_id, camera_name=""):
        super().__init__()
        self.camera_id = camera_id
        self.camera_name = camera_name or f"Kamera {camera_id}"
        self.recording = False
        self.last_frame_time = datetime.now()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Video Label
        self.video_label = QLabel()
        self.video_label.setMinimumSize(280, 210)
        self.video_label.setStyleSheet("border: 2px solid #555; background-color: black;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setText(f"{self.camera_name}\nWarte auf Stream...")
        self.video_label.setScaledContents(False)
        
        # Info Label mit FPS
        self.info_label = QLabel(f"{self.camera_name} - Offline")
        self.info_label.setStyleSheet("color: red; font-weight: bold; font-size: 11px;")
        
        # Button Layout
        btn_layout = QHBoxLayout()
        
        # Aufnahme Button
        self.record_btn = QPushButton("●")
        self.record_btn.setCheckable(True)
        self.record_btn.setEnabled(False)
        self.record_btn.setMaximumWidth(40)
        self.record_btn.setToolTip("Aufzeichnung starten/stoppen")
        self.record_btn.clicked.connect(self.toggle_recording)
        
        # Entfernen Button
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setMaximumWidth(40)
        self.remove_btn.setToolTip("Kamera entfernen")
        self.remove_btn.setStyleSheet("color: #999;")
        
        btn_layout.addWidget(self.record_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        
        layout.addWidget(self.video_label)
        layout.addWidget(self.info_label)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        self.setMaximumWidth(300)
    
    def update_frame(self, frame):
        """Frame aktualisieren mit FPS-Berechnung"""
        # FPS berechnen
        now = datetime.now()
        fps = 1.0 / (now - self.last_frame_time).total_seconds() if (now - self.last_frame_time).total_seconds() > 0 else 0
        self.last_frame_time = now
        
        # Resize für Display
        h, w = frame.shape[:2]
        display_w, display_h = 280, 210
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
            self.video_label.setText(f"{self.camera_name}\n{message}\nVersuche erneut...")
    
    def toggle_recording(self):
        """Aufnahme umschalten"""
        self.recording = self.record_btn.isChecked()
        if self.recording:
            self.record_btn.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
        else:
            self.record_btn.setStyleSheet("")


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reolink Multi-Camera Viewer")
        self.setGeometry(100, 100, 1200, 800)
        
        self.cameras = []
        self.camera_threads = {}  # Dict für parallele Thread-Verwaltung
        self.camera_widgets = {}  # Dict für Widget-Zugriff
        self.recording_path = os.path.expanduser("~/Videos/Reolink")
        self.cameras_per_row = 3  # Standard: 3 Kameras pro Reihe
        self.next_camera_id = 1
        
        # Erstelle Aufzeichnungsordner
        os.makedirs(self.recording_path, exist_ok=True)
        
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        """UI initialisieren"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Konfigurations-Panel
        config_group = QGroupBox("Kamera-Konfiguration")
        config_layout = QVBoxLayout()
        
        # Erste Zeile: URL und Name
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("RTSP URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("rtsp://admin:password@192.168.1.100:554/h264Preview_01_main")
        self.url_input.setMinimumWidth(400)
        row1.addWidget(self.url_input)
        
        row1.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("z.B. Eingang")
        self.name_input.setMaximumWidth(150)
        row1.addWidget(self.name_input)
        
        add_btn = QPushButton("➕ Hinzufügen")
        add_btn.clicked.connect(self.add_camera)
        row1.addWidget(add_btn)
        
        config_layout.addLayout(row1)
        
        # Zweite Zeile: Grid-Einstellungen und Aktionen
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Kameras pro Reihe:"))
        self.grid_cols_spin = QSpinBox()
        self.grid_cols_spin.setRange(1, 10)
        self.grid_cols_spin.setValue(3)
        self.grid_cols_spin.valueChanged.connect(self.update_grid_layout)
        row2.addWidget(self.grid_cols_spin)
        
        clear_btn = QPushButton("Alle entfernen")
        clear_btn.clicked.connect(self.clear_cameras)
        row2.addWidget(clear_btn)
        
        path_btn = QPushButton("📁 Speicherort")
        path_btn.clicked.connect(self.select_recording_path)
        row2.addWidget(path_btn)
        
        row2.addStretch()
        config_layout.addLayout(row2)
        
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)
        
        # Control Panel
        control_layout = QHBoxLayout()
        
        self.start_all_btn = QPushButton("▶ Alle Streams starten")
        self.start_all_btn.clicked.connect(self.start_all_streams)
        self.start_all_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        
        self.stop_all_btn = QPushButton("⏹ Alle Streams stoppen")
        self.stop_all_btn.clicked.connect(self.stop_all_streams)
        
        self.record_all_btn = QPushButton("● Alle aufnehmen")
        self.record_all_btn.setCheckable(True)
        self.record_all_btn.clicked.connect(self.toggle_all_recording)
        
        self.camera_count_label = QLabel("Kameras: 0 | Aktiv: 0")
        self.camera_count_label.setStyleSheet("font-weight: bold;")
        
        control_layout.addWidget(self.start_all_btn)
        control_layout.addWidget(self.stop_all_btn)
        control_layout.addWidget(self.record_all_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.camera_count_label)
        
        main_layout.addLayout(control_layout)
        
        # Scroll Area für Kamera-Grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.camera_container = QWidget()
        self.camera_grid = QGridLayout(self.camera_container)
        self.camera_grid.setSpacing(8)
        self.camera_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        scroll.setWidget(self.camera_container)
        main_layout.addWidget(scroll)
        
        # Status Bar
        self.statusBar().showMessage("Bereit - CPU-optimiert für parallele Streams")
        
        # Timer für Status-Updates
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status_display)
        self.status_timer.start(2000)  # Alle 2 Sekunden
    
    def add_camera(self):
        """Kamera hinzufügen"""
        url = self.url_input.text().strip()
        name = self.name_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "Fehler", "Bitte RTSP URL eingeben!")
            return
        
        camera_id = self.next_camera_id
        self.next_camera_id += 1
        
        camera_name = name if name else f"Kamera {camera_id}"
        
        # Kamera zur Liste hinzufügen
        self.cameras.append({
            'id': camera_id, 
            'url': url, 
            'name': camera_name
        })
        
        # Widget erstellen
        widget = CameraWidget(camera_id, camera_name)
        widget.remove_btn.clicked.connect(lambda: self.remove_camera(camera_id))
        self.camera_widgets[camera_id] = widget
        
        # Im Grid platzieren
        self.update_grid_layout()
        
        # Eingabe leeren
        self.url_input.clear()
        self.name_input.clear()
        
        self.update_status_display()
        self.statusBar().showMessage(f"{camera_name} hinzugefügt")
        self.save_config()
    
    def remove_camera(self, camera_id):
        """Einzelne Kamera entfernen"""
        # Thread stoppen falls aktiv
        if camera_id in self.camera_threads:
            self.camera_threads[camera_id].stop()
            del self.camera_threads[camera_id]
        
        # Widget entfernen
        if camera_id in self.camera_widgets:
            widget = self.camera_widgets[camera_id]
            self.camera_grid.removeWidget(widget)
            widget.deleteLater()
            del self.camera_widgets[camera_id]
        
        # Aus Liste entfernen
        self.cameras = [c for c in self.cameras if c['id'] != camera_id]
        
        self.update_grid_layout()
        self.update_status_display()
        self.save_config()
        self.statusBar().showMessage(f"Kamera {camera_id} entfernt")
    
    def update_grid_layout(self):
        """Grid-Layout neu berechnen basierend auf cameras_per_row"""
        self.cameras_per_row = self.grid_cols_spin.value()
        
        # Alle Widgets aus Grid entfernen
        for camera_id, widget in self.camera_widgets.items():
            self.camera_grid.removeWidget(widget)
        
        # Widgets neu platzieren
        for idx, camera in enumerate(self.cameras):
            camera_id = camera['id']
            if camera_id in self.camera_widgets:
                row = idx // self.cameras_per_row
                col = idx % self.cameras_per_row
                self.camera_grid.addWidget(self.camera_widgets[camera_id], row, col)
    
    def clear_cameras(self):
        """Alle Kameras entfernen"""
        if not self.cameras:
            return
        
        reply = QMessageBox.question(self, 'Bestätigung', 
                                    'Alle Kameras entfernen?',
                                    QMessageBox.StandardButton.Yes | 
                                    QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.stop_all_streams()
            
            for widget in self.camera_widgets.values():
                self.camera_grid.removeWidget(widget)
                widget.deleteLater()
            
            self.camera_widgets.clear()
            self.cameras.clear()
            self.next_camera_id = 1
            self.update_status_display()
            self.save_config()
            self.statusBar().showMessage("Alle Kameras entfernt")
    
    def start_all_streams(self):
        """Alle Streams parallel starten"""
        if not self.cameras:
            QMessageBox.information(self, "Info", "Keine Kameras konfiguriert!")
            return
        
        # Threads parallel starten
        for camera in self.cameras:
            camera_id = camera['id']
            
            # Skip wenn bereits läuft
            if camera_id in self.camera_threads and self.camera_threads[camera_id].isRunning():
                continue
            
            # Neuen Thread erstellen
            thread = CameraThread(camera_id, camera['url'])
            
            # Signals verbinden
            thread.frame_ready.connect(lambda frame, cid=camera_id: self.update_camera_frame(frame, cid))
            thread.connection_status.connect(lambda connected, cid, msg: self.update_camera_status(connected, cid, msg))
            
            # Aufnahme-Button verbinden
            if camera_id in self.camera_widgets:
                widget = self.camera_widgets[camera_id]
                widget.record_btn.clicked.connect(
                    lambda checked, t=thread, w=widget: self.toggle_camera_recording(t, w, checked)
                )
            
            # Thread starten (parallel)
            thread.start()
            self.camera_threads[camera_id] = thread
        
        self.statusBar().showMessage(f"{len(self.cameras)} Streams werden parallel gestartet...")
    
    def stop_all_streams(self):
        """Alle Streams stoppen"""
        for thread in list(self.camera_threads.values()):
            thread.stop()
        self.camera_threads.clear()
        self.update_status_display()
        self.statusBar().showMessage("Alle Streams gestoppt")
    
    def update_camera_frame(self, frame, camera_id):
        """Frame einer Kamera aktualisieren"""
        if camera_id in self.camera_widgets:
            self.camera_widgets[camera_id].update_frame(frame)
    
    def update_camera_status(self, connected, camera_id, message):
        """Status einer Kamera aktualisieren"""
        if camera_id in self.camera_widgets:
            self.camera_widgets[camera_id].update_status(connected, message)
    
    def toggle_camera_recording(self, thread, widget, checked):
        """Aufnahme einer einzelnen Kamera umschalten"""
        if checked:
            filename = thread.start_recording(self.recording_path)
            if filename:
                self.statusBar().showMessage(f"Aufnahme: {os.path.basename(filename)}")
        else:
            thread.stop_recording()
            self.statusBar().showMessage(f"Aufnahme gestoppt: {widget.camera_name}")
    
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
            self.record_all_btn.setText("■ Alle stoppen")
            self.record_all_btn.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
            self.statusBar().showMessage(f"{count} Aufnahmen gestartet")
        else:
            self.record_all_btn.setText("● Alle aufnehmen")
            self.record_all_btn.setStyleSheet("")
            self.statusBar().showMessage(f"{count} Aufnahmen gestoppt")
    
    def update_status_display(self):
        """Statusanzeige aktualisieren"""
        total = len(self.cameras)
        active = len([t for t in self.camera_threads.values() if t.isRunning()])
        self.camera_count_label.setText(f"Kameras: {total} | Aktiv: {active}")
    
    def select_recording_path(self):
        """Speicherort für Aufnahmen wählen"""
        path = QFileDialog.getExistingDirectory(self, "Speicherort wählen", self.recording_path)
        if path:
            self.recording_path = path
            self.save_config()
            self.statusBar().showMessage(f"Speicherort: {path}")
    
    def save_config(self):
        """Konfiguration speichern"""
        config = {
            'cameras': self.cameras,
            'recording_path': self.recording_path,
            'cameras_per_row': self.cameras_per_row,
            'next_camera_id': self.next_camera_id
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
                self.cameras = config.get('cameras', [])
                self.recording_path = config.get('recording_path', self.recording_path)
                self.cameras_per_row = config.get('cameras_per_row', 3)
                self.next_camera_id = config.get('next_camera_id', 1)
                
                self.grid_cols_spin.setValue(self.cameras_per_row)
                
                # Widgets erstellen
                for camera in self.cameras:
                    camera_id = camera['id']
                    camera_name = camera.get('name', f"Kamera {camera_id}")
                    
                    widget = CameraWidget(camera_id, camera_name)
                    widget.remove_btn.clicked.connect(lambda checked, cid=camera_id: self.remove_camera(cid))
                    self.camera_widgets[camera_id] = widget
                
                self.update_grid_layout()
                self.update_status_display()
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
    
    def closeEvent(self, event):
        """Beim Schließen alle Threads sauber beenden"""
        self.stop_all_streams()
        event.accept()


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