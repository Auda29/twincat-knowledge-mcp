"""Strict incremental TDD coverage for pre-publication topic validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_export import read_topic_export, write_topic_export
from twincat_knowledge.corpus.topic_validation import (
    TopicCorpusBoundsError,
    TopicCorpusSummary,
    TopicCorpusValidationError,
    validate_topic_corpus,
)
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.topics import Topic
from twincat_knowledge.ingest.infosys import InfoSysReader
from twincat_knowledge.ingest.normalize import normalize_infosys

ARTICLE_HASH = "a" * 64
ARCHIVE_HASH = "b" * 64


def _snapshot(
    *, source_id: str = "synthetic", snapshot_id: str = "source-1", language: str = "en"
) -> SourceSnapshot:
    return SourceSnapshot(
        schema_version="1.0",
        source_id=source_id,
        snapshot_id=snapshot_id,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language=language,
        content_hash=ARCHIVE_HASH,
        rights_reference="operator-approved-fixture",
        parser_version="reader-1",
    )


def _manifest(
    topics: tuple[Topic, ...],
    *,
    source: SourceSnapshot | None = None,
    imported: int | None = None,
    counted_topics: int | None = None,
    counted_sections: int | None = None,
    package_snapshot_id: str = "package-1",
) -> CorpusManifest:
    source = source or _snapshot()
    imported = len(topics) if imported is None else imported
    return CorpusManifest(
        package_schema_version="1.0",
        snapshot_id=package_snapshot_id,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        sources=(source,),
        inventory=InventoryBalance(
            documents_total=imported,
            documents_imported=imported,
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(
            topics=len(topics) if counted_topics is None else counted_topics,
            sections=sum(len(topic.sections) for topic in topics)
            if counted_sections is None
            else counted_sections,
        ),
    )


def _normalized_topics() -> tuple[Topic, ...]:
    archive = BytesIO()
    with ZipFile(archive, "w") as handle:
        handle.writestr(
            "motion/1033/move.html",
            """<html><head><title>Move ☃</title></head><body>
            <p>Before</p><pre class="language-st">x := 1;\n</pre>
            <table><tr><td>Input</td></tr></table></body></html>""",
        )
    archive.seek(0)
    raw = InfoSysReader(archive, source_id="synthetic", snapshot_id="source-1").read()
    normalized = normalize_infosys(raw, (_snapshot(),))
    return read_topic_export(
        _write_export_fixture(normalized), max_record_bytes=1_048_576
    )


def _write_export_fixture(topics: tuple[Topic, ...]):
    """Use the real JSONL writer while keeping the test fixture in memory-free API."""
    import tempfile
    from pathlib import Path

    directory = Path(tempfile.mkdtemp(prefix="topic-validation-test-"))
    path = directory / "topics.jsonl"
    write_topic_export(path, topics)
    return path


def test_reader_normalizer_jsonl_reload_validates_and_returns_immutable_summary() -> (
    None
):
    topics = _normalized_topics()

    result = validate_topic_corpus(_manifest(topics), topics)

    assert result == TopicCorpusSummary(1, 3, {"en": 1})
    assert result.topic_count == 1
    assert result.section_count == 3
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        result.language_counts["de"] = 1  # type: ignore[index]
    with pytest.raises((AttributeError, TypeError)):
        result.topic_count = 2  # type: ignore[misc]


def test_manifest_package_snapshot_may_differ_from_source_snapshot() -> None:
    topics = _normalized_topics()

    result = validate_topic_corpus(
        _manifest(topics, package_snapshot_id="package-generation-9"), topics
    )

    assert result.topic_count == 1


def test_stable_canonical_ids_match_the_existing_byte_level_scheme() -> None:
    identity = {
        "source_id": "synthetic",
        "snapshot_id": "source-1",
        "language": "en",
        "raw_locator": "motion/1033/move.html",
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected_topic = "topic-" + hashlib.sha256(encoded).hexdigest()
    expected_section = (
        "section-"
        + hashlib.sha256(b'{"section_index":0,"topic_id":"topic-example"}').hexdigest()
    )

    assert canonical_topic_id(**identity) == expected_topic
    assert canonical_section_id("topic-example", 0) == expected_section
    assert _normalized_topics()[0].id == expected_topic
    assert _normalized_topics()[0].sections[0].id == canonical_section_id(
        expected_topic, 0
    )


def test_forged_public_json_rebound_topic_id_is_rejected() -> None:
    topic = _normalized_topics()[0]
    payload = topic.model_dump(mode="json")
    payload["id"] = "topic-forged"
    forged = Topic.model_validate_json(json.dumps(payload))

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic,)), (forged,))
    assert str(error.value) == "topic corpus contains invalid data"
    assert "topic-forged" not in str(error.value)


def test_swapped_or_reordered_section_ids_are_rejected_even_when_rebound() -> None:
    topic = _normalized_topics()[0]
    payload = topic.model_dump(mode="json")
    payload["sections"][0]["id"], payload["sections"][1]["id"] = (
        payload["sections"][1]["id"],
        payload["sections"][0]["id"],
    )
    payload["sections"][0]["source"]["section_id"] = payload["sections"][0]["id"]
    payload["sections"][1]["source"]["section_id"] = payload["sections"][1]["id"]
    swapped = Topic.model_validate_json(json.dumps(payload))

    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(_manifest((topic,)), (swapped,))

    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(
            _manifest((topic,)),
            (topic.model_copy(update={"sections": tuple(reversed(topic.sections))}),),
        )


def test_unknown_source_and_source_language_mismatch_are_generic_rejections() -> None:
    topic = _normalized_topics()[0]
    unknown_source = _manifest((topic,), source=_snapshot(source_id="other"))
    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(unknown_source, (topic,))
    assert str(error.value) == "topic corpus contains invalid data"

    payload = topic.model_dump(mode="json")
    payload["source"]["language"] = "de"
    mismatch = Topic.model_construct(**payload)
    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic,)), (mismatch,))
    assert str(error.value) == "topic corpus contains invalid data"


def test_unsupported_source_schema_is_rejected_without_exposing_model_details() -> None:
    topic = _normalized_topics()[0]
    source_data = _snapshot().model_dump(mode="python")
    source_data["schema_version"] = "2.0"
    unsupported = SourceSnapshot.model_construct(**source_data)

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic,), source=unsupported), (topic,))
    assert str(error.value) == "topic corpus contains invalid data"
    assert "2.0" not in str(error.value)


def test_non_topic_json_shape_is_rejected_as_generic_input() -> None:
    topic = _normalized_topics()[0]

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic,)), ({"unexpected": "secret"},))  # type: ignore[arg-type]
    assert str(error.value) == "topic corpus contains invalid data"
    assert "secret" not in str(error.value)


def test_inventory_and_entity_counts_must_match_the_consumed_topics() -> None:
    topic = _normalized_topics()[0]
    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(_manifest((topic,), imported=2), (topic,))
    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(_manifest((topic,), counted_topics=2), (topic,))
    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(_manifest((topic,), counted_sections=2), (topic,))


def test_duplicate_topic_ids_are_rejected() -> None:
    topic = _normalized_topics()[0]
    manifest = _manifest((topic, topic), counted_topics=2, counted_sections=6)

    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(manifest, (topic, topic))


@pytest.mark.parametrize(
    "field,value",
    [("language", "fr"), ("id", 7), ("sections", object())],
)
def test_bypassed_invalid_public_topic_models_are_revalidated(
    field: str, value: object
) -> None:
    topic = _normalized_topics()[0]
    forged = topic.model_construct(**{field: value})

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic,)), (forged,))
    assert str(error.value) == "topic corpus contains invalid data"


def test_bypassed_invalid_manifest_is_revalidated() -> None:
    topic = _normalized_topics()[0]
    manifest = _manifest((topic,)).model_construct(entity_counts=None)

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(manifest, (topic,))
    assert str(error.value) == "topic corpus contains invalid data"


@pytest.mark.parametrize(
    "name,kwargs",
    [
        ("max_topics", {"max_topics": True}),
        ("max_sections", {"max_sections": True}),
        ("max_total_bytes", {"max_total_bytes": True}),
        ("max_record_bytes", {"max_record_bytes": True}),
        ("max_topics", {"max_topics": 100_001}),
        ("max_sections", {"max_sections": 1_000_001}),
        ("max_total_bytes", {"max_total_bytes": 536_870_913}),
        ("max_record_bytes", {"max_record_bytes": 1_048_577}),
    ],
)
def test_limits_are_strict_and_have_fixed_hard_maxima(
    name: str, kwargs: dict[str, object]
) -> None:
    topic = _normalized_topics()[0]
    with pytest.raises(TopicCorpusBoundsError, match="topic corpus limit exceeded"):
        validate_topic_corpus(_manifest((topic,)), (topic,), **kwargs)  # type: ignore[arg-type]


def test_total_byte_maximum_matches_export_contract() -> None:
    """Validation and export share one full-local-InfoSys-scale byte ceiling."""
    from twincat_knowledge.corpus import topic_export, topic_validation

    assert topic_validation.MAX_TOTAL_BYTES == topic_export.MAX_TOTAL_BYTES
    assert topic_validation.MAX_TOTAL_BYTES == 512 * 1024 * 1024
    topic = _normalized_topics()[0]
    summary = validate_topic_corpus(
        _manifest((topic,)), (topic,), max_total_bytes=536_870_912
    )
    assert summary.topic_count == 1


def test_topic_consumption_is_incremental_and_stops_at_first_over_limit() -> None:
    topic = _normalized_topics()[0]
    consumed = 0

    def topics() -> Iterator[Topic]:
        nonlocal consumed
        while True:
            consumed += 1
            yield topic

    manifest = _manifest((topic,), imported=2, counted_topics=2, counted_sections=6)
    with pytest.raises(TopicCorpusBoundsError, match="topic corpus limit exceeded"):
        validate_topic_corpus(manifest, topics(), max_topics=1)
    assert consumed == 2


def test_section_record_and_total_byte_limits_are_checked() -> None:
    topic = _normalized_topics()[0]
    record_size = len(topic.model_dump_json().encode("utf-8"))
    with pytest.raises(TopicCorpusBoundsError):
        validate_topic_corpus(_manifest((topic,)), (topic,), max_sections=2)
    with pytest.raises(TopicCorpusBoundsError):
        validate_topic_corpus(
            _manifest((topic,)), (topic,), max_record_bytes=record_size - 1
        )
    with pytest.raises(TopicCorpusBoundsError):
        validate_topic_corpus(
            _manifest((topic,)), (topic,), max_total_bytes=record_size - 1
        )


def test_caller_iterator_failures_are_generic_and_have_no_exception_chain() -> None:
    topic = _normalized_topics()[0]

    class CallerDomainFailure(TopicCorpusValidationError):
        pass

    def raising_next() -> Iterator[Topic]:
        yield topic
        raise CallerDomainFailure("secret path and payload")

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic, topic)), raising_next())
    assert str(error.value) == "topic corpus iterator failed"
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    assert "secret" not in repr(error.value)

    class BadIterable:
        def __iter__(self) -> Iterator[Topic]:
            raise CallerDomainFailure("secret iterator detail")

    with pytest.raises(TopicCorpusValidationError) as error:
        validate_topic_corpus(_manifest((topic,)), BadIterable())
    assert str(error.value) == "topic corpus iterator failed"
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_no_summary_is_returned_when_a_late_record_fails() -> None:
    topic = _normalized_topics()[0]

    def topics() -> Iterator[Topic]:
        yield topic
        yield topic.model_construct(id="forged")

    manifest = _manifest((topic, topic), counted_topics=2, counted_sections=6)
    with pytest.raises(TopicCorpusValidationError):
        validate_topic_corpus(manifest, topics())
