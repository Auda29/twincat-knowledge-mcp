"""No-I/O validation of normalized topics before package publication."""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast

from pydantic import BaseModel

from twincat_knowledge.domain.identity import (
    canonical_section_id,
    canonical_topic_id,
)
from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.topics import Topic

from .manifest import CorpusManifest

MAX_TOPICS: Final = 100_000
MAX_SECTIONS: Final = 1_000_000
MAX_TOTAL_BYTES: Final = 67_108_864
MAX_RECORD_BYTES: Final = 1_048_576
SUPPORTED_PACKAGE_SCHEMA: Final = "1.0"
SUPPORTED_SOURCE_SCHEMA: Final = "1.0"


class TopicCorpusValidationError(ValueError):
    """A corpus manifest or normalized topic record is invalid."""


class TopicCorpusBoundsError(TopicCorpusValidationError):
    """A corpus validation limit was invalid or exceeded."""


@dataclass(frozen=True, slots=True)
class TopicCorpusSummary:
    """Immutable facts established by a complete topic-corpus validation."""

    topic_count: int
    section_count: int
    language_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "language_counts", MappingProxyType(dict(self.language_counts))
        )


def _limit(value: object, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TopicCorpusBoundsError("topic corpus limit exceeded")
    if value < 1 or value > maximum:
        raise TopicCorpusBoundsError("topic corpus limit exceeded")
    return value


def _limits(
    max_topics: object,
    max_sections: object,
    max_total_bytes: object,
    max_record_bytes: object,
) -> tuple[int, int, int, int]:
    return (
        _limit(max_topics, MAX_TOPICS),
        _limit(max_sections, MAX_SECTIONS),
        _limit(max_total_bytes, MAX_TOTAL_BYTES),
        _limit(max_record_bytes, MAX_RECORD_BYTES),
    )


def _revalidate(model: object, model_type: type[BaseModel]) -> tuple[BaseModel, str]:
    """Revalidate an instance, including instances made with model_construct."""
    try:
        if not isinstance(model, BaseModel) or not isinstance(model, model_type):
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            payload = model.model_dump(mode="python")
        validated = model_type.model_validate(payload)
        serialized = validated.model_dump_json()
        reparsed = model_type.model_validate_json(serialized)
        return reparsed, serialized
    except Exception:
        # Model errors can contain caller-controlled values and field paths.
        raise TopicCorpusValidationError("topic corpus contains invalid data") from None


def _caller_topics(topics: Iterable[Topic]) -> Iterator[Topic]:
    """Read caller iterators without exposing caller exception details."""
    try:
        iterator = iter(topics)
    except Exception:
        raise TopicCorpusValidationError("topic corpus iterator failed") from None
    while True:
        try:
            topic = next(iterator)
        except StopIteration:
            return
        except Exception:
            raise TopicCorpusValidationError("topic corpus iterator failed") from None
        yield topic


def _manifest_mapping(
    manifest: CorpusManifest,
) -> dict[tuple[str, str, str], SourceSnapshot]:
    mapping: dict[tuple[str, str, str], SourceSnapshot] = {}
    for source in manifest.sources:
        if source.schema_version != SUPPORTED_SOURCE_SCHEMA:
            raise TopicCorpusValidationError("topic corpus contains invalid data")
        key = (source.source_id, source.snapshot_id, source.language)
        if key in mapping:
            raise TopicCorpusValidationError("topic corpus contains invalid data")
        mapping[key] = source
    return mapping


def validate_topic_corpus(
    manifest: CorpusManifest,
    topics: Iterable[Topic],
    *,
    max_topics: int = MAX_TOPICS,
    max_sections: int = MAX_SECTIONS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_record_bytes: int = MAX_RECORD_BYTES,
) -> TopicCorpusSummary:
    """Validate a bounded topic stream and return facts only after success.

    This function reads no files or network resources. Topics are consumed one
    at a time and are never materialized as a collection.
    """
    limits = _limits(max_topics, max_sections, max_total_bytes, max_record_bytes)
    checked_manifest_base, _ = _revalidate(manifest, CorpusManifest)
    checked_manifest = cast(CorpusManifest, checked_manifest_base)
    if checked_manifest.package_schema_version != SUPPORTED_PACKAGE_SCHEMA:
        raise TopicCorpusValidationError("topic corpus contains invalid data")
    if checked_manifest.entity_counts is None:
        raise TopicCorpusValidationError("topic corpus contains invalid data")
    source_mapping = _manifest_mapping(checked_manifest)

    max_topic_count, max_section_count, total_limit, record_limit = limits
    topic_count = 0
    section_count = 0
    total_bytes = 0
    language_counts: dict[str, int] = {}
    seen_topic_ids: set[str] = set()

    for supplied_topic in _caller_topics(topics):
        topic_count += 1
        if topic_count > max_topic_count:
            raise TopicCorpusBoundsError("topic corpus limit exceeded")
        topic_base, serialized = _revalidate(supplied_topic, Topic)
        topic = cast(Topic, topic_base)
        record_bytes = len(serialized.encode("utf-8"))
        if record_bytes > record_limit:
            raise TopicCorpusBoundsError("topic corpus limit exceeded")
        total_bytes += record_bytes
        if total_bytes > total_limit:
            raise TopicCorpusBoundsError("topic corpus limit exceeded")

        expected_topic_id = canonical_topic_id(
            topic.source.source_id,
            topic.source.snapshot_id,
            topic.language,
            topic.source.locator,
        )
        if topic.id != expected_topic_id or topic.id in seen_topic_ids:
            raise TopicCorpusValidationError("topic corpus contains invalid data")
        seen_topic_ids.add(topic.id)

        source_key = (
            topic.source.source_id,
            topic.source.snapshot_id,
            topic.language,
        )
        if source_key not in source_mapping:
            raise TopicCorpusValidationError("topic corpus contains invalid data")

        for index, section in enumerate(topic.sections):
            section_count += 1
            if section_count > max_section_count:
                raise TopicCorpusBoundsError("topic corpus limit exceeded")
            if section.id != canonical_section_id(topic.id, index):
                raise TopicCorpusValidationError("topic corpus contains invalid data")

        language_counts[topic.language] = language_counts.get(topic.language, 0) + 1

    counts = checked_manifest.entity_counts
    if checked_manifest.inventory.documents_imported != topic_count:
        raise TopicCorpusValidationError("topic corpus contains invalid data")
    if counts.topics != topic_count or counts.sections != section_count:
        raise TopicCorpusValidationError("topic corpus contains invalid data")

    return TopicCorpusSummary(topic_count, section_count, language_counts)


__all__ = [
    "MAX_RECORD_BYTES",
    "MAX_SECTIONS",
    "MAX_TOPICS",
    "MAX_TOTAL_BYTES",
    "SUPPORTED_PACKAGE_SCHEMA",
    "SUPPORTED_SOURCE_SCHEMA",
    "TopicCorpusBoundsError",
    "TopicCorpusSummary",
    "TopicCorpusValidationError",
    "validate_topic_corpus",
]
