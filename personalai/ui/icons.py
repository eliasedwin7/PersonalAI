"""Small native-icon helpers for PySide widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle


def standard_icon(pixmap: QStyle.StandardPixmap):
    app = QApplication.instance()
    if app is None:
        return None
    return app.style().standardIcon(pixmap)
