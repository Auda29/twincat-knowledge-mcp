"""Immutable typed results for the first, unresolved hierarchy slice."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from .models import OpaqueId, StrictModel
from .provenance import SourceReference

MAX_PARENT_ORIGINAL_TOPIC_ID_LENGTH = 512
MAX_TOC_ORDER = 10_000_000


class HierarchyDiagnosticCode(StrEnum):
    """Stable, non-echoing reasons that explicit metadata was unavailable."""

    PARENT_MISSING = "parent_missing"
    PARENT_DUPLICATE = "parent_duplicate"
    PARENT_BLANK = "parent_blank"
    PARENT_MALFORMED = "parent_malformed"
    PARENT_CONTROL = "parent_control"
    PARENT_OVERSIZED = "parent_oversized"
    ORDER_MISSING = "order_missing"
    ORDER_DUPLICATE = "order_duplicate"
    ORDER_INVALID = "order_invalid"
    ORDER_OVERSIZED = "order_oversized"


class TopicHierarchy(StrictModel):
    """One explicit parent edge and optional explicit peer order.

    ``-1`` is an explicit root marker.  Any other value is retained exactly;
    resolution, scope checks, and cycle checks deliberately belong to a later
    graph/index slice.
    """

    parent_original_topic_id: StrictStr = Field(
        min_length=1, max_length=MAX_PARENT_ORIGINAL_TOPIC_ID_LENGTH
    )
    toc_order: Annotated[StrictInt, Field(gt=0, le=MAX_TOC_ORDER)] | None = None

    @field_validator("parent_original_topic_id")
    @classmethod
    def validate_parent_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("parent_original_topic_id must not be blank")
        if value != value.strip():
            raise ValueError("parent_original_topic_id must not have edge whitespace")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("parent_original_topic_id must not contain controls")
        return value


class TopicHierarchyAssessment(StrictModel):
    """Source-bound extraction result; parent references remain unresolved."""

    topic_id: OpaqueId
    source: SourceReference
    hierarchy: TopicHierarchy | None = None
    diagnostic_codes: tuple[HierarchyDiagnosticCode, ...] = ()

    @model_validator(mode="after")
    def validate_article_source(self) -> TopicHierarchyAssessment:
        if self.source.section_id is not None:
            raise ValueError("hierarchy source must be an article-level reference")
        return self

    @property
    def diagnostics(self) -> tuple[HierarchyDiagnosticCode, ...]:
        """Compatibility-readable alias for the stable diagnostic codes."""
        return self.diagnostic_codes

    @property
    def source_reference(self) -> SourceReference:
        """Explicit provenance without inventing a section anchor."""
        return self.source


# Descriptive aliases for callers that use the shorter domain terminology.
HierarchyMetadata = TopicHierarchy
HierarchyAssessment = TopicHierarchyAssessment
HierarchyDiagnostic = HierarchyDiagnosticCode

__all__ = [
    "HierarchyAssessment",
    "HierarchyDiagnostic",
    "HierarchyDiagnosticCode",
    "HierarchyMetadata",
    "MAX_PARENT_ORIGINAL_TOPIC_ID_LENGTH",
    "MAX_TOC_ORDER",
    "TopicHierarchy",
    "TopicHierarchyAssessment",
]
