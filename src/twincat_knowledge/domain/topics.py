"""Immutable normalized topic and section models.

These models deliberately depend only on domain/provenance types.  Ingest
adapters may produce them, but normalized data remains usable without an
adapter implementation.
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import Field, StrictStr, model_validator

from .models import Language, OpaqueId, StrictModel
from .provenance import SourceReference

SectionKind = Literal["paragraph", "code", "table", "warning"]


class Section(StrictModel):
    """One immutable, ordered, typed normalized article section."""

    id: OpaqueId
    kind: SectionKind
    text: StrictStr | None = None
    code: StrictStr | None = None
    language: StrictStr | None = Field(default=None, max_length=128)
    rows: tuple[tuple[StrictStr, ...], ...] = ()
    source: SourceReference

    @model_validator(mode="after")
    def validate_payload(self) -> Section:
        if self.kind in {"paragraph", "warning"}:
            if self.text is None or self.code is not None or self.rows:
                raise ValueError(f"{self.kind} section requires text only")
        elif self.kind == "code":
            if self.code is None or self.text is not None or self.rows:
                raise ValueError("code section requires code only")
        elif self.kind == "table":
            if self.text is not None or self.code is not None:
                raise ValueError("table section requires rows only")
        return self

    @property
    def section_id(self) -> str:
        """Readable alias for the opaque section identifier."""
        return self.id

    @property
    def content(self) -> str | tuple[tuple[str, ...], ...]:
        """Return the typed payload without exposing mutable state."""
        if self.kind == "table":
            return self.rows
        payload = self.text if self.kind in {"paragraph", "warning"} else self.code
        return cast(str, payload)


class Topic(StrictModel):
    """One immutable normalized InfoSys topic bound to a source snapshot."""

    id: OpaqueId
    title: StrictStr = Field(max_length=4_096)
    original_topic_id: StrictStr | None = Field(default=None, max_length=512)
    library: StrictStr = Field(min_length=1, max_length=256)
    language: Language
    source: SourceReference
    sections: tuple[Section, ...] = ()
    image_refs: tuple[StrictStr, ...] = ()
    help_ids: tuple[StrictStr, ...] = ()

    @property
    def topic_id(self) -> str | None:
        """Compatibility alias for the original help-topic identifier."""
        return self.original_topic_id

    @property
    def original_help_topic_id(self) -> str | None:
        """Explicitly named alias for callers avoiding ``topic_id`` ambiguity."""
        return self.original_topic_id


__all__ = ["Section", "SectionKind", "Topic"]
