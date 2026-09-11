"""Bounded, immutable SQLite topic index for caller-validated packages."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Self

from twincat_knowledge.domain.topics import Topic

SCHEMA_VERSION = 1
MAX_TOPICS = 100_000
MAX_TOPIC_JSON_BYTES = 1_048_576
MAX_SEARCH_TEXT_BYTES = 1_048_576
MAX_QUERY_BYTES = 2048
MAX_SEARCH_LIMIT = 20
MAX_SEARCH_OFFSET = 100_000


class TopicIndexError(RuntimeError):
    """Base class for controlled topic-index failures."""


class TopicIndexPathError(TopicIndexError):
    """The output path is not a new file in an existing directory."""


class TopicIndexValidationError(TopicIndexError, ValueError):
    """A supplied topic or option has an invalid type or value."""


class TopicIndexBoundsError(TopicIndexValidationError):
    """A supplied count, text, query, or pagination value exceeds a limit."""


class TopicIndexUnavailableError(TopicIndexError):
    """The runtime cannot provide the required SQLite FTS5 feature."""


class TopicIndexOpenError(TopicIndexError):
    """An index could not be opened in read-only mode."""


class TopicIndexSchemaError(TopicIndexError):
    """An existing file is not a supported topic-index schema."""


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


def _check_fts5() -> None:
    """Fail explicitly when this Python's SQLite has no FTS5 support."""
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE VIRTUAL TABLE topic_index_fts5_probe USING fts5(body)"
        )
    except sqlite3.Error as exc:
        raise TopicIndexUnavailableError(
            "SQLite FTS5 is required to build/read a topic index; "
            "install Python with SQLite compiled with FTS5 support"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def _check_bound(value: object, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TopicIndexValidationError(f"{name} must be an integer")
    if value < 1 or value > maximum:
        raise TopicIndexBoundsError(f"{name} must be between 1 and {maximum}")
    return value


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _validate_text_size(value: str, name: str, maximum: int) -> None:
    if _utf8_size(value) > maximum:
        raise TopicIndexBoundsError(f"{name} exceeds the {maximum}-byte UTF-8 limit")


def create_topic_index(
    path: Path,
    topics: Iterable[Topic],
    *,
    max_topics: int = MAX_TOPICS,
    max_topic_json_bytes: int = MAX_TOPIC_JSON_BYTES,
    max_search_text_bytes: int = MAX_SEARCH_TEXT_BYTES,
) -> int:
    """Build privately, then publish a complete new file without replacement."""
    _check_fts5()
    _check_bound(max_topics, "max_topics", MAX_TOPICS)
    _check_bound(max_topic_json_bytes, "max_topic_json_bytes", MAX_TOPIC_JSON_BYTES)
    _check_bound(max_search_text_bytes, "max_search_text_bytes", MAX_SEARCH_TEXT_BYTES)
    output = Path(path).absolute()
    if not output.parent.is_dir():
        raise TopicIndexPathError("index parent directory must already exist")
    if output.exists() or output.is_symlink():
        raise TopicIndexPathError("index output path must not already exist")
    # SQLite owns sidecars only inside this private build directory. Never
    # delete similarly named files from the operator's output directory.
    with TemporaryDirectory(prefix=".topic-index-", dir=output.parent) as directory:
        staging = Path(directory) / "index.sqlite"
        count = _write_database(
            staging, topics, max_topics, max_topic_json_bytes, max_search_text_bytes
        )
        staging.chmod(0o600)
        # Windows CRT _commit (os.fsync) requires a writable descriptor.
        with staging.open("r+b") as handle:
            os.fsync(handle.fileno())
        try:
            # Same-filesystem hard link is atomic and refuses an existing target.
            # No rename/replace fallback: those can overwrite a concurrent file.
            os.link(staging, output)
        except FileExistsError as exc:
            raise TopicIndexPathError(
                "index output path must not already exist"
            ) from exc
        except OSError as exc:
            raise TopicIndexPathError(
                "could not publish index; output filesystem must support hard links"
            ) from exc
        return count


def _write_database(
    staging: Path,
    topics: Iterable[Topic],
    max_topics: int,
    max_topic_json_bytes: int,
    max_search_text_bytes: int,
) -> int:
    connection = sqlite3.connect(staging)
    try:
        connection.isolation_level = None
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute(
            "CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO index_meta VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute(
            "CREATE TABLE topics ("
            "id TEXT PRIMARY KEY, language TEXT NOT NULL, library TEXT NOT NULL, "
            "source_snapshot_id TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE search_text USING fts5(id UNINDEXED, body)"
        )

        count = 0
        for topic in topics:
            if not isinstance(topic, Topic):
                raise TopicIndexValidationError("topics must contain only Topic models")
            count += 1
            if count > max_topics:
                raise TopicIndexBoundsError(
                    f"topic count exceeds the {max_topics}-topic limit"
                )
            payload = topic.model_dump_json()
            body = _search_text(topic)
            _validate_text_size(payload, "topic JSON", max_topic_json_bytes)
            _validate_text_size(body, "topic search text", max_search_text_bytes)
            try:
                connection.execute(
                    "INSERT INTO topics VALUES (?, ?, ?, ?, ?)",
                    (
                        topic.id,
                        topic.language,
                        topic.library,
                        topic.source.snapshot_id,
                        payload,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise TopicIndexValidationError(
                    "duplicate or invalid topic record"
                ) from exc
            connection.execute(
                "INSERT INTO search_text VALUES (?, ?)", (topic.id, body)
            )
        connection.execute("COMMIT")
        return count
    finally:
        # Close before TemporaryDirectory cleanup, including on Windows.
        connection.close()


def _readonly_uri(path: Path) -> str:
    try:
        absolute = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise TopicIndexOpenError(f"topic index does not exist: {path}") from exc
    return f"{absolute.as_uri()}?mode=ro"


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        meta_version = connection.execute(
            "SELECT value FROM index_meta WHERE key = 'schema_version'"
        ).fetchone()
        topics_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(topics)")
        }
        search_kind = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'search_text'"
        ).fetchone()
        search_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'search_text'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise TopicIndexSchemaError(
            "topic index schema is missing or malformed; rebuild the index"
        ) from exc
    if (
        user_version != SCHEMA_VERSION
        or meta_version is None
        or meta_version[0] != str(SCHEMA_VERSION)
        or topics_columns
        != {"id", "language", "library", "source_snapshot_id", "payload"}
        or search_kind != ("table",)
        or search_sql is None
        or "using fts5" not in search_sql[0].lower()
    ):
        raise TopicIndexSchemaError(
            f"unsupported topic index schema; expected version {SCHEMA_VERSION}"
        )


def _configure_readonly(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("PRAGMA query_only = ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        connection.execute("PRAGMA trusted_schema = OFF")
        trusted_schema = connection.execute("PRAGMA trusted_schema").fetchone()
    except sqlite3.Error as exc:
        raise TopicIndexUnavailableError(
            "SQLite query_only/trusted_schema protections are unavailable"
        ) from exc
    if query_only != (1,) or trusted_schema != (0,):
        raise TopicIndexUnavailableError(
            "SQLite query_only/trusted_schema protections could not be enabled"
        )


class TopicIndex:
    """Read-only access to an existing, caller-validated index."""

    def __init__(self, path: Path):
        _check_fts5()
        self._connection: sqlite3.Connection | None = None
        try:
            self._connection = sqlite3.connect(_readonly_uri(Path(path)), uri=True)
            _configure_readonly(self._connection)
            _validate_schema(self._connection)
        except TopicIndexError:
            if self._connection is not None:
                self._connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if self._connection is not None:
                self._connection.close()
            raise TopicIndexOpenError(
                f"could not open topic index read-only: {path}"
            ) from exc

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise TopicIndexError("topic index is closed")
        return self._connection

    def iter_topics(
        self, *, max_topics: int = MAX_TOPICS
    ) -> AbstractContextManager[Iterator[Topic]]:
        """Stream a bounded canonical-ID-ordered topic view.

        The cursor is owned by this context manager, not by the returned
        iterator.  SQLite reads at most ``max_topics + 1`` rows: the sentinel
        proves the actual count is within the caller's bound before its payload
        is parsed.  This API is intended for trusted indexes already verified by
        the package loader; direct callers still receive row-size and model
        validation before a ``Topic`` is yielded.
        """
        limit = _check_bound(max_topics, "max_topics", MAX_TOPICS)
        return self._iter_topics_context(limit)

    @contextmanager
    def _iter_topics_context(self, limit: int) -> Iterator[Iterator[Topic]]:
        connection = self._connection_or_raise()
        cursor: sqlite3.Cursor | None = None
        try:
            cursor = connection.execute(
                "SELECT payload, length(CAST(payload AS BLOB)) "
                "FROM topics ORDER BY id ASC LIMIT ?",
                (limit + 1,),
            )

            def stream() -> Iterator[Topic]:
                count = 0
                for payload, payload_bytes in cursor:
                    count += 1
                    if count > limit:
                        raise TopicIndexBoundsError(
                            f"topic count exceeds the {limit}-topic limit"
                        )
                    if (
                        not isinstance(payload, str)
                        or not isinstance(payload_bytes, int)
                        or payload_bytes < 0
                        or payload_bytes > MAX_TOPIC_JSON_BYTES
                    ):
                        raise TopicIndexValidationError(
                            "topic payload exceeds its safe byte bound"
                        )
                    try:
                        topic = Topic.model_validate_json(payload)
                    except Exception:
                        raise TopicIndexValidationError(
                            "topic payload is invalid"
                        ) from None
                    yield topic

            yield stream()
        except sqlite3.Error as exc:
            raise TopicIndexError("topic index iteration failed") from exc
        finally:
            if cursor is not None:
                cursor.close()

    def get_topic(self, topic_id: str) -> Topic | None:
        if not isinstance(topic_id, str):
            raise TopicIndexValidationError("topic_id must be a string")
        row = (
            self._connection_or_raise()
            .execute("SELECT payload FROM topics WHERE id = ?", (topic_id,))
            .fetchone()
        )
        return None if row is None else Topic.model_validate_json(row[0])

    def validate_topic_contents(self, topics: tuple[Topic, ...]) -> None:
        """Cross-check caller-validated topics, filters and canonical FTS rows.

        Scan FTS rows once rather than doing an unindexed lookup per topic.
        This validates logical rows, not SQLite's private FTS shadow encoding.
        """
        connection = self._connection_or_raise()
        if not isinstance(topics, tuple) or len(topics) > MAX_TOPICS:
            raise TopicIndexValidationError("invalid expected topic collection")
        expected: dict[str, Topic] = {}
        for topic in topics:
            if not isinstance(topic, Topic) or topic.id in expected:
                raise TopicIndexValidationError("invalid expected topic collection")
            expected[topic.id] = topic
        try:
            for table in ("topics", "search_text"):
                count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[
                    0
                ]
                if count != len(expected):
                    raise TopicIndexValidationError("index topic count mismatch")
            for topic in topics:
                filters = connection.execute(
                    "SELECT language, library, source_snapshot_id FROM topics "
                    "WHERE id = ? AND length(CAST(language AS BLOB)) <= ? "
                    "AND length(CAST(library AS BLOB)) <= ? "
                    "AND length(CAST(source_snapshot_id AS BLOB)) <= ? "
                    "AND length(CAST(payload AS BLOB)) <= ?",
                    (
                        topic.id,
                        MAX_QUERY_BYTES,
                        MAX_QUERY_BYTES,
                        MAX_QUERY_BYTES,
                        MAX_TOPIC_JSON_BYTES,
                    ),
                ).fetchone()
                if filters != (topic.language, topic.library, topic.source.snapshot_id):
                    raise TopicIndexValidationError("index filter fields mismatch")
                if self.get_topic(topic.id) != topic:
                    raise TopicIndexValidationError("index topic payload mismatch")
            rows = connection.execute(
                "SELECT CASE WHEN length(CAST(id AS BLOB)) <= 256 THEN id END, "
                "CASE WHEN length(CAST(body AS BLOB)) <= ? THEN body END "
                "FROM search_text",
                (MAX_SEARCH_TEXT_BYTES,),
            )
            try:
                for topic_id, body in rows:
                    matched = expected.pop(topic_id, None)
                    if matched is None or body != _search_text(matched):
                        raise TopicIndexValidationError("index search rows mismatch")
            finally:
                # An early rejection leaves a live statement in the traceback.
                # Finalize it before connection close and Windows cache removal.
                rows.close()
            if expected:
                raise TopicIndexValidationError("index search rows missing")
        except (sqlite3.Error, UnicodeError) as exc:
            raise TopicIndexValidationError("index contents are invalid") from exc

    def search(
        self,
        query: str,
        *,
        language: str | None = None,
        library: str | None = None,
        source_snapshot_id: str | None = None,
        limit: int = MAX_SEARCH_LIMIT,
        offset: int = 0,
    ) -> tuple[Topic, ...]:
        if not isinstance(query, str):
            raise TopicIndexValidationError("query must be a string")
        if _utf8_size(query) > MAX_QUERY_BYTES:
            raise TopicIndexBoundsError(
                f"query exceeds the {MAX_QUERY_BYTES}-byte UTF-8 limit"
            )
        if "\x00" in query:
            raise TopicIndexValidationError("query must not contain NUL")
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise TopicIndexValidationError("offset must be an integer")
        if offset < 0 or offset > MAX_SEARCH_OFFSET:
            raise TopicIndexBoundsError(
                f"offset must be between 0 and {MAX_SEARCH_OFFSET}"
            )
        _check_bound(limit, "limit", MAX_SEARCH_LIMIT)
        filters: list[str] = []
        values: list[str | int] = []
        for column, value in (
            ("language", language),
            ("library", library),
            ("source_snapshot_id", source_snapshot_id),
        ):
            if value is not None:
                if not isinstance(value, str):
                    raise TopicIndexValidationError(f"{column} must be a string")
                if not value or _utf8_size(value) > MAX_QUERY_BYTES:
                    raise TopicIndexBoundsError(f"{column} is empty or too large")
                filters.append(f"t.{column} = ?")
                values.append(value)
        connection = self._connection_or_raise()
        if not query.strip():
            return ()
        literal = '"' + query.replace('"', '""') + '"'
        where = " AND ".join(filters)
        if where:
            where = " AND " + where
        rows = connection.execute(
            "SELECT t.payload FROM search_text "
            "JOIN topics AS t ON t.id = search_text.id "
            "WHERE search_text MATCH ?"
            + where
            + " ORDER BY bm25(search_text) ASC, t.id ASC LIMIT ? OFFSET ?",
            (literal, *values, limit, offset),
        )
        return tuple(Topic.model_validate_json(row[0]) for row in rows)


__all__ = [
    "MAX_QUERY_BYTES",
    "MAX_SEARCH_LIMIT",
    "MAX_SEARCH_OFFSET",
    "MAX_SEARCH_TEXT_BYTES",
    "MAX_TOPIC_JSON_BYTES",
    "MAX_TOPICS",
    "SCHEMA_VERSION",
    "TopicIndex",
    "TopicIndexBoundsError",
    "TopicIndexError",
    "TopicIndexOpenError",
    "TopicIndexPathError",
    "TopicIndexSchemaError",
    "TopicIndexUnavailableError",
    "TopicIndexValidationError",
    "create_topic_index",
]
