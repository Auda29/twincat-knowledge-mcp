"""RED-GREEN tests for the bounded InfoSys topic normalization slice."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.ingest.infosys import InfoSysSection, InfoSysTopic
from twincat_knowledge.ingest.normalize import (
    TopicNormalizationError,
    normalize_infosys,
)

ARTICLE_HASH = "a" * 64
ARCHIVE_HASH = "b" * 64


def _snapshot(
    *,
    source_id: str = "infosys",
    snapshot_id: str = "snapshot-1",
    language: str = "en",
) -> SourceSnapshot:
    return SourceSnapshot(
        source_id=source_id,
        snapshot_id=snapshot_id,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language=language,
        content_hash=ARCHIVE_HASH,
        rights_reference="operator-approved-fixture",
        parser_version="reader-1",
    )


def _topic(
    *,
    locator: str = "lib/1033/move.html",
    source_id: str = "infosys",
    snapshot_id: str = "snapshot-1",
    language: str = "en",
    library: str = "lib",
    title: str = "Move",
    topic_id: str | None = "help.move",
    sections: tuple[InfoSysSection, ...] = (),
    image_refs: tuple[str, ...] = (),
    help_ids: tuple[str, ...] = (),
) -> InfoSysTopic:
    return InfoSysTopic(
        title=title,
        topic_id=topic_id,
        language=language,
        library=library,
        source=SourceReference(
            source_id=source_id,
            snapshot_id=snapshot_id,
            topic_id=topic_id,
            title=title,
            language=language,
            canonical_url="https://example.invalid/help/move",
            locator=locator,
            content_hash=ARTICLE_HASH,
        ),
        sections=sections,
        image_refs=image_refs,
        help_ids=help_ids,
    )


def test_normalization_is_deterministic_immutable_and_json_roundtrips() -> None:
    input_topic = _topic()

    first = normalize_infosys([input_topic], [_snapshot()])
    second = normalize_infosys([input_topic], [_snapshot()])

    assert first == second
    assert first[0].id.startswith("topic-")
    assert first[0].original_topic_id == "help.move"
    assert first[0].source.locator == input_topic.source.locator
    assert first[0].source.content_hash == ARTICLE_HASH
    assert first[0] == type(first[0]).model_validate_json(first[0].model_dump_json())
    with pytest.raises(ValidationError):
        first[0].title = "changed"  # type: ignore[misc]


def test_snapshot_language_and_library_variants_are_not_merged_by_title() -> None:
    topics = [
        _topic(locator="alpha/1033/same.html", library="alpha"),
        _topic(locator="beta/1033/same.html", library="beta", snapshot_id="snapshot-2"),
        _topic(
            locator="alpha/1031/same.html",
            language="de",
            snapshot_id="snapshot-1",
            library="alpha",
        ),
    ]

    result = normalize_infosys(
        topics,
        [_snapshot(), _snapshot(snapshot_id="snapshot-2"), _snapshot(language="de")],
    )

    assert len(result) == 3
    assert len({item.id for item in result}) == 3
    assert {
        (item.library, item.language, item.source.snapshot_id) for item in result
    } == {
        ("alpha", "en", "snapshot-1"),
        ("beta", "en", "snapshot-2"),
        ("alpha", "de", "snapshot-1"),
    }


def test_exact_payloads_and_references_preserve_section_sources() -> None:
    sections = (
        InfoSysSection(kind="paragraph", text="  exact paragraph\n"),
        InfoSysSection(kind="code", code="  x := 1;\n\n", language="st"),
        InfoSysSection(kind="table", rows=((" Input ", ""), ("Axis", "  "))),
        InfoSysSection(kind="warning", text="WARNING: do not execute this"),
    )
    input_topic = _topic(
        sections=sections,
        image_refs=("javascript:untrusted-image", "images/x.png"),
        help_ids=("ms-xhelp:///?Id=help.move", "not-a-link-to-follow"),
    )

    result = normalize_infosys([input_topic], [_snapshot()])[0]

    assert [section.kind for section in result.sections] == [
        "paragraph",
        "code",
        "table",
        "warning",
    ]
    assert result.sections[0].text == "  exact paragraph\n"
    assert result.sections[1].code == "  x := 1;\n\n"
    assert result.sections[1].language == "st"
    assert result.sections[2].rows == ((" Input ", ""), ("Axis", "  "))
    assert result.sections[3].text == "WARNING: do not execute this"
    assert result.image_refs == input_topic.image_refs
    assert result.help_ids == input_topic.help_ids
    assert [section.source.section_id for section in result.sections] == [
        section.id for section in result.sections
    ]
    for section in result.sections:
        assert section.source.topic_id == "help.move"
        assert section.source.locator == input_topic.source.locator
        assert section.source.content_hash == ARTICLE_HASH
        assert section.source.canonical_url == input_topic.source.canonical_url


def test_strict_input_and_normalized_models_reject_unknown_or_malformed_shapes() -> (
    None
):
    with pytest.raises(ValidationError):
        InfoSysTopic.model_validate(
            {
                "title": "x",
                "topic_id": None,
                "language": "en",
                "library": "lib",
                "source": {
                    "source_id": "s",
                    "snapshot_id": "snap",
                    "language": "en",
                    "locator": "lib/x.html",
                    "content_hash": ARTICLE_HASH,
                    "unexpected": "reject",
                },
                "unknown": True,
            }
        )

    with pytest.raises(ValidationError):
        InfoSysSection.model_validate({"kind": "code", "text": "not-code"})

    normalized = normalize_infosys([_topic()], [_snapshot()])[0]
    with pytest.raises(ValidationError):
        type(normalized).model_validate(
            {**normalized.model_dump(mode="json"), "unknown": "reject"}
        )


def test_missing_or_mismatched_snapshot_is_rejected() -> None:
    with pytest.raises(TopicNormalizationError, match="no matching snapshot"):
        normalize_infosys([_topic()], [_snapshot(snapshot_id="other")])

    with pytest.raises(TopicNormalizationError, match="no matching snapshot"):
        normalize_infosys([_topic(language="de")], [_snapshot()])

    mismatched_source = _topic().model_copy(
        update={"source": _topic(language="de").source}
    )
    with pytest.raises(TopicNormalizationError, match="topic language"):
        normalize_infosys([mismatched_source], [_snapshot()])


def test_duplicate_snapshot_mapping_and_duplicate_output_id_are_rejected() -> None:
    with pytest.raises(TopicNormalizationError, match="duplicate source snapshot"):
        normalize_infosys([_topic()], [_snapshot(), _snapshot()])

    with pytest.raises(TopicNormalizationError, match="duplicate normalized topic ID"):
        normalize_infosys([_topic(), _topic()], [_snapshot()])


def test_article_hash_is_not_compared_with_whole_source_archive_hash() -> None:
    result = normalize_infosys([_topic()], [_snapshot()])
    assert result[0].source.content_hash == ARTICLE_HASH


def test_topic_iterator_is_bounded_incrementally() -> None:
    consumed = 0

    def topics() -> Iterator[InfoSysTopic]:
        nonlocal consumed
        while True:
            consumed += 1
            yield _topic(locator=f"lib/1033/{consumed}.html")

    with pytest.raises(TopicNormalizationError, match="maximum topic count"):
        normalize_infosys(topics(), [_snapshot()], max_topics=2)

    assert consumed <= 3


def test_normalized_source_references_carry_the_original_help_topic_id() -> None:
    topic = _topic().model_copy(update={"source": _topic(topic_id=None).source})

    result = normalize_infosys([topic], [_snapshot()])[0]

    assert result.original_topic_id == "help.move"
    assert result.source.topic_id == "help.move"
    assert all(section.source.topic_id == "help.move" for section in result.sections)
