"""Strict, source-neutral domain models for corpus provenance."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

from .errors import VersionApplicabilityError

MAX_ID_LENGTH = 256
MAX_VERSION_LENGTH = 128
MAX_REFERENCE_LENGTH = 512
MAX_COUNT = 10_000_000
MAX_SNAPSHOTS = 10_000


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value


OpaqueId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=MAX_ID_LENGTH),
    AfterValidator(_non_blank),
]
VersionText = Annotated[
    StrictStr,
    Field(min_length=1, max_length=MAX_VERSION_LENGTH),
    AfterValidator(_non_blank),
]
ReferenceText = Annotated[
    StrictStr,
    Field(min_length=1, max_length=MAX_REFERENCE_LENGTH),
    AfterValidator(_non_blank),
]
Language = Literal["de", "en"]
AwareDateTime = Annotated[datetime, AfterValidator(_aware_datetime)]


class StrictModel(BaseModel):
    """Shared policy: no coercion, unknown fields, or mutable instances."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        frozen=True,
    )


class SourceSnapshot(StrictModel):
    """One approved source generation represented in a corpus package.

    ``documented_version`` and ``applicability`` deliberately carry unknown
    applicability instead of silently asserting a version range.
    """

    schema_version: VersionText = "1.0"
    source_id: OpaqueId
    snapshot_id: OpaqueId
    imported_at: AwareDateTime
    documented_version: VersionText | None = None
    applicability: Literal["known", "unknown"] = "unknown"
    language: Language
    content_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-fA-F]{64}$")]
    rights_reference: ReferenceText
    parser_version: VersionText

    @model_validator(mode="after")
    def validate_version_applicability(self) -> "SourceSnapshot":
        if self.applicability == "known" and self.documented_version is None:
            raise VersionApplicabilityError(
                "applicability='known' requires documented_version"
            )
        if self.applicability == "unknown" and self.documented_version is not None:
            raise VersionApplicabilityError(
                "documented_version must be absent when applicability='unknown'"
            )
        return self


class EntityCounts(StrictModel):
    """Optional inventory counts for normalized corpus entities."""

    topics: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    sections: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    libraries: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    symbols: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    devices: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    errors: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    examples: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
    relations: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)] = 0
