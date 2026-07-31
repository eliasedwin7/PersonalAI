"""Private on-device knowledge indexing with embedding and lexical retrieval."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from personalai.core import config as config_mod

TEXT_SUFFIXES = {".txt", ".md", ".rst", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv", ".html", ".css"}
CHUNK_CHARS = 1_200
CHUNK_OVERLAP = 180
MAX_FILE_CHARS = 80_000


@dataclass
class KnowledgeChunk:
    source: str
    text: str
    embedding: list[float] | None = None


class KnowledgeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_mod.APP_DIR / "knowledge" / "index.json"
        self.chunks: list[KnowledgeChunk] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.chunks = [KnowledgeChunk(**item) for item in raw.get("chunks", [])]
        except (OSError, json.JSONDecodeError, TypeError):
            self.chunks = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"chunks": [asdict(chunk) for chunk in self.chunks]}, ensure_ascii=False), encoding="utf-8")

    def index_folder(self, folder: Path, embed: Callable[[list[str]], list[list[float]]] | None = None) -> int:
        folder = folder.expanduser().resolve()
        chunks: list[KnowledgeChunk] = []
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
            except OSError:
                continue
            for chunk in _chunk_text(text):
                chunks.append(KnowledgeChunk(str(path), chunk))
        if embed and chunks:
            vectors = embed([chunk.text for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=False):
                chunk.embedding = vector
        existing = [chunk for chunk in self.chunks if not chunk.source.startswith(str(folder))]
        self.chunks = existing + chunks
        self.save()
        return len(chunks)

    def clear(self) -> None:
        self.chunks = []
        self.save()

    def search(self, query: str, limit: int = 4,
               embed_query: Callable[[list[str]], list[list[float]]] | None = None) -> list[KnowledgeChunk]:
        if not self.chunks:
            return []
        query_vector = None
        if embed_query and any(chunk.embedding for chunk in self.chunks):
            try:
                query_vector = embed_query([query])[0]
            except (IndexError, OSError, ValueError):
                query_vector = None
        if query_vector:
            ranked = sorted(self.chunks, key=lambda chunk: _cosine(query_vector, chunk.embedding or []), reverse=True)
        else:
            terms = set(re.findall(r"\w+", query.casefold()))
            ranked = sorted(self.chunks, key=lambda chunk: _lexical_score(terms, chunk.text), reverse=True)
        return [chunk for chunk in ranked[:limit] if chunk.text]


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + CHUNK_CHARS // 2:
                end = boundary
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _lexical_score(terms: set[str], text: str) -> int:
    words = set(re.findall(r"\w+", text.casefold()))
    return len(terms & words)


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0
