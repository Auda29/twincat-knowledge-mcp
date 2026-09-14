"""Pure, bounded extraction of explicit TOC metadata from normalized topics."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Final

from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topic_hierarchy import (
    MAX_PARENT_ORIGINAL_TOPIC_ID_LENGTH,
    MAX_TOC_ORDER,
    HierarchyDiagnosticCode,
    TopicHierarchy,
    TopicHierarchyAssessment,
)
from twincat_knowledge.domain.topics import Topic, TopicMetadata

MAX_METADATA_ITEMS: Final = 4_096
MAX_ATTRIBUTE_ITEMS: Final = 4_096
MAX_SECTION_ITEMS: Final = 100_000
MAX_TOPIC_ITEMS: Final = 100_000
MAX_TOC_ORDER_DIGITS: Final = len(str(MAX_TOC_ORDER))
_PARENT_NAME: Final = "microsoft.help.tocparent"
_ORDER_NAME: Final = "microsoft.help.tocorder"


class TopicHierarchyExtractionError(ValueError):
    """The input was not a safely revalidated normalized Topic."""


def _bounded_tuple(value: object, *, maximum: int, name: str) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} must be a tuple or list")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds its supported bound")
    iterator = iter(value)
    items: list[object] = []
    for _ in range(maximum + 1):
        try:
            items.append(next(iterator))
        except StopIteration:
            return tuple(items)
    raise ValueError(f"{name} exceeds its supported bound")


def _reject_unknown_model_state(model: object) -> None:
    extras = getattr(model, "__pydantic_extra__", None)
    fields = getattr(type(model), "model_fields", None)
    state = getattr(model, "__dict__", None)
    if (
        (extras is not None and (not isinstance(extras, dict) or extras))
        or not isinstance(fields, dict)
        or not isinstance(state, dict)
        or any(key not in fields for key in state)
    ):
        raise ValueError("model contains unknown fields")


def _source_payload(source: SourceReference) -> dict[str, object]:
    if not isinstance(source, SourceReference):
        raise ValueError("source must be a SourceReference")
    _reject_unknown_model_state(source)
    return {
        "source_id": source.source_id,
        "snapshot_id": source.snapshot_id,
        "topic_id": source.topic_id,
        "section_id": source.section_id,
        "title": source.title,
        "language": source.language,
        "canonical_url": source.canonical_url,
        "locator": source.locator,
        "content_hash": source.content_hash,
    }


def _metadata_payload(item: object) -> dict[str, object]:
    if not isinstance(item, TopicMetadata):
        raise ValueError("metadata must contain TopicMetadata models")
    _reject_unknown_model_state(item)
    attributes = _bounded_tuple(
        item.attributes, maximum=MAX_ATTRIBUTE_ITEMS, name="metadata attributes"
    )
    pairs: list[tuple[object, object]] = []
    for pair in attributes:
        pair_values = _bounded_tuple(pair, maximum=2, name="metadata attribute pair")
        if len(pair_values) != 2:
            raise ValueError("metadata attributes must contain pairs")
        pairs.append((pair_values[0], pair_values[1]))
    return {
        "name": item.name,
        "content": item.content,
        "attributes": tuple(pairs),
    }


def _section_payload(item: object) -> dict[str, object]:
    # Importing locally keeps this module's public dependency surface small.
    from twincat_knowledge.domain.topics import Section

    if not isinstance(item, Section):
        raise ValueError("sections must contain Section models")
    _reject_unknown_model_state(item)
    rows = _bounded_tuple(item.rows, maximum=MAX_SECTION_ITEMS, name="section rows")
    checked_rows: list[tuple[object, ...]] = []
    for row in rows:
        row_values = _bounded_tuple(
            row, maximum=MAX_ATTRIBUTE_ITEMS, name="section row"
        )
        checked_rows.append(row_values)
    return {
        "id": item.id,
        "kind": item.kind,
        "text": item.text,
        "code": item.code,
        "language": item.language,
        "rows": tuple(checked_rows),
        "source": _source_payload(item.source),
    }


def _topic_payload(topic: Topic) -> dict[str, object]:
    """Copy fields through bounded containers without serializing caller objects."""
    if not isinstance(topic, Topic):
        raise ValueError("input must be a Topic model")
    _reject_unknown_model_state(topic)
    metadata = _bounded_tuple(
        topic.metadata, maximum=MAX_METADATA_ITEMS, name="topic metadata"
    )
    sections = _bounded_tuple(
        topic.sections, maximum=MAX_SECTION_ITEMS, name="topic sections"
    )
    image_refs = _bounded_tuple(
        topic.image_refs, maximum=MAX_SECTION_ITEMS, name="topic image refs"
    )
    help_ids = _bounded_tuple(
        topic.help_ids, maximum=MAX_SECTION_ITEMS, name="topic help ids"
    )
    return {
        "id": topic.id,
        "title": topic.title,
        "original_topic_id": topic.original_topic_id,
        "library": topic.library,
        "language": topic.language,
        "source": _source_payload(topic.source),
        "metadata": tuple(_metadata_payload(item) for item in metadata),
        "sections": tuple(_section_payload(item) for item in sections),
        "image_refs": tuple(image_refs),
        "help_ids": tuple(help_ids),
    }


def _revalidate_topic(topic: Topic) -> Topic:
    # ``model_construct`` and ``model_copy`` can bypass Pydantic validation.
    # Rebuilding a bounded primitive payload also avoids recursive model_dump on
    # malicious cyclic in-process objects.
    return Topic.model_validate(_topic_payload(topic))


def _parent_diagnostic(value: object) -> HierarchyDiagnosticCode | None:
    if not isinstance(value, str):
        return HierarchyDiagnosticCode.PARENT_MALFORMED
    if len(value) > MAX_PARENT_ORIGINAL_TOPIC_ID_LENGTH:
        return HierarchyDiagnosticCode.PARENT_OVERSIZED
    if not value.strip():
        return HierarchyDiagnosticCode.PARENT_BLANK
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return HierarchyDiagnosticCode.PARENT_CONTROL
    if value != value.strip():
        return HierarchyDiagnosticCode.PARENT_MALFORMED
    return None


def _parse_order(value: str) -> tuple[int | None, HierarchyDiagnosticCode | None]:
    if not value or any(char not in "0123456789" for char in value):
        return None, HierarchyDiagnosticCode.ORDER_INVALID
    if len(value) > MAX_TOC_ORDER_DIGITS:
        return None, HierarchyDiagnosticCode.ORDER_OVERSIZED
    parsed = int(value, 10)
    if parsed <= 0:
        return None, HierarchyDiagnosticCode.ORDER_INVALID
    if parsed > MAX_TOC_ORDER:
        return None, HierarchyDiagnosticCode.ORDER_OVERSIZED
    return parsed, None


def extract_topic_hierarchy(topic: Topic) -> TopicHierarchyAssessment:
    """Extract only explicit ``TocParent``/``TocOrder`` metadata.

    The returned parent is an unresolved original-topic identifier.  This
    function never examines title, path, links, archive order, or body text.
    All ordinary input failures become one fixed exception message; Python
    cancellation/base exceptions are intentionally not caught.
    """
    try:
        checked = _revalidate_topic(topic)
        parent_items = tuple(
            item for item in checked.metadata if item.name.casefold() == _PARENT_NAME
        )
        order_items = tuple(
            item for item in checked.metadata if item.name.casefold() == _ORDER_NAME
        )

        diagnostics: list[HierarchyDiagnosticCode] = []
        if not parent_items:
            diagnostics.append(HierarchyDiagnosticCode.PARENT_MISSING)
            hierarchy = None
        elif len(parent_items) != 1:
            diagnostics.append(HierarchyDiagnosticCode.PARENT_DUPLICATE)
            hierarchy = None
        else:
            parent = parent_items[0].content
            parent_code = _parent_diagnostic(parent)
            if parent_code is not None:
                diagnostics.append(parent_code)
                hierarchy = None
            elif not order_items:
                diagnostics.append(HierarchyDiagnosticCode.ORDER_MISSING)
                hierarchy = TopicHierarchy(
                    parent_original_topic_id=parent, toc_order=None
                )
            elif len(order_items) != 1:
                diagnostics.append(HierarchyDiagnosticCode.ORDER_DUPLICATE)
                hierarchy = TopicHierarchy(
                    parent_original_topic_id=parent, toc_order=None
                )
            else:
                order, order_code = _parse_order(order_items[0].content)
                if order_code is not None:
                    diagnostics.append(order_code)
                hierarchy = TopicHierarchy(
                    parent_original_topic_id=parent,
                    toc_order=order,
                )

        return TopicHierarchyAssessment(
            topic_id=checked.id,
            source=checked.source,
            hierarchy=hierarchy,
            diagnostic_codes=tuple(diagnostics),
        )
    except Exception:
        raise TopicHierarchyExtractionError("normalized topic is invalid") from None


def _caller_topics(topics: Iterable[Topic]) -> Iterator[Topic]:
    try:
        iterator = iter(topics)
    except Exception:
        raise TopicHierarchyExtractionError("topic iterator is invalid") from None
    while True:
        try:
            item = next(iterator)
        except StopIteration:
            return
        except Exception:
            raise TopicHierarchyExtractionError("topic iterator is invalid") from None
        yield item


def extract_topic_hierarchies(
    topics: Iterable[Topic], *, max_topics: int = MAX_TOPIC_ITEMS
) -> tuple[TopicHierarchyAssessment, ...]:
    """Extract a bounded batch while preserving input order."""
    try:
        if isinstance(max_topics, bool) or not isinstance(max_topics, int):
            raise TypeError("max_topics must be an integer")
        if max_topics <= 0 or max_topics > MAX_TOPIC_ITEMS:
            raise ValueError("max_topics is outside its supported bound")
        results: list[TopicHierarchyAssessment] = []
        for count, topic in enumerate(_caller_topics(topics), start=1):
            if count > max_topics:
                raise TopicHierarchyExtractionError(
                    "topic count exceeds its supported bound"
                )
            results.append(extract_topic_hierarchy(topic))
        return tuple(results)
    except TopicHierarchyExtractionError:
        raise
    except Exception:
        raise TopicHierarchyExtractionError(
            "topic hierarchy extraction failed"
        ) from None


extract_hierarchy = extract_topic_hierarchy
extract_hierarchies = extract_topic_hierarchies

__all__ = [
    "MAX_ATTRIBUTE_ITEMS",
    "MAX_METADATA_ITEMS",
    "MAX_PARENT_ORIGINAL_TOPIC_ID_LENGTH",
    "MAX_SECTION_ITEMS",
    "MAX_TOPIC_ITEMS",
    "MAX_TOC_ORDER",
    "MAX_TOC_ORDER_DIGITS",
    "TopicHierarchyExtractionError",
    "extract_hierarchies",
    "extract_hierarchy",
    "extract_topic_hierarchies",
    "extract_topic_hierarchy",
]
