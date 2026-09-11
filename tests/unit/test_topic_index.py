"""RED-GREEN tests for the source-neutral SQLite topic index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import twincat_knowledge.corpus.topic_index as topic_index
from twincat_knowledge.corpus.topic_index import (
    TopicIndex,
    TopicIndexBoundsError,
    TopicIndexOpenError,
    TopicIndexPathError,
    TopicIndexSchemaError,
    TopicIndexUnavailableError,
    TopicIndexValidationError,
    create_topic_index,
)
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata


def _topic(
    topic_id: str = "topic-1",
    *,
    language: str = "en",
    library: str = "motion",
    snapshot_id: str = "snapshot-1",
    title: str = "Move absolute",
) -> Topic:
    source = SourceReference(
        source_id="infosys",
        snapshot_id=snapshot_id,
        topic_id=f"help-{topic_id}",
        title=title,
        language=language,
        canonical_url="https://example.invalid/topic",
        locator=f"{library}/{language}/{topic_id}.html",
        content_hash="a" * 64,
    )
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id=f"help-{topic_id}",
        library=library,
        language=language,
        source=source,
        metadata=(TopicMetadata(name="kind", content="function"),),
        sections=(
            Section(
                id=f"{topic_id}-paragraph",
                kind="paragraph",
                text="Moves an axis to an absolute position.",
                source=source.model_copy(
                    update={"section_id": f"{topic_id}-paragraph"}
                ),
            ),
            Section(
                id=f"{topic_id}-code",
                kind="code",
                code="MC_MoveAbsolute(Axis := Axis1);",
                language="st",
                source=source.model_copy(update={"section_id": f"{topic_id}-code"}),
            ),
            Section(
                id=f"{topic_id}-table",
                kind="table",
                rows=(("Input", "Axis"), ("Velocity", "100")),
                source=source.model_copy(update={"section_id": f"{topic_id}-table"}),
            ),
        ),
        image_refs=("images/move.png",),
        help_ids=("ms-xhelp:///?Id=move",),
    )


def test_create_reopen_get_and_search_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "topics.sqlite"
    topic = _topic()

    assert create_topic_index(path, [topic]) == 1

    with TopicIndex(path) as index:
        assert index.get_topic(topic.id) == topic
        assert index.search("absolute") == (topic,)
        assert index.search("MC_MoveAbsolute") == (topic,)
        assert index.search("Velocity") == (topic,)


def test_empty_query_is_explicitly_empty(tmp_path: Path) -> None:
    path = tmp_path / "topics.sqlite"
    create_topic_index(path, [_topic()])

    with TopicIndex(path) as index:
        assert index.search("") == ()
        assert index.search("   ") == ()


def test_missing_id_returns_none_without_snapshot_fallback(tmp_path: Path) -> None:
    path = tmp_path / "topics.sqlite"
    create_topic_index(path, [_topic(snapshot_id="old")])

    with TopicIndex(path) as index:
        assert (
            index.get_topic(
                "topic-1",
            )
            is not None
        )
        assert index.get_topic("topic-1-other-snapshot") is None


def test_create_rejects_existing_regular_file_without_modifying_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "already.sqlite"
    path.write_bytes(b"not an index")

    with pytest.raises(TopicIndexPathError):
        create_topic_index(path, [_topic()])

    assert path.read_bytes() == b"not an index"


def test_create_rejects_existing_symlink_without_modifying_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.sqlite"
    target.write_bytes(b"existing")
    path = tmp_path / "alias.sqlite"
    path.symlink_to(target)

    with pytest.raises(TopicIndexPathError):
        create_topic_index(path, [_topic()])

    assert target.read_bytes() == b"existing"
    assert path.is_symlink()


def test_create_enforces_topic_count_and_cleans_own_artifact(tmp_path: Path) -> None:
    path = tmp_path / "bounded.sqlite"

    with pytest.raises(TopicIndexBoundsError):
        create_topic_index(path, (_topic(str(i)) for i in range(2)), max_topics=1)

    assert not path.exists()
    assert not path.with_name(path.name + "-journal").exists()
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_create_rejects_invalid_model_and_missing_parent_without_artifact(
    tmp_path: Path,
) -> None:
    missing_parent = tmp_path / "missing" / "index.sqlite"

    with pytest.raises(TopicIndexPathError):
        create_topic_index(missing_parent, [_topic()])
    with pytest.raises(TopicIndexValidationError):
        create_topic_index(tmp_path / "invalid.sqlite", [object()])  # type: ignore[list-item]

    assert not missing_parent.parent.exists()
    assert not (tmp_path / "invalid.sqlite").exists()


def test_create_enforces_json_and_search_byte_limits(tmp_path: Path) -> None:
    with pytest.raises(TopicIndexBoundsError):
        create_topic_index(tmp_path / "json.sqlite", [_topic()], max_topic_json_bytes=1)
    with pytest.raises(TopicIndexBoundsError):
        create_topic_index(
            tmp_path / "search.sqlite", [_topic()], max_search_text_bytes=1
        )

    assert not (tmp_path / "json.sqlite").exists()
    assert not (tmp_path / "search.sqlite").exists()


def test_search_filters_and_pagination_are_stable(tmp_path: Path) -> None:
    path = tmp_path / "filtered.sqlite"
    topics = [
        _topic("b", language="en", library="motion", snapshot_id="snap-a"),
        _topic("a", language="en", library="motion", snapshot_id="snap-a"),
        _topic("c", language="de", library="motion", snapshot_id="snap-b"),
        _topic("d", language="en", library="io", snapshot_id="snap-a"),
    ]
    create_topic_index(path, topics)

    with TopicIndex(path) as index:
        assert tuple(topic.id for topic in index.search("absolute")) == (
            "a",
            "b",
            "c",
            "d",
        )
        assert tuple(
            topic.id
            for topic in index.search(
                "absolute", language="en", library="motion", source_snapshot_id="snap-a"
            )
        ) == ("a", "b")
        assert tuple(
            topic.id for topic in index.search("absolute", limit=1, offset=1)
        ) == ("b",)


def test_search_rejects_unbounded_query_and_pagination(tmp_path: Path) -> None:
    path = tmp_path / "limits.sqlite"
    create_topic_index(path, [_topic()])

    with TopicIndex(path) as index:
        with pytest.raises(TopicIndexBoundsError):
            index.search("x" * 2049)
        with pytest.raises(TopicIndexBoundsError):
            index.search("x", limit=21)
        with pytest.raises(TopicIndexBoundsError):
            index.search("x", offset=100_001)
        with pytest.raises(TopicIndexValidationError):
            index.search("x", limit=True)  # type: ignore[arg-type]


def test_search_treats_fts_grammar_as_literal_text(tmp_path: Path) -> None:
    path = tmp_path / "literal.sqlite"
    create_topic_index(
        path,
        [_topic("alpha", title="alpha"), _topic("beta", title="beta")],
    )

    with TopicIndex(path) as index:
        assert index.search('alpha" OR beta') == ()


def test_reader_rejects_missing_and_malformed_indexes(tmp_path: Path) -> None:
    with pytest.raises(TopicIndexOpenError):
        TopicIndex(tmp_path / "missing.sqlite")

    malformed = tmp_path / "malformed.sqlite"
    with sqlite3.connect(malformed) as connection:
        connection.execute("CREATE TABLE anything(value TEXT)")
    with pytest.raises(TopicIndexSchemaError):
        TopicIndex(malformed)


def test_reader_schema_version_is_explicit_and_read_only_without_sidecars(
    tmp_path: Path,
) -> None:
    path = tmp_path / "safe # index.sqlite"
    create_topic_index(path, [_topic()])
    before = path.read_bytes()
    before_names = {entry.name for entry in tmp_path.iterdir()}

    with TopicIndex(path) as index:
        assert index._connection is not None
        assert index._connection.execute("PRAGMA query_only").fetchone() == (1,)
        assert index._connection.execute("PRAGMA trusted_schema").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError):
            index._connection.execute("CREATE TABLE forbidden(value TEXT)")

    assert path.read_bytes() == before
    assert {entry.name for entry in tmp_path.iterdir()} == before_names


def test_fts5_unavailability_is_actionable_and_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "no-fts5.sqlite"

    def unavailable() -> None:
        raise TopicIndexUnavailableError(
            "SQLite FTS5 is required to build/read a topic index"
        )

    monkeypatch.setattr(topic_index, "_check_fts5", unavailable)
    with pytest.raises(TopicIndexUnavailableError, match="FTS5"):
        create_topic_index(path, [_topic()])

    assert not path.exists()


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_failed_build_preserves_unowned_sidecar_names(tmp_path, suffix):
    path = tmp_path / "output.sqlite"
    foreign = path.with_name(path.name + suffix)
    foreign.write_bytes(b"unrelated operator file")
    with pytest.raises(TopicIndexBoundsError):
        create_topic_index(path, [_topic("a"), _topic("b")], max_topics=1)
    assert foreign.exists(), "cleanup deleted a file it did not create"
    assert foreign.read_bytes() == b"unrelated operator file"
    assert not path.exists()


def test_build_does_not_expose_partial_output_or_replace_concurrent_file(tmp_path):
    path = tmp_path / "output.sqlite"

    def topics():
        assert not path.exists(), "partially built database is publicly visible"
        path.write_bytes(b"operator-created concurrent file")
        yield _topic()

    with pytest.raises(TopicIndexPathError):
        create_topic_index(path, topics())
    assert path.read_bytes() == b"operator-created concurrent file"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["output.sqlite"]


def test_empty_search_rejects_closed_reader(tmp_path):
    from twincat_knowledge.corpus.topic_index import TopicIndexError

    path = tmp_path / "closed.sqlite"
    create_topic_index(path, [_topic()])
    with TopicIndex(path) as index:
        assert index.search("  ") == ()
    with pytest.raises(TopicIndexError, match="closed"):
        index.search("  ")


def test_duplicate_ids_raise_controlled_validation_error(tmp_path):
    path = tmp_path / "duplicates.sqlite"
    with pytest.raises(TopicIndexValidationError, match="duplicate"):
        create_topic_index(path, [_topic(), _topic()])
    assert list(tmp_path.iterdir()) == []


def test_index_fsync_uses_writable_handle_for_windows(tmp_path, monkeypatch):
    import os

    real_fsync = os.fsync
    synced = []

    def require_writable_fsync(fd):
        # Windows CRT _commit rejects read-only descriptors. A zero-byte write
        # checks the same prerequisite on POSIX without changing file contents.
        os.write(fd, b"")
        real_fsync(fd)
        synced.append(fd)

    monkeypatch.setattr(topic_index.os, "fsync", require_writable_fsync)
    path = tmp_path / "portable.sqlite"
    assert create_topic_index(path, [_topic()]) == 1
    assert len(synced) == 1
    with TopicIndex(path) as index:
        assert index.get_topic("topic-1") == _topic()
