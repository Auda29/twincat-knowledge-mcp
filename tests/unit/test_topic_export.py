"""RED-GREEN tests for transparent bounded Topic JSONL export."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from twincat_knowledge.corpus.topic_export import (
    ExportSummary,
    read_topic_export,
    write_topic_export,
)
from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.ingest.infosys import InfoSysSection, InfoSysTopic
from twincat_knowledge.ingest.normalize import normalize_infosys


def _snapshot() -> SourceSnapshot:
    return SourceSnapshot(
        source_id="infosys",
        snapshot_id="snapshot-1",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language="en",
        content_hash="b" * 64,
        rights_reference="operator-approved-fixture",
        parser_version="reader-1",
    )


def _topic(topic_id: str = "topic-1") -> Topic:
    title = "Move \N{SNOWMAN}"
    source = SourceReference(
        source_id="infosys",
        snapshot_id="snapshot-1",
        topic_id=f"help-{topic_id}",
        title=title,
        language="en",
        canonical_url="https://example.invalid/topic",
        locator=f"motion/en/{topic_id}.html",
        content_hash="a" * 64,
    )
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id=f"help-{topic_id}",
        library="motion",
        language="en",
        source=source,
        metadata=(
            TopicMetadata(
                name="ordered",
                content="first",
                attributes=(("x", "1"), ("x", "2")),
            ),
            TopicMetadata(name="ordered", content="second"),
        ),
        sections=(
            Section(
                id=f"{topic_id}-code",
                kind="code",
                code="IF x THEN\n    y := 'line';\nEND_IF;",
                language="st",
                source=source.model_copy(update={"section_id": f"{topic_id}-code"}),
            ),
        ),
        image_refs=("images/a.png",),
        help_ids=("help-a", "help-b"),
    )


def test_normalized_topics_round_trip_with_raw_sha(tmp_path: Path) -> None:
    raw = normalize_infosys(
        [
            InfoSysTopic(
                title="Move",
                topic_id="help.move",
                language="en",
                library="motion",
                source=SourceReference(
                    source_id="infosys",
                    snapshot_id="snapshot-1",
                    topic_id="help.move",
                    title="Move",
                    language="en",
                    locator="motion/en/move.html",
                    content_hash="a" * 64,
                ),
                sections=(InfoSysSection(kind="code", code="x := 1;\n"),),
            )
        ],
        [_snapshot()],
    )
    path = tmp_path / "topics.jsonl"

    summary = write_topic_export(path, raw)

    assert isinstance(summary, ExportSummary)
    assert summary.count == 1
    assert summary.bytes == path.stat().st_size
    assert summary.sha256 == __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    assert read_topic_export(path) == raw
