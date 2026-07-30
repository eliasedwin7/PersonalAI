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
        QWidget#workspaceShell { background: #1e201d; }
        QWidget#appBar { background: #272925; border-bottom: 1px solid #3f433c; }
        QWidget#sessionPane { background: #242622; border-right: 1px solid #3f433c; }
        QWidget#chatWorkspace { background: #1e201d; }
        QLabel#brand { color: #f4f1e9; font-size: 17px; font-weight: 700; }
        QLabel#workspaceTitle { color: #f4f1e9; font-size: 20px; font-weight: 700; }
        QLabel#pageTitle { color: #f4f1e9; font-size: 18px; font-weight: 700; padding: 8px 4px; }
        QLabel#paneTitle { color: #f4f1e9; font-size: 15px; font-weight: 700; }
        QWidget#emptyChatState { background: #1e201d; }
        QLabel#emptyStateTitle { color: #f4f1e9; font-size: 21px; font-weight: 700; padding-bottom: 12px; }
        QLabel#mutedLabel { color: #aeb4a7; }
        QLabel#connectionStatus { color: #aeb4a7; padding: 4px 6px; }
        QLabel#connectionStatus[online="true"] { color: #8bdba5; }
        QTabBar#navigation { border: none; background: transparent; }
        QTabBar#navigation::tab { background: transparent; border: none; color: #b8bcb2; padding: 7px 10px; margin: 0 2px; }
        QTabBar#navigation::tab:hover { color: #f4f1e9; }
        QTabBar#navigation::tab:selected { color: #f4f1e9; border-bottom: 2px solid #63b58c; }
        QListWidget { border: none; background: transparent; outline: none; }
        QListWidget::item { border-radius: 4px; padding: 8px 9px; margin: 1px 0; }
        QListWidget::item:selected { background: #344d43; color: #f5fff7; }
        QPushButton, QToolButton { background: #333731; border: 1px solid #4a4f47; border-radius: 4px; padding: 6px 10px; min-height: 20px; }
        QPushButton:hover, QToolButton:hover { background: #40453d; border-color: #7f8e7d; }
        QPushButton:pressed, QToolButton:pressed { background: #292c27; }
        QPushButton:disabled { color: #747870; background: #292b27; border-color: #3c4039; }
        QPushButton#primaryButton { background: #3d7e65; border-color: #4d997b; color: #f6fff9; }
        QPushButton#primaryButton:hover { background: #4d9678; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox { border: 1px solid #42473f; border-radius: 4px; padding: 6px; background: #191b18; }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #65a98b; }
        QProgressBar { border: 1px solid #4c514a; border-radius: 3px; background: #1b1d1a; min-height: 8px; }
        QProgressBar::chunk { background: #5bbf8a; border-radius: 2px; }
        QTabWidget::pane { border: 0; background: #1e201d; }
        QTabBar::tab { background: #252823; border: 1px solid #42473f; padding: 7px 14px; margin-right: 2px; }
        QTabBar::tab:selected { background: #344d43; color: #f5fff7; }
        """
    )
