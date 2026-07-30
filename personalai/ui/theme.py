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
    app.setStyleSheet(
        """
        QWidget#workspaceShell { background: #20221f; }
        QWidget#sidebar { background: #292b27; border: 1px solid #41443d; border-radius: 6px; }
        QLabel#brand { color: #f4f1e9; font-size: 19px; font-weight: 700; padding: 8px; }
        QLabel#workspaceTitle { color: #f4f1e9; font-size: 20px; font-weight: 700; }
        QLabel#pageTitle { color: #f4f1e9; font-size: 18px; font-weight: 700; }
        QLabel#mutedLabel { color: #aeb4a7; }
        QLabel#connectionStatus { color: #aeb4a7; border: 1px solid #51564c; border-radius: 4px; padding: 4px 8px; }
        QLabel#connectionStatus[online="true"] { color: #8bdba5; border-color: #477d5a; }
        QListWidget#navigation { border: none; background: transparent; outline: none; padding-top: 8px; }
        QListWidget#navigation::item { border-radius: 4px; padding: 10px 12px; margin: 2px 0; }
        QListWidget#navigation::item:selected { background: #355e52; color: #f5fff7; }
        QPushButton { background: #343833; border: 1px solid #52574f; border-radius: 4px; padding: 6px 10px; min-height: 20px; }
        QPushButton:hover { background: #41463e; border-color: #7f8e7d; }
        QPushButton:pressed { background: #2a2d29; }
        QPushButton:disabled { color: #747870; background: #292b27; border-color: #3c4039; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox { border: 1px solid #4c514a; border-radius: 4px; padding: 5px; background: #1b1d1a; }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #6da892; }
        QProgressBar { border: 1px solid #4c514a; border-radius: 3px; background: #1b1d1a; min-height: 8px; }
        QProgressBar::chunk { background: #5bbf8a; border-radius: 2px; }
        QTabBar::tab { background: #2a2d29; border: 1px solid #484d45; padding: 7px 14px; margin-right: 2px; }
        QTabBar::tab:selected { background: #355e52; color: #f5fff7; }
        """
    )
