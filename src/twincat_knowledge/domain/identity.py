"""Pure canonical identifiers shared by ingestion and package validation."""

from __future__ import annotations

import hashlib
import json
from typing import Final

_TOPIC_PREFIX: Final = "topic-"
_SECTION_PREFIX: Final = "section-"


def _hashed_identifier(prefix: str, value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}{hashlib.sha256(encoded).hexdigest()}"


def topic_identity(
    source_id: str,
    snapshot_id: str,
    language: str,
    raw_locator: str,
) -> dict[str, str]:
    """Return the exact source identity used for a normalized topic ID."""
    return {
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "language": language,
        "raw_locator": raw_locator,
    }


def canonical_topic_id(
    source_id: str,
    snapshot_id: str,
    language: str,
    raw_locator: str,
) -> str:
    """Build the stable SHA-256 ID for one source article."""
    return _hashed_identifier(
        _TOPIC_PREFIX,
        topic_identity(source_id, snapshot_id, language, raw_locator),
    )


def canonical_section_id(topic_id: str, section_index: int) -> str:
    """Build the stable SHA-256 ID for an ordered topic section."""
    return _hashed_identifier(
        _SECTION_PREFIX,
        {"topic_id": topic_id, "section_index": section_index},
    )


# Explicit ``*_for`` spellings make the intended use at call sites clear while
# preserving one implementation of the canonical scheme.
topic_id_for = canonical_topic_id
section_id_for = canonical_section_id


__all__ = [
    "canonical_section_id",
    "canonical_topic_id",
    "section_id_for",
    "topic_identity",
    "topic_id_for",
]
