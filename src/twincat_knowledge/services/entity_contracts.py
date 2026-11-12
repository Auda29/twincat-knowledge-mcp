"""Bounded contracts for extracted, source-backed entities."""

import re

from pydantic import Field, StrictStr, field_validator

from twincat_knowledge.domain.entities import TypedEntity
from twincat_knowledge.domain.models import StrictModel

from .query_contracts import ResponseEnvelope


class EntityFilters(StrictModel):
    namespace: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    library: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    documented_version: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )


class FindEntitiesInput(StrictModel):
    query: StrictStr = Field(min_length=1, max_length=512)
    filters: EntityFilters | None = None
    limit: int = Field(default=5, strict=True, ge=1, le=20)
    cursor: StrictStr | None = Field(default=None, max_length=2048)


class LookupErrorInput(StrictModel):
    code: StrictStr = Field(min_length=1, max_length=256)
    domain: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    filters: EntityFilters | None = None
    limit: int = Field(default=5, strict=True, ge=1, le=20)
    cursor: StrictStr | None = Field(default=None, max_length=2048)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not re.fullmatch(
            r"(?:[+-]?[0-9]{1,20}|0[xX][0-9a-fA-F]{1,16}|16#[0-9a-fA-F]{1,16})",
            value.strip(),
        ):
            raise ValueError("unsupported error code spelling")
        return value


class GetSymbolInput(StrictModel):
    symbol_id: StrictStr = Field(min_length=1, max_length=256)


class GetLibraryInput(StrictModel):
    library_id: StrictStr = Field(min_length=1, max_length=256)


class EntityResults(StrictModel):
    items: tuple[TypedEntity, ...]
    has_more: bool
    coverage_available: bool


EntityResponse = ResponseEnvelope[EntityResults]
