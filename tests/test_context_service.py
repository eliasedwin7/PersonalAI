from __future__ import annotations

import pytest

from personalai.core.errors import UserFacingError
from personalai.services import context_service


def test_load_context_includes_filename_and_content(tmp_path):
    path = tmp_path / "STORY_OUTLINE.md"
    path.write_text("Chapter 3: Kellan returns to the capital.", encoding="utf-8")
    block = context_service.load_context(path, char_limit=10000)
    assert "STORY_OUTLINE.md" in block
    assert "Kellan returns to the capital" in block
    assert "truncated" not in block


def test_load_context_truncates_long_files_keeping_the_end(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("A" * 100 + "END_MARKER", encoding="utf-8")
    block = context_service.load_context(path, char_limit=20)
    assert "truncated" in block
    assert "END_MARKER" in block
    assert "A" * 100 not in block  # the head was cut, not kept


def test_load_context_missing_file_raises(tmp_path):
    with pytest.raises(UserFacingError):
        context_service.load_context(tmp_path / "nope.txt", char_limit=1000)


def test_build_user_message_no_context_passthrough():
    assert context_service.build_user_message("hello", []) == "hello"


def test_build_user_message_prepends_context_blocks():
    result = context_service.build_user_message("continue the scene", ["BLOCK_A", "BLOCK_B"])
    assert result.startswith("BLOCK_A")
    assert "BLOCK_B" in result
    assert result.endswith("continue the scene")
