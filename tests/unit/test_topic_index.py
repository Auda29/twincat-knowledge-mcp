"""RED-GREEN tests for the source-neutral SQLite topic index."""

from __future__ import annotations

from pathlib import Path

from twincat_knowledge.corpus.topic_index import TopicIndex, create_topic_index
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
