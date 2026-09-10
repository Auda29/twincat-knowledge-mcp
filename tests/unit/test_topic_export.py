"""RED-GREEN tests for transparent bounded Topic JSONL export."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import twincat_knowledge.corpus.topic_export as topic_export
from twincat_knowledge.corpus.topic_export import (
    ExportSummary,
    TopicExportBoundsError,
    TopicExportError,
    TopicExportPathError,
    TopicExportValidationError,
    read_topic_export,
    write_topic_export,
)
from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.ingest.infosys import (
    InfoSysReader,
    InfoSysSection,
    InfoSysTopic,
)
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


def _archive(html: str) -> BytesIO:
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("motion/1033/move.html", html)
    payload.seek(0)
    return payload


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
    assert summary.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert read_topic_export(path) == raw


def test_reader_normalizer_export_reload_preserves_real_synthetic_fixture(
    tmp_path: Path,
) -> None:
    html = """<html xmlns="http://www.w3.org/1999/xhtml"><head>
    <title>Move \N{SNOWMAN}</title>
    <meta name="repeat" content="one" data-extra="a" />
    <meta name="repeat" content="two" data-extra="b" />
    </head><body><p>Before</p><pre class="language-st">x := 1;
</pre><table><tr><td>Input</td></tr></table></body></html>"""
    read_topics = InfoSysReader(
        _archive(html), source_id="synthetic", snapshot_id="fixture-1"
    ).read()
    normalized = normalize_infosys(
        read_topics,
        [
            _snapshot().model_copy(
                update={"source_id": "synthetic", "snapshot_id": "fixture-1"}
            )
        ],
    )
    path = tmp_path / "reader-normalizer.jsonl"

    write_topic_export(path, normalized)

    assert read_topic_export(path) == normalized


def test_export_is_exact_ordered_jsonl_and_empty_export_is_valid(
    tmp_path: Path,
) -> None:
    topics = (_topic("first"), _topic("second"))
    path = tmp_path / "topics.jsonl"

    summary = write_topic_export(path, topics)
    expected = b"".join(
        (topic.model_dump_json() + "\n").encode("utf-8") for topic in topics
    )

    assert path.read_bytes() == expected
    assert summary == ExportSummary(
        2, len(expected), hashlib.sha256(expected).hexdigest()
    )
    assert tuple(topic.id for topic in read_topic_export(path)) == ("first", "second")

    empty = tmp_path / "empty.jsonl"
    empty_summary = write_topic_export(empty, ())
    assert empty.read_bytes() == b""
    assert empty_summary == ExportSummary(0, 0, hashlib.sha256(b"").hexdigest())
    assert read_topic_export(empty) == ()


def test_reader_accepts_one_final_record_without_lf(tmp_path: Path) -> None:
    path = tmp_path / "final.jsonl"
    path.write_bytes(_topic().model_dump_json().encode("utf-8"))

    assert read_topic_export(path) == (_topic(),)


def test_duplicate_and_invalid_topic_inputs_never_publish(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.jsonl"
    with pytest.raises(TopicExportValidationError, match="duplicate"):
        write_topic_export(duplicate, (_topic(), _topic()))
    assert not duplicate.exists()

    invalid = tmp_path / "invalid.jsonl"
    with pytest.raises(TopicExportValidationError, match="Topic"):
        write_topic_export(invalid, [object()])  # type: ignore[list-item]
    assert not invalid.exists()

    duplicate.write_bytes(((_topic().model_dump_json() + "\n") * 2).encode("utf-8"))
    with pytest.raises(TopicExportValidationError, match="duplicate"):
        read_topic_export(duplicate)


def test_reader_rejects_malformed_provenance_and_multiple_json(tmp_path: Path) -> None:
    topic_data = json.loads(_topic().model_dump_json())
    topic_data["title"] = "changed"
    malformed_provenance = tmp_path / "provenance.jsonl"
    malformed_provenance.write_text(json.dumps(topic_data), encoding="utf-8")

    with pytest.raises(TopicExportValidationError, match="invalid topic JSON") as error:
        read_topic_export(malformed_provenance)
    assert str(malformed_provenance) not in str(error.value)
    assert "changed" not in str(error.value)

    multiple = tmp_path / "multiple.jsonl"
    record = _topic().model_dump_json().encode("utf-8")
    multiple.write_bytes(record + b" " + record)
    with pytest.raises(TopicExportValidationError, match="invalid topic JSON"):
        read_topic_export(multiple)

    trailing = tmp_path / "trailing.jsonl"
    trailing.write_bytes(record + b" trailing")
    with pytest.raises(TopicExportValidationError, match="invalid topic JSON"):
        read_topic_export(trailing)


@pytest.mark.parametrize("contents", [b"\n", b"\r\n", b" \n"])
def test_reader_rejects_blank_lines(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "blank.jsonl"
    path.write_bytes(contents)

    with pytest.raises(TopicExportValidationError, match="blank"):
        read_topic_export(path)


@pytest.mark.parametrize(
    "contents, message", [(b"\xff", "UTF-8"), (b"\xef\xbb\xbf{}", "BOM")]
)
def test_reader_rejects_invalid_utf8_and_bom(
    tmp_path: Path, contents: bytes, message: str
) -> None:
    path = tmp_path / "encoding.jsonl"
    path.write_bytes(contents)

    with pytest.raises(TopicExportValidationError, match=message):
        read_topic_export(path)


def test_record_and_total_byte_limits_are_independent(tmp_path: Path) -> None:
    topic = _topic()
    record_bytes = len(topic.model_dump_json().encode("utf-8"))

    with pytest.raises(TopicExportBoundsError, match="record"):
        write_topic_export(
            tmp_path / "record.jsonl", [topic], max_record_bytes=record_bytes - 1
        )
    with pytest.raises(TopicExportBoundsError, match="export"):
        write_topic_export(
            tmp_path / "total.jsonl", [topic], max_total_bytes=record_bytes
        )

    source = tmp_path / "valid.jsonl"
    write_topic_export(source, [topic])
    with pytest.raises(TopicExportBoundsError, match="record"):
        read_topic_export(source, max_record_bytes=record_bytes - 1)
    with pytest.raises(TopicExportBoundsError, match="export"):
        read_topic_export(source, max_total_bytes=record_bytes)


def test_topic_limit_consumes_only_one_record_past_bound(tmp_path: Path) -> None:
    consumed = 0

    def topics() -> Iterator[Topic]:
        nonlocal consumed
        while True:
            consumed += 1
            yield _topic(str(consumed))

    with pytest.raises(TopicExportBoundsError, match="topic count"):
        write_topic_export(tmp_path / "bounded.jsonl", topics(), max_topics=2)
    assert consumed == 3


def test_reader_topic_limit_is_checked_before_materializing_more_models(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bounded-read.jsonl"
    write_topic_export(path, [_topic("one"), _topic("two"), _topic("three")])

    with pytest.raises(TopicExportBoundsError, match="topic count"):
        read_topic_export(path, max_topics=2)


def test_generator_failure_cleans_only_private_build_area(tmp_path: Path) -> None:
    foreign = tmp_path / "operator.txt"
    foreign.write_bytes(b"keep")

    def topics() -> Iterator[Topic]:
        yield _topic()
        raise RuntimeError("private generator details")

    with pytest.raises(TopicExportError) as error:
        write_topic_export(tmp_path / "failed.jsonl", topics())
    assert "private generator details" not in str(error.value)
    assert foreign.read_bytes() == b"keep"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["operator.txt"]


def test_existing_regular_and_dangling_symlink_are_preserved(tmp_path: Path) -> None:
    regular = tmp_path / "regular.jsonl"
    regular.write_bytes(b"existing")
    with pytest.raises(TopicExportPathError):
        write_topic_export(regular, [_topic()])
    assert regular.read_bytes() == b"existing"

    dangling = tmp_path / "dangling.jsonl"
    dangling.symlink_to(tmp_path / "missing-target")
    with pytest.raises(TopicExportPathError):
        write_topic_export(dangling, [_topic()])
    assert dangling.is_symlink()


def test_concurrent_target_is_never_replaced(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.jsonl"

    def topics() -> Iterator[Topic]:
        path.write_bytes(b"operator-created")
        yield _topic()

    with pytest.raises(TopicExportPathError):
        write_topic_export(path, topics())
    assert path.read_bytes() == b"operator-created"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["concurrent.jsonl"]


def test_unsupported_hardlink_filesystem_is_a_clear_error(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "unsupported.jsonl"

    def no_hardlink(*args, **kwargs):
        raise OSError("hard links are unavailable")

    monkeypatch.setattr(topic_export.os, "link", no_hardlink)
    with pytest.raises(TopicExportPathError, match="hard links"):
        write_topic_export(path, [_topic()])
    assert not path.exists()


@pytest.mark.parametrize("name", ["max_topics", "max_total_bytes", "max_record_bytes"])
def test_limits_reject_bool_and_above_hard_max(tmp_path: Path, name: str) -> None:
    kwargs = {name: True}
    with pytest.raises(TopicExportValidationError):
        write_topic_export(tmp_path / "bool.jsonl", [], **kwargs)  # type: ignore[arg-type]
    kwargs = {name: getattr(topic_export, name.upper()) + 1}
    with pytest.raises(TopicExportBoundsError):
        read_topic_export(tmp_path / "missing.jsonl", **kwargs)  # type: ignore[arg-type]


def test_reader_has_no_side_effects(tmp_path: Path) -> None:
    path = tmp_path / "topics.jsonl"
    write_topic_export(path, [_topic()])
    before_bytes = path.read_bytes()
    before_names = sorted(item.name for item in tmp_path.iterdir())

    assert read_topic_export(path) == (_topic(),)

    assert path.read_bytes() == before_bytes
    assert sorted(item.name for item in tmp_path.iterdir()) == before_names
