from __future__ import annotations

from personalai.core.config import MemoryEntry
from personalai.services.memory_service import (
    add_approved_entries,
    merge_approved_memory,
    parse_suggestions,
)


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


def test_add_approved_entries_keeps_individual_history_and_deduplicates():
    entries = [MemoryEntry("Call the user Edwin.")]

    add_approved_entries(entries, ["Prefers concise answers.", "call the user edwin."])

    assert [entry.text for entry in entries] == ["Call the user Edwin.", "Prefers concise answers."]
    assert entries[1].source == "Approved from chat"
    assert entries[1].category == "preferences"
