"""Local topic index; caller validates the enclosing package before serving."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType
from typing import Self

from twincat_knowledge.domain.topics import Topic


def _search_text(topic: Topic) -> str:
    parts = [topic.title]
    for section in topic.sections:
        if section.kind == "table":
            parts.extend(cell for row in section.rows for cell in row)
        else:
            parts.append(
                section.text if section.text is not None else section.code or ""
            )
    return "\n".join(parts)


def create_topic_index(path: Path, topics: Iterable[Topic]) -> int:
    """Build an operator-owned index; not an agent-side import action."""
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.execute(
                "CREATE TABLE topics(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE search_text USING fts5(id UNINDEXED, body)"
            )
            count = 0
            for topic in topics:
                connection.execute(
                    "INSERT INTO topics VALUES (?, ?)",
                    (topic.id, topic.model_dump_json()),
                )
                connection.execute(
                    "INSERT INTO search_text VALUES (?, ?)",
                    (topic.id, _search_text(topic)),
                )
                count += 1
        return count
    finally:
        connection.close()


class TopicIndex:
    """Read-only access to an existing, caller-validated index."""

    def __init__(self, path: Path):
        self._connection = sqlite3.connect(
            path.absolute().as_uri() + "?mode=ro", uri=True
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.close()

    def get_topic(self, topic_id: str) -> Topic | None:
        row = self._connection.execute(
            "SELECT payload FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        return None if row is None else Topic.model_validate_json(row[0])

    def search(self, query: str) -> tuple[Topic, ...]:
        if not query.strip():
            return ()
        literal = '"' + query.replace('"', '""') + '"'
        rows = self._connection.execute(
            "SELECT t.payload FROM search_text JOIN topics t ON t.id=search_text.id "
            "WHERE search_text MATCH ? ORDER BY bm25(search_text), t.id LIMIT 20",
            (literal,),
        )
        return tuple(Topic.model_validate_json(row[0]) for row in rows)
