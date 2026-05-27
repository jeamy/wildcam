import os
import sys

from PyQt6.QtGui import QIcon


def resource_path(relative_path: str) -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def load_svg_icon(name: str) -> QIcon:
    return QIcon(resource_path(os.path.join("assets", "icons", name)))
