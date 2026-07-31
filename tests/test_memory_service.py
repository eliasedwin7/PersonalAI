from __future__ import annotations

from personalai.services.memory_service import merge_approved_memory, parse_suggestions


def test_parse_suggestions_accepts_json_and_removes_duplicates():
    result = parse_suggestions('```json\n["Call the user Edwin", "Prefers concise answers", "call the user edwin"]\n```')
    assert result == ["Call the user Edwin", "Prefers concise answers"]


def test_parse_suggestions_rejects_non_json_response():
    assert parse_suggestions("I suggest remembering their name.") == []


def test_merge_approved_memory_preserves_manual_text_and_deduplicates():
    merged = merge_approved_memory("Writes in Australian English.", [
        "Prefers concise answers", "prefers concise answers",
    ])
    assert merged.splitlines() == [
        "Writes in Australian English.",
        "- Prefers concise answers",
    ]
