"""Strict domain contracts for the topic query service."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import Field, StrictStr, field_validator

from twincat_knowledge.domain.models import StrictModel

MAX_QUERY_CHARS = 512
MAX_QUERY_UTF8_BYTES = 2048
MAX_CURSOR_CHARS = 2048
MAX_PAGE_SIZE = 20

SearchKind = Literal[
    "topics",
    "symbols",
    "libraries",
    "devices",
    "errors",
    "examples",
]
LanguageFilter = Literal["de", "en", "any"]
ResponseStatus = Literal["ok", "not_found", "ambiguous", "not_available", "error"]


class QueryFilters(StrictModel):
    """Filters understood by the public topic search contract."""

    snapshot_id: StrictStr | None = Field(default=None, max_length=256)
    language: LanguageFilter | None = None
    library_id: StrictStr | None = Field(default=None, max_length=256)
    product_family: StrictStr | None = Field(default=None, max_length=512)
    documented_version: StrictStr | None = Field(default=None, max_length=128)
    device_revision: StrictStr | None = Field(default=None, max_length=128)


class _QueryInput(StrictModel):
    limit: int = Field(default=5, strict=True, ge=1, le=MAX_PAGE_SIZE)
    cursor: StrictStr | None = Field(default=None, max_length=MAX_CURSOR_CHARS)


class SearchInput(_QueryInput):
    query: StrictStr = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    kinds: tuple[SearchKind, ...] = ("topics",)
    filters: QueryFilters | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("query must not contain NUL")
        if len(value.encode("utf-8")) > MAX_QUERY_UTF8_BYTES:
            raise ValueError("query exceeds the bounded UTF-8 limit")
        return value

    @field_validator("kinds")
    @classmethod
    def validate_kinds(cls, value: tuple[SearchKind, ...]) -> tuple[SearchKind, ...]:
        if len(value) > 8:
            raise ValueError("too many search kinds")
        return value


class GetTopicInput(_QueryInput):
    topic_id: StrictStr = Field(min_length=1, max_length=256)
    section_ids: tuple[StrictStr, ...] | None = Field(default=None, max_length=1_000)


class CorpusStatusInput(_QueryInput):
    snapshot_id: StrictStr | None = Field(default=None, max_length=256)
    detail: Literal["summary", "coverage"] = "summary"


class BrowseTopicsInput(_QueryInput):
    """Strict request for roots or one level of explicit topic children."""

    parent_topic_id: StrictStr | None = Field(
        default=None, min_length=1, max_length=256
    )
    filters: QueryFilters | None = None


# Descriptive aliases make the three top-level contracts discoverable without
# creating alternate request envelopes.
TopicSearchInput = SearchInput
TopicGetInput = GetTopicInput
TopicBrowseInput = BrowseTopicsInput
GetCorpusStatusInput = CorpusStatusInput


class SourceCitation(StrictModel):
    """A returned source pointer plus preserved snapshot applicability facts."""

    source_id: StrictStr = Field(min_length=1, max_length=256)
    snapshot_id: StrictStr = Field(min_length=1, max_length=256)
    topic_id: StrictStr | None = Field(default=None, max_length=256)
    section_id: StrictStr | None = Field(default=None, max_length=256)
    title: StrictStr | None = Field(default=None, max_length=4_096)
    language: Literal["de", "en"]
    canonical_url: StrictStr | None = Field(default=None, max_length=2_048)
    locator: StrictStr = Field(min_length=1, max_length=2_048)
    content_hash: StrictStr = Field(pattern=r"^[0-9a-fA-F]{64}$")
    documented_version: StrictStr | None = Field(default=None, max_length=128)
    applicability: Literal["known", "unknown"]


class SearchProvenance(StrictModel):
    """Compact item attribution; full source pointers live in the envelope."""

    source_id: StrictStr = Field(min_length=1, max_length=256)
    snapshot_id: StrictStr = Field(min_length=1, max_length=256)
    topic_id: StrictStr | None = Field(default=None, max_length=256)


class SearchItem(StrictModel):
    id: StrictStr = Field(min_length=1, max_length=256)
    title: StrictStr = Field(max_length=4_096)
    snippet: StrictStr = Field(max_length=1_024)
    kind: Literal["topics"] = "topics"
    source: SearchProvenance


class SearchData(StrictModel):
    items: tuple[SearchItem, ...]
    total: int | None = Field(default=None, strict=True, ge=0)
    has_more: bool
    applied_filters: QueryFilters | None = None


class TopicMetadataData(StrictModel):
    name: StrictStr = Field(max_length=512)
    content: StrictStr = Field(max_length=16_384)
    attributes: tuple[tuple[StrictStr, StrictStr], ...] = ()


class TopicSectionData(StrictModel):
    id: StrictStr = Field(min_length=1, max_length=256)
    kind: Literal["paragraph", "code", "table", "warning"]
    text: StrictStr | None = None
    code: StrictStr | None = None
    language: StrictStr | None = Field(default=None, max_length=128)
    rows: tuple[tuple[StrictStr, ...], ...] = ()
    source: SourceCitation


class TopicData(StrictModel):
    topic_id: StrictStr = Field(min_length=1, max_length=256)
    title: StrictStr = Field(max_length=4_096)
    original_topic_id: StrictStr | None = Field(default=None, max_length=512)
    library: StrictStr = Field(min_length=1, max_length=256)
    language: Literal["de", "en"]
    metadata: tuple[TopicMetadataData, ...] = ()
    sections: tuple[TopicSectionData, ...] = ()
    image_refs: tuple[StrictStr, ...] = ()
    help_ids: tuple[StrictStr, ...] = ()
    complete: bool


class LanguageCount(StrictModel):
    language: Literal["de", "en"]
    count: int = Field(strict=True, ge=0)


class StatusSource(StrictModel):
    source_id: StrictStr = Field(min_length=1, max_length=256)
    snapshot_id: StrictStr = Field(min_length=1, max_length=256)
    language: Literal["de", "en"]
    content_hash: StrictStr = Field(pattern=r"^[0-9a-fA-F]{64}$")
    documented_version: StrictStr | None = Field(default=None, max_length=128)
    applicability: Literal["known", "unknown"]


class StatusInventory(StrictModel):
    documents_total: int = Field(strict=True, ge=0)
    documents_imported: int = Field(strict=True, ge=0)
    documents_skipped: int = Field(strict=True, ge=0)
    documents_failed: int = Field(strict=True, ge=0)


class CorpusStatusData(StrictModel):
    package_snapshot_id: StrictStr = Field(min_length=1, max_length=256)
    topic_count: int = Field(strict=True, ge=0)
    section_count: int = Field(strict=True, ge=0)
    language_counts: tuple[LanguageCount, ...]
    search_modes: tuple[Literal["lexical"], ...]
    implemented_categories: tuple[Literal["topics"], ...]
    count_fields: tuple[Literal["topics", "sections", "languages"], ...]
    source_count: int = Field(strict=True, ge=0)
    sources: tuple[StatusSource, ...]
    inventory: StatusInventory


class BrowseBreadcrumbItem(StrictModel):
    """The bounded identity/title projection of one breadcrumb node."""

    topic_id: StrictStr = Field(min_length=1, max_length=256)
    title: StrictStr = Field(max_length=4_096)


class BrowseTopicItem(StrictModel):
    """A topic tree row; article bodies are intentionally absent."""

    topic_id: StrictStr = Field(min_length=1, max_length=256)
    original_topic_id: StrictStr | None = Field(default=None, max_length=512)
    title: StrictStr = Field(max_length=4_096)
    language: Literal["de", "en"]
    library: StrictStr = Field(min_length=1, max_length=256)
    parent_topic_id: StrictStr | None = Field(default=None, max_length=256)
    hierarchy: Literal["available", "unknown", "unresolved", "ambiguous"]
    order: int | None = Field(default=None, strict=True, ge=1)
    order_available: bool
    order_tied: bool
    ordering: Literal["toc_order", "technical_canonical_id"]
    breadcrumb: tuple[BrowseBreadcrumbItem, ...]
    source: SourceCitation


class BrowseTopicsData(StrictModel):
    items: tuple[BrowseTopicItem, ...]
    total: int | None = Field(default=None, strict=True, ge=0)
    has_more: bool
    parent_topic_id: StrictStr | None = Field(default=None, max_length=256)
    applied_filters: QueryFilters | None = None
    hierarchy_available: bool


T = TypeVar("T")


class ResponseEnvelope(StrictModel, Generic[T]):  # noqa: UP046
    """Common bounded response envelope used by all three service methods."""

    schema_version: Literal["1.0"] = "1.0"
    status: ResponseStatus
    snapshot_ids: tuple[StrictStr, ...]
    data: T | None = None
    sources: tuple[SourceCitation, ...] = ()
    warnings: tuple[StrictStr, ...] = ()
    truncated: bool = False
    next_cursor: StrictStr | None = Field(default=None, max_length=MAX_CURSOR_CHARS)


SearchResponse = ResponseEnvelope[SearchData]
TopicResponse = ResponseEnvelope[TopicData]
CorpusStatusResponse = ResponseEnvelope[CorpusStatusData]
BrowseTopicsResponse = ResponseEnvelope[BrowseTopicsData]

__all__ = [
    "CorpusStatusData",
    "CorpusStatusInput",
    "CorpusStatusResponse",
    "BrowseBreadcrumbItem",
    "BrowseTopicItem",
    "BrowseTopicsData",
    "BrowseTopicsInput",
    "BrowseTopicsResponse",
    "GetCorpusStatusInput",
    "GetTopicInput",
    "LanguageCount",
    "QueryFilters",
    "ResponseEnvelope",
    "ResponseStatus",
    "SearchData",
    "SearchInput",
    "SearchItem",
    "SearchResponse",
    "SearchProvenance",
    "SourceCitation",
    "StatusInventory",
    "StatusSource",
    "TopicBrowseInput",
    "TopicData",
    "TopicGetInput",
    "TopicMetadataData",
    "TopicResponse",
    "TopicSearchInput",
    "TopicSectionData",
]
