"""Vertical TDD coverage for pure hierarchy metadata extraction."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topic_hierarchy import (
    HierarchyDiagnosticCode,
    TopicHierarchy,
)
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.ingest.infosys import read_infosys
from twincat_knowledge.ingest.normalize import normalize_infosys
from twincat_knowledge.ingest.topic_hierarchy import (
    MAX_ATTRIBUTE_ITEMS,
    MAX_METADATA_ITEMS,
    TopicHierarchyExtractionError,
    extract_topic_hierarchies,
    extract_topic_hierarchy,
)

ARTICLE_HASH = "a" * 64
ARCHIVE_HASH = "b" * 64


class _UnderreportedList(list):
    def __len__(self) -> int:
        return 0


class _FiniteBombList(_UnderreportedList):
    def __init__(self, values, limit: int) -> None:
        super().__init__(values)
        self.limit = limit
        self.consumed = 0
        self.overconsumed = False

    def __iter__(self):
        for value in super().__iter__():
            self.consumed += 1
            if self.consumed > self.limit:
                self.overconsumed = True
                raise AssertionError("bounded iterator was over-consumed")
            yield value


class _RaisingMetadataList(_UnderreportedList):
    def __iter__(self):
        raise TopicHierarchyExtractionError("caller-controlled secret")


def _table_section() -> Section:
    source = _topic().source.model_copy(update={"section_id": "section-1"})
    return Section(
        id="section-1",
        kind="table",
        rows=(("cell",),),
        source=source,
    )


def _snapshot() -> SourceSnapshot:
    return SourceSnapshot(
        source_id="synthetic",
        snapshot_id="snapshot-1",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language="en",
        content_hash=ARCHIVE_HASH,
        rights_reference="operator-approved synthetic fixture",
        parser_version="fixture",
    )


def _topic(*metadata: TopicMetadata) -> Topic:
    source = SourceReference(
        source_id="synthetic",
        snapshot_id="snapshot-1",
        topic_id="help.child",
        title="Child",
        language="en",
        canonical_url=None,
        locator="sample/1033/child.html",
        content_hash=ARTICLE_HASH,
    )
    return Topic(
        id="topic-canonical-child",
        title="Child",
        original_topic_id="help.child",
        library="sample",
        language="en",
        source=source,
        metadata=metadata,
    )


def _meta(name: str, content: str, **attrs: str) -> TopicMetadata:
    return TopicMetadata(
        name=name,
        content=content,
        attributes=tuple((key, value) for key, value in attrs.items()),
    )


def _codes(result) -> set[HierarchyDiagnosticCode]:
    return set(result.diagnostic_codes)


def test_extracts_explicit_root_and_preserves_source_and_metadata() -> None:
    topic = _topic(
        _meta("Microsoft.Help.Id", "help.child"),
        _meta("Microsoft.Help.TocParent", "-1"),
        _meta("Microsoft.Help.TocOrder", "0007"),
        _meta("Microsoft.Help.Version", "unverified"),
    )
    before = topic.model_dump(mode="python")

    result = extract_topic_hierarchy(topic)

    assert result.topic_id == topic.id
    assert result.source == topic.source
    assert result.source.section_id is None
    assert result.hierarchy == TopicHierarchy(
        parent_original_topic_id="-1", toc_order=7
    )
    assert result.diagnostic_codes == ()
    assert topic.model_dump(mode="python") == before


def test_extracts_case_preserving_parent_and_ignores_unrelated_fields() -> None:
    topic = _topic(
        _meta("Microsoft.Help.TocParent", "Parent.ID/Case"),
        _meta("Microsoft.Help.TocOrder", "12"),
        _meta("Microsoft.Help.TopicLocale", "de"),
        _meta("Microsoft.Help.Id", "body-link-parent"),
    ).model_copy(update={"help_ids": ("body-link-parent",)})

    result = extract_topic_hierarchy(topic)

    assert result.hierarchy is not None
    assert result.hierarchy.parent_original_topic_id == "Parent.ID/Case"
    assert result.hierarchy.toc_order == 12
    assert result.diagnostic_codes == ()


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        ((), HierarchyDiagnosticCode.PARENT_MISSING),
        (
            (_meta("Microsoft.Help.TocParent", ""),),
            HierarchyDiagnosticCode.PARENT_BLANK,
        ),
        (
            (_meta("Microsoft.Help.TocParent", " parent "),),
            HierarchyDiagnosticCode.PARENT_MALFORMED,
        ),
        (
            (_meta("Microsoft.Help.TocParent", "bad\x00id"),),
            HierarchyDiagnosticCode.PARENT_CONTROL,
        ),
        (
            (_meta("Microsoft.Help.TocParent", "x" * 513),),
            HierarchyDiagnosticCode.PARENT_OVERSIZED,
        ),
    ],
)
def test_invalid_or_missing_parent_is_unavailable_without_repair(
    metadata, code
) -> None:
    result = extract_topic_hierarchy(_topic(*metadata))

    assert result.hierarchy is None
    assert result.diagnostic_codes == (code,)


def test_duplicate_parent_is_unavailable_even_when_values_match() -> None:
    result = extract_topic_hierarchy(
        _topic(
            _meta("Microsoft.Help.TocParent", "same"),
            _meta("Microsoft.Help.TocParent", "same"),
            _meta("Microsoft.Help.TocOrder", "1"),
        )
    )

    assert result.hierarchy is None
    assert result.diagnostic_codes == (HierarchyDiagnosticCode.PARENT_DUPLICATE,)


@pytest.mark.parametrize(
    ("order", "code"),
    [
        (None, HierarchyDiagnosticCode.ORDER_MISSING),
        ("", HierarchyDiagnosticCode.ORDER_INVALID),
        ("+1", HierarchyDiagnosticCode.ORDER_INVALID),
        ("-1", HierarchyDiagnosticCode.ORDER_INVALID),
        ("1.0", HierarchyDiagnosticCode.ORDER_INVALID),
        ("١", HierarchyDiagnosticCode.ORDER_INVALID),
        ("0", HierarchyDiagnosticCode.ORDER_INVALID),
        ("100000000", HierarchyDiagnosticCode.ORDER_OVERSIZED),
    ],
)
def test_parent_survives_without_order_fallback(order, code) -> None:
    metadata = [_meta("Microsoft.Help.TocParent", "Parent")]
    if order is not None:
        metadata.append(_meta("Microsoft.Help.TocOrder", order))

    result = extract_topic_hierarchy(_topic(*metadata))

    assert result.hierarchy is not None
    assert result.hierarchy.parent_original_topic_id == "Parent"
    assert result.hierarchy.toc_order is None
    assert result.diagnostic_codes == (code,)


def test_duplicate_order_keeps_parent_but_order_is_unknown() -> None:
    result = extract_topic_hierarchy(
        _topic(
            _meta("Microsoft.Help.TocParent", "Parent"),
            _meta("Microsoft.Help.TocOrder", "1"),
            _meta("Microsoft.Help.TocOrder", "2"),
        )
    )

    assert result.hierarchy is not None
    assert result.hierarchy.toc_order is None
    assert result.diagnostic_codes == (HierarchyDiagnosticCode.ORDER_DUPLICATE,)


def test_construct_bypass_is_revalidated_and_cyclic_input_is_controlled() -> None:
    forged = Topic.model_construct(
        id="topic-canonical-child",
        title="Child",
        original_topic_id="help.child",
        library="sample",
        language="en",
        source=_topic().source,
        metadata=[object()],
    )

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)

    cyclic: list[object] = []
    cyclic.append(cyclic)
    cyclic_topic = Topic.model_construct(
        id="topic-canonical-child",
        title="Child",
        original_topic_id="help.child",
        library="sample",
        language="en",
        source=_topic().source,
        metadata=cyclic,
    )
    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(cyclic_topic)


def test_model_copy_extra_on_topic_is_rejected_at_fresh_boundary() -> None:
    forged = _topic().model_copy(update={"unexpected": "secret"})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_model_copy_extra_on_source_is_rejected_at_fresh_boundary() -> None:
    source = _topic().source.model_copy(update={"unexpected": "secret"})
    forged = _topic().model_copy(update={"source": source})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_model_copy_extra_on_section_is_rejected_at_fresh_boundary() -> None:
    section = _table_section().model_copy(update={"unexpected": "secret"})
    forged = _topic().model_copy(update={"sections": [section]})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_model_copy_extra_on_metadata_is_rejected_at_fresh_boundary() -> None:
    metadata = _meta("Microsoft.Help.Unrelated", "value").model_copy(
        update={"unexpected": "secret"}
    )
    forged = _topic().model_copy(update={"metadata": [metadata]})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_direct_extraction_sanitizes_error_from_caller_container() -> None:
    forged = _topic().model_copy(update={"metadata": _RaisingMetadataList()})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic") as exc:
        extract_topic_hierarchy(forged)
    assert "caller-controlled secret" not in str(exc.value)


def test_underreported_metadata_is_rejected_at_actual_materialization_bound() -> None:
    metadata = _UnderreportedList(
        [_meta("Microsoft.Help.Unrelated", "value")] * (MAX_METADATA_ITEMS + 1)
    )
    forged = _topic().model_copy(update={"metadata": metadata})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_bounded_materialization_stops_after_first_overbound_item() -> None:
    metadata = _FiniteBombList(
        [_meta("Microsoft.Help.Unrelated", "value")] * (MAX_METADATA_ITEMS + 2),
        limit=MAX_METADATA_ITEMS + 1,
    )
    forged = _topic().model_copy(update={"metadata": metadata})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)
    assert metadata.consumed == MAX_METADATA_ITEMS + 1
    assert not metadata.overconsumed


def test_exact_metadata_bound_remains_valid_for_finite_list() -> None:
    metadata = _UnderreportedList(
        [_meta("Microsoft.Help.Unrelated", "value")] * MAX_METADATA_ITEMS
    )
    forged = _topic().model_copy(update={"metadata": metadata})

    result = extract_topic_hierarchy(forged)

    assert result.hierarchy is None
    assert result.diagnostic_codes == (HierarchyDiagnosticCode.PARENT_MISSING,)


def test_underreported_section_row_is_rejected_without_unbounded_row_copy() -> None:
    row = _UnderreportedList(["cell"] * (MAX_ATTRIBUTE_ITEMS + 1))
    section = _table_section().model_copy(update={"rows": (row,)})
    forged = _topic().model_copy(update={"sections": [section]})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_underreported_metadata_pair_is_rejected_without_dropping_extra_items() -> None:
    pair = _UnderreportedList(["name", "value", "unexpected"])
    metadata = _meta("Microsoft.Help.Unrelated", "value").model_copy(
        update={"attributes": (pair,)}
    )
    forged = _topic().model_copy(update={"metadata": [metadata]})

    with pytest.raises(TopicHierarchyExtractionError, match="normalized topic"):
        extract_topic_hierarchy(forged)


def test_batch_extraction_is_bounded_incrementally() -> None:
    consumed = 0

    def topics():
        nonlocal consumed
        while True:
            consumed += 1
            yield _topic(_meta("Microsoft.Help.TocParent", "Parent"))

    with pytest.raises(TopicHierarchyExtractionError, match="topic count"):
        extract_topic_hierarchies(topics(), max_topics=2)
    assert consumed == 3


def test_batch_preserves_sanitized_caller_iterator_error() -> None:
    def topics():
        yield _topic()
        raise TopicHierarchyExtractionError("caller-controlled secret")

    with pytest.raises(
        TopicHierarchyExtractionError, match="topic iterator is invalid"
    ):
        extract_topic_hierarchies(topics())


def test_cancellation_is_not_sanitized_as_an_ordinary_input_error(monkeypatch) -> None:
    import twincat_knowledge.ingest.topic_hierarchy as module

    def cancel(_topic):
        raise asyncio.CancelledError

    monkeypatch.setattr(module, "_revalidate_topic", cancel)
    with pytest.raises(asyncio.CancelledError):
        extract_topic_hierarchy(_topic())


def test_real_reader_and_normalizer_make_raw_hierarchy_metadata_available() -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as handle:
        handle.writestr(
            "sample/1033/child.html",
            "<html><head><title>Child</title>"
            '<meta name="Microsoft.Help.Id" content="help.child"/>'
            '<meta name="Microsoft.Help.TocParent" content="Parent.ID"/>'
            '<meta name="Microsoft.Help.TocOrder" content="3"/>'
            '<meta name="Microsoft.Help.Version" content="unrelated"/>'
            "</head><body><article><p>child</p></article></body></html>",
        )
    raw = read_infosys(
        archive.getvalue(), source_id="synthetic", snapshot_id="snapshot-1"
    )
    normalized = normalize_infosys(raw, (_snapshot(),))[0]

    result = extract_topic_hierarchy(normalized)

    assert result.hierarchy == TopicHierarchy(
        parent_original_topic_id="Parent.ID", toc_order=3
    )
    assert normalized.metadata == tuple(
        TopicMetadata.model_validate(item.model_dump(mode="python"))
        for item in raw[0].metadata
    )
    assert normalized.source.content_hash == raw[0].source.content_hash


def test_hierarchy_model_rejects_non_strict_or_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        TopicHierarchy.model_validate(
            {"parent_original_topic_id": "Parent", "toc_order": True}
        )
    with pytest.raises(ValidationError):
        TopicHierarchy.model_validate(
            {"parent_original_topic_id": "Parent", "toc_order": 10_000_001}
        )
