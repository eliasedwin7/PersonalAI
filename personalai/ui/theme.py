"""Dark theme: Fusion style + a QPalette, no external theming library.

Written independently for PersonalAI (not imported from anywhere else -
this project has zero dependency on any sibling project's code), but the
same small, dependency-free approach as any other Qt app in this family:
own ~40 lines rather than pull in a theming package that might stop being
maintained.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(37, 37, 38))
    p.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 48))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Button, QColor(45, 45, 48))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 85, 85))
    p.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 140))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 120))
    app.setPalette(p)
