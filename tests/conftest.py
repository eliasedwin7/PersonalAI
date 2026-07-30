"""Shared fixtures. Every test runs against a temp ~/.personalai so the
real one (and any real conversations in it) is never touched."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from personalai.core import config as config_mod  # noqa: E402


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point every module-level path constant at a temp dir. Patched on
    config_mod itself - conversation.py reads config_mod.CONVERSATIONS_DIR
    dynamically (not via `from ... import NAME`), so this is the one
    place that needs patching for both config and conversation storage."""
    app_dir = tmp_path / ".personalai"
    monkeypatch.setattr(config_mod, "APP_DIR", app_dir)
    monkeypatch.setattr(config_mod, "CONVERSATIONS_DIR", app_dir / "conversations")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", app_dir / "config.json")
    return app_dir
