"""Bounded conversion from the InfoSys reader shape to normalized topics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from twincat_knowledge.domain.identity import (
    canonical_section_id,
    canonical_topic_id,
    topic_identity,
)
from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.ingest.infosys import InfoSysSection, InfoSysTopic

DEFAULT_MAX_TOPICS: Final = 100_000
DEFAULT_MAX_SNAPSHOTS: Final = 10_000


class TopicNormalizationError(ValueError):
    """The supplied InfoSys topics cannot form a safe normalized slice."""


def _topic_identity(topic: InfoSysTopic) -> dict[str, str]:
    """Use source identity, not title, as the topic identity."""
    return topic_identity(
        topic.source.source_id,
        topic.source.snapshot_id,
        topic.language,
        topic.source.locator,
    )


def _source_for(
    source: SourceReference,
    *,
    section_id: str | None,
) -> SourceReference:
    """Retain every source field while adding the normalized section ID."""
    return source.model_copy(update={"section_id": section_id})


def _normalize_section(
    section: InfoSysSection,
    *,
    index: int,
    topic_id: str,
    source: SourceReference,
) -> Section:
    section_id = canonical_section_id(topic_id, index)
    return Section(
        id=section_id,
        kind=section.kind,
        text=section.text,
        code=section.code,
        language=section.language,
        rows=section.rows,
        source=_source_for(source, section_id=section_id),
    )


def _snapshot_map(
    snapshots: Iterable[SourceSnapshot],
) -> dict[tuple[str, str, str], SourceSnapshot]:
    mapped: dict[tuple[str, str, str], SourceSnapshot] = {}
    for count, snapshot in enumerate(snapshots, start=1):
        if count > DEFAULT_MAX_SNAPSHOTS:
            raise TopicNormalizationError("maximum snapshot count exceeded")
        if not isinstance(snapshot, SourceSnapshot):
            raise TopicNormalizationError(
                "snapshots must contain SourceSnapshot models"
            )
        key = (snapshot.source_id, snapshot.snapshot_id, snapshot.language)
        if key in mapped:
            raise TopicNormalizationError(
                "duplicate source snapshot mapping: "
                f"{snapshot.source_id}/{snapshot.snapshot_id}/{snapshot.language}"
            )
        mapped[key] = snapshot
    return mapped


def normalize_infosys(
    topics: Iterable[InfoSysTopic],
    snapshots: Iterable[SourceSnapshot],
    *,
    max_topics: int = DEFAULT_MAX_TOPICS,
) -> tuple[Topic, ...]:
    """Normalize bounded InfoSys topics against supplied source snapshots.

    The iterator is consumed incrementally and at most ``max_topics`` output
    objects are retained.  Locators and references are data only: this
    function performs no filesystem or network access and does not verify
    bytes that are not present in the input models.
    """
    if isinstance(max_topics, bool) or not isinstance(max_topics, int):
        raise TypeError("max_topics must be an integer")
    if max_topics <= 0:
        raise ValueError("max_topics must be positive")

    source_snapshots = _snapshot_map(snapshots)
    normalized: list[Topic] = []
    seen_ids: set[str] = set()

    for count, input_topic in enumerate(topics, start=1):
        if count > max_topics:
            raise TopicNormalizationError("maximum topic count exceeded")
        if not isinstance(input_topic, InfoSysTopic):
            raise TopicNormalizationError("topics must contain InfoSysTopic models")

        source_key = (
            input_topic.source.source_id,
            input_topic.source.snapshot_id,
            input_topic.language,
        )
        if input_topic.source.language != input_topic.language:
            raise TopicNormalizationError("topic source does not match topic language")
        snapshot = source_snapshots.get(source_key)
        if snapshot is None:
            raise TopicNormalizationError(
                "no matching snapshot for topic source_id/snapshot_id/language"
            )
        if (
            input_topic.source.source_id != snapshot.source_id
            or input_topic.source.snapshot_id != snapshot.snapshot_id
            or input_topic.language != snapshot.language
        ):
            raise TopicNormalizationError("topic source does not match snapshot")

        if (
            input_topic.source.title is not None
            and input_topic.source.title != input_topic.title
        ):
            raise TopicNormalizationError("topic title and source.title disagree")

        original_topic_id = input_topic.topic_id
        source_topic_id = input_topic.source.topic_id
        if (
            original_topic_id is not None
            and source_topic_id is not None
            and original_topic_id != source_topic_id
        ):
            raise TopicNormalizationError(
                "topic_id and source.topic_id disagree for the same article"
            )
        if original_topic_id is None:
            original_topic_id = source_topic_id

        topic_id = canonical_topic_id(**_topic_identity(input_topic))
        if topic_id in seen_ids:
            raise TopicNormalizationError("duplicate normalized topic ID")
        seen_ids.add(topic_id)

        provenance_source = input_topic.source.model_copy(
            update={"topic_id": original_topic_id}
        )
        normalized_source = _source_for(provenance_source, section_id=None)
        sections = tuple(
            _normalize_section(
                section,
                index=index,
                topic_id=topic_id,
                source=provenance_source,
            )
            for index, section in enumerate(input_topic.sections)
        )
        normalized.append(
            Topic(
                id=topic_id,
                title=input_topic.title,
                original_topic_id=original_topic_id,
                library=input_topic.library,
                language=input_topic.language,
                source=normalized_source,
                metadata=tuple(
                    TopicMetadata.model_validate(item.model_dump())
                    for item in input_topic.metadata
                ),
                sections=sections,
                image_refs=input_topic.image_refs,
                help_ids=input_topic.help_ids,
            )
        )

    return tuple(normalized)


__all__ = [
    "DEFAULT_MAX_SNAPSHOTS",
    "DEFAULT_MAX_TOPICS",
    "TopicNormalizationError",
    "normalize_infosys",
]
