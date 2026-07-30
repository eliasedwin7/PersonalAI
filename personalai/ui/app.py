"""GUI bootstrap. Launched via `myai gui` (cli.py imports this lazily so
plain CLI usage never pays the Qt import cost)."""

from __future__ import annotations

import sys

from personalai.core import config as config_mod
from personalai.core.conversation import ConversationStore
from personalai.services.backend_factory import build_llm_client
from personalai.services.chat_service import ChatService


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from personalai.ui.main_window import MainWindow
    from personalai.ui.theme import apply_dark_theme

    config_mod.ensure_dirs()
    config_store = config_mod.ConfigStore()
    config = config_store.load()
    chat_service = ChatService(
        config=config,
        store=ConversationStore(),
        client=build_llm_client(config),
    )

    app = QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName("PersonalAI")
    apply_dark_theme(app)

    window = MainWindow(chat_service, config_store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
