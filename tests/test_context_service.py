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


# ---- folder context ---------------------------------------------------------------

def test_load_context_folder_combines_eligible_files(tmp_path):
    (tmp_path / "chapter1.md").write_text("Chapter one content.", encoding="utf-8")
    (tmp_path / "chapter2.md").write_text("Chapter two content.", encoding="utf-8")
    (tmp_path / "notes.py").write_text("# a code note", encoding="utf-8")
    (tmp_path / "cover.png").write_bytes(b"not text, must be skipped")

    block = context_service.load_context_folder(tmp_path, char_limit=100_000)
    assert "chapter1.md" in block
    assert "Chapter one content." in block
    assert "chapter2.md" in block
    assert "Chapter two content." in block
    assert "notes.py" in block
    assert "cover.png" not in block  # non-text extension excluded


def test_load_context_folder_sorted_deterministically(tmp_path):
    (tmp_path / "b.md").write_text("B", encoding="utf-8")
    (tmp_path / "a.md").write_text("A", encoding="utf-8")
    block = context_service.load_context_folder(tmp_path, char_limit=100_000)
    assert block.index("a.md") < block.index("b.md")


def test_load_context_folder_recurses_subfolders(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.md").write_text("deep content", encoding="utf-8")
    block = context_service.load_context_folder(tmp_path, char_limit=100_000)
    assert "deep content" in block
    assert "sub" in block  # relative path shown, not just the bare filename


def test_load_context_folder_truncates_combined_keeping_the_end(tmp_path):
    (tmp_path / "a.md").write_text("A" * 100, encoding="utf-8")
    (tmp_path / "b.md").write_text("B" * 100 + "END_MARKER", encoding="utf-8")
    block = context_service.load_context_folder(tmp_path, char_limit=50)
    assert "truncated" in block
    assert "END_MARKER" in block
    assert "A" * 50 not in block


def test_load_context_folder_missing_raises(tmp_path):
    with pytest.raises(UserFacingError, match="not found"):
        context_service.load_context_folder(tmp_path / "nope", char_limit=1000)


def test_load_context_folder_no_eligible_files_raises(tmp_path):
    (tmp_path / "image.png").write_bytes(b"binary")
    with pytest.raises(UserFacingError, match="No text files"):
        context_service.load_context_folder(tmp_path, char_limit=1000)


def test_load_context_folder_respects_file_count_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(context_service, "MAX_FILES_FROM_FOLDER", 2)
    for i in range(5):
        (tmp_path / f"f{i}.md").write_text(f"content {i}", encoding="utf-8")
    block = context_service.load_context_folder(tmp_path, char_limit=100_000)
    assert "2 file(s)" in block


def test_load_context_path_dispatches_file_vs_folder(tmp_path):
    file_path = tmp_path / "single.md"
    file_path.write_text("single file content", encoding="utf-8")
    assert "single file content" in context_service.load_context_path(file_path, 10_000)

    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.md").write_text("folder content", encoding="utf-8")
    assert "folder content" in context_service.load_context_path(folder, 10_000)
