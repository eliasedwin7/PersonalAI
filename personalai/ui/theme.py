"""Dark theme: Fusion style + a QPalette, no external theming library.

Written independently for PersonalAI (not imported from anywhere else -
this project has zero dependency on any sibling project's code), but the
same small, dependency-free approach as any other Qt app in this family:
own ~40 lines rather than pull in a theming package that might stop being
maintained.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(15, 16, 19))
    p.setColor(QPalette.ColorRole.WindowText, QColor(232, 234, 240))
    p.setColor(QPalette.ColorRole.Base, QColor(18, 19, 23))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(26, 28, 34))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(33, 36, 44))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(232, 234, 240))
    p.setColor(QPalette.ColorRole.Text, QColor(232, 234, 240))
    p.setColor(QPalette.ColorRole.Button, QColor(31, 34, 41))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(232, 234, 240))
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 85, 85))
    p.setColor(QPalette.ColorRole.Highlight, QColor(80, 122, 255))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(132, 139, 152))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 120))
    app.setPalette(p)
    app.setStyleSheet(
        """
        * {
            font-size: 13px;
            color: #e8eaf0;
            selection-background-color: #314a95;
        }
        QWidget#workspaceShell { background: #0f1013; }
        QWidget#sideBar {
            background: #14161b;
            border-right: 1px solid #242832;
        }
        QLabel#brand {
            color: #f7f8fb;
            font-size: 22px;
            font-weight: 700;
            padding: 2px 4px 0 4px;
        }
        QLabel#sideSubtitle {
            color: #8d96a8;
            font-size: 12px;
            padding: 0 4px 8px 4px;
        }
        QStackedWidget#pageStack { background: #0f1013; }
        QWidget#sessionPane {
            background: #111318;
            border-right: 1px solid #242832;
        }
        QWidget#chatWorkspace { background: #0f1013; }
        QLabel#workspaceTitle {
            color: #f7f8fb;
            font-size: 20px;
            font-weight: 700;
        }
        QLabel#pageTitle {
            color: #f7f8fb;
            font-size: 20px;
            font-weight: 700;
            padding: 2px 0 6px 0;
        }
        QLabel#paneTitle {
            color: #f7f8fb;
            font-size: 15px;
            font-weight: 650;
        }
        QWidget#emptyChatState { background: #0f1013; }
        QLabel#emptyStateTitle {
            color: #f7f8fb;
            font-size: 24px;
            font-weight: 700;
            padding-bottom: 12px;
        }
        QLabel#mutedLabel { color: #9aa3b5; }
        QLabel#connectionStatus {
            color: #9aa3b5;
            background: #101218;
            border: 1px solid #242832;
            border-radius: 6px;
            padding: 8px 10px;
        }
        QLabel#connectionStatus[online="true"] {
            color: #7ee0b2;
            border-color: #245943;
            background: #101a17;
        }
        QListWidget#navigationList {
            border: none;
            background: transparent;
            outline: none;
        }
        QListWidget#navigationList::item {
            border-radius: 6px;
            padding: 10px 12px;
            margin: 2px 0;
            color: #aab2c3;
        }
        QListWidget#navigationList::item:hover {
            background: #1b1f27;
            color: #f7f8fb;
        }
        QListWidget#navigationList::item:selected {
            background: #20283a;
            color: #f7f8fb;
            border-left: 3px solid #7c9cff;
        }
        QListWidget {
            border: 1px solid #242832;
            border-radius: 6px;
            background: #111318;
            outline: none;
        }
        QListWidget::item {
            border-radius: 4px;
            padding: 9px 10px;
            margin: 2px 4px;
            color: #c4cad6;
        }
        QListWidget::item:hover { background: #1b1f27; color: #f7f8fb; }
        QListWidget::item:selected { background: #25314d; color: #ffffff; }
        QPushButton, QToolButton {
            background: #1d212a;
            border: 1px solid #303746;
            border-radius: 6px;
            padding: 7px 12px;
            min-height: 24px;
            color: #e8eaf0;
        }
        QPushButton:hover, QToolButton:hover {
            background: #252b37;
            border-color: #465066;
        }
        QPushButton:pressed, QToolButton:pressed { background: #161922; }
        QPushButton:disabled, QToolButton:disabled {
            color: #6f7787;
            background: #171a21;
            border-color: #242832;
        }
        QPushButton#primaryButton {
            background: #5d7cff;
            border-color: #7892ff;
            color: #ffffff;
            font-weight: 650;
        }
        QPushButton#primaryButton:hover { background: #6e8aff; }
        QPushButton#sideButton {
            text-align: left;
            padding: 9px 12px;
            background: #191d25;
        }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            border: 1px solid #2b313e;
            border-radius: 6px;
            padding: 7px;
            background: #111318;
            color: #e8eaf0;
        }
        QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover,
        QSpinBox:hover, QDoubleSpinBox:hover {
            border-color: #3b4455;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
        QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #7c9cff;
            background: #131720;
        }
        QTextEdit#chatTranscript {
            border: none;
            background: transparent;
            padding: 16px 10px;
        }
        QLabel#imagePreview {
            background: #0d0f14;
            border: 1px solid #242832;
            border-radius: 6px;
            color: #8d96a8;
        }
        QPlainTextEdit#toolOutput {
            background: #0d0f14;
            border-color: #242832;
        }
        QProgressBar {
            border: 1px solid #303746;
            border-radius: 4px;
            background: #111318;
            min-height: 8px;
        }
        QProgressBar::chunk { background: #7c9cff; border-radius: 3px; }
        QTabWidget::pane {
            border: 1px solid #242832;
            border-radius: 6px;
            background: #111318;
            top: -1px;
        }
        QTabBar::tab {
            background: #151820;
            border: 1px solid #242832;
            padding: 8px 16px;
            margin-right: 3px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            color: #aab2c3;
        }
        QTabBar::tab:hover { color: #f7f8fb; background: #1b1f27; }
        QTabBar::tab:selected {
            background: #20283a;
            color: #ffffff;
            border-color: #34405a;
        }
        QSplitter::handle { background: #242832; }
        QScrollBar:vertical {
            background: transparent;
            width: 10px;
            margin: 2px;
        }
        QScrollBar::handle:vertical {
            background: #303746;
            border-radius: 4px;
            min-height: 28px;
        }
        QScrollBar::handle:vertical:hover { background: #465066; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """
    )
