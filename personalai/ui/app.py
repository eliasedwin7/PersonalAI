"""GUI bootstrap. Launched via `myai gui` (cli.py imports this lazily so
plain CLI usage never pays the Qt import cost)."""

from __future__ import annotations

import sys

from personalai.core import config as config_mod
from personalai.core.conversation import ConversationStore
from personalai.services.backend_factory import build_llm_client
from personalai.services.chat_service import ChatService
from personalai.services.knowledge_service import KnowledgeStore


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from personalai.ui.hotkey import GlobalHotkey
    from personalai.ui.main_window import ICON_PATH, MainWindow
    from personalai.ui.theme import apply_dark_theme

    config_mod.ensure_dirs()
    config_store = config_mod.ConfigStore()
    config = config_store.load()
    chat_service = ChatService(
        config=config,
        store=ConversationStore(),
        client=build_llm_client(config),
        knowledge_store=KnowledgeStore(),
    )

    app = QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName("Nexus")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    apply_dark_theme(app)

    window = MainWindow(chat_service, config_store)
    hotkey = GlobalHotkey(app, window._show_and_raise)
    hotkey.configure(config.global_hotkey_enabled)
    window.set_hotkey_manager(hotkey)
    app.aboutToQuit.connect(hotkey.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
