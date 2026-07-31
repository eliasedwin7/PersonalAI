from __future__ import annotations

import zipfile

from personalai.core.backup import export_backup
from personalai.core.config import ConfigStore
from personalai.core.conversation import ConversationStore


def test_export_backup_contains_config_and_conversations(tmp_path):
    config_store = ConfigStore(tmp_path / "config.json")
    config = config_store.load()
    config.assistant_memory = "Call me Edwin."
    config_store.save(config)
    conversations = ConversationStore(tmp_path / "conversations")
    conversation = conversations.load_or_create("project", "general")
    conversation.append("user", "Remember this chat")
    conversations.save(conversation)

    backup = export_backup(tmp_path / "nexus-data", config_store.path, conversations)

    assert backup.name == "nexus-data.zip"
    with zipfile.ZipFile(backup) as archive:
        assert set(archive.namelist()) == {"config.json", "conversations/project.json"}
        assert "Call me Edwin." in archive.read("config.json").decode()
