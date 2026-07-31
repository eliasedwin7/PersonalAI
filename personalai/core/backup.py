"""Portable backups of Nexus configuration, conversations, and memory."""

from __future__ import annotations

import zipfile
from pathlib import Path

from personalai.core.conversation import ConversationStore


def export_backup(destination: Path, config_path: Path, conversations: ConversationStore) -> Path:
    """Write a zip archive containing the human-readable Nexus data files."""
    destination = destination.expanduser()
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if config_path.exists():
            archive.write(config_path, "config.json")
        for path in sorted(conversations.directory.glob("*.json")):
            archive.write(path, f"conversations/{path.name}")
    return destination
