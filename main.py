import os
import sys

os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'
os.environ['AV_LOG_FORCE_NOCOLOR'] = '1'
os.environ['AV_LOG_FORCE_LEVEL'] = '-8'
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|loglevel;quiet'

import cv2
from PyQt6.QtWidgets import QApplication

from main_window import MainWindow


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
