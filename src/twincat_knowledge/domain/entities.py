"""Immutable facts extracted from explicit normalized article evidence."""

from typing import Literal

from pydantic import Field, StrictStr, model_validator

from .models import OpaqueId, StrictModel, VersionText
from .provenance import SourceReference

EntityKind = Literal["symbol", "library", "error"]


class TypedEntity(StrictModel):
    """One evidence-scoped fact, with unknown context represented explicitly.

    ``topic_id`` is the canonical normalized Topic.id. The original help ID
    remains in each citation. A version describes source documentation only;
    it does not assert installed software or runtime applicability.
    """

    id: OpaqueId
    kind: EntityKind
    name: StrictStr = Field(min_length=1, max_length=512)
    namespace: StrictStr | None = Field(default=None, max_length=512)
    library: StrictStr | None = Field(default=None, max_length=512)
    documented_version: VersionText | None = None
    declaration: StrictStr | None = Field(default=None, max_length=262_144)
    error_code: StrictStr | None = Field(default=None, max_length=128)
    error_domain: StrictStr | None = Field(default=None, max_length=512)
    description: StrictStr | None = Field(default=None, max_length=16_384)
    topic_id: OpaqueId
    sources: tuple[SourceReference, ...] = Field(min_length=1, max_length=64)
    missing_fields: tuple[StrictStr, ...] = Field(max_length=16)
    warnings: tuple[StrictStr, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_kind(self) -> "TypedEntity":
        if self.kind == "symbol" and self.declaration is None:
            raise ValueError("symbol requires declaration evidence")
        if self.kind == "library" and self.library != self.name:
            raise ValueError("library name must match its explicit library field")
        if self.kind == "error" and self.error_code is None:
            raise ValueError("error requires error_code evidence")
        if self.kind != "symbol" and self.declaration is not None:
            raise ValueError("declaration is only valid for symbols")
        if self.kind != "error" and (
            self.error_code is not None or self.error_domain is not None
        ):
            raise ValueError("error fields are only valid for errors")
        return self


__all__ = ["EntityKind", "TypedEntity"]
