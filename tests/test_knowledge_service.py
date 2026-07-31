from __future__ import annotations

from personalai.services.knowledge_service import KnowledgeStore


def test_index_folder_and_search_relevant_local_text(tmp_path):
    source = tmp_path / "notes"
    source.mkdir()
    (source / "travel.md").write_text(
        "Nexus has a travel plan for Japan with a Kyoto stop.", encoding="utf-8"
    )
    (source / "chores.txt").write_text("Remember to buy groceries.", encoding="utf-8")
    store = KnowledgeStore(tmp_path / "index.json")

    count = store.index_folder(source)
    matches = store.search("Where is the Japan trip going?", limit=1)

    assert count == 2
    assert len(matches) == 1
    assert matches[0].source.endswith("travel.md")
    assert "Kyoto" in matches[0].text


def test_embedding_search_prefers_the_nearest_chunk(tmp_path):
    source = tmp_path / "notes"
    source.mkdir()
    (source / "one.txt").write_text("first topic", encoding="utf-8")
    (source / "two.txt").write_text("second topic", encoding="utf-8")
    store = KnowledgeStore(tmp_path / "index.json")

    def embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "first" in text else [0.0, 1.0] for text in texts]

    store.index_folder(source, embed=embed)
    matches = store.search("second query", limit=1, embed_query=lambda _texts: [[0.0, 1.0]])

    assert matches[0].source.endswith("two.txt")
