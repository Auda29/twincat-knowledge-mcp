"""RED-GREEN tests for the source-neutral SQLite topic index."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from twincat_knowledge.corpus.topic_index import (
    TopicIndex,
    TopicIndexBoundsError,
    TopicIndexPathError,
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
        create_topic_index(
            tmp_path / "json.sqlite", [_topic()], max_topic_json_bytes=1
        )
    with pytest.raises(TopicIndexBoundsError):
        create_topic_index(
            tmp_path / "search.sqlite", [_topic()], max_search_text_bytes=1
        )

    assert not (tmp_path / "json.sqlite").exists()
    assert not (tmp_path / "search.sqlite").exists()
