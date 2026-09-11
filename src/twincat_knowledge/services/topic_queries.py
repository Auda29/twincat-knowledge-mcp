"""Real, read-only bounded topic query service (not an MCP adapter)."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Iterable
from typing import Literal, TypeVar, cast

from pydantic import BaseModel

from twincat_knowledge.corpus.topic_index import MAX_SEARCH_OFFSET
from twincat_knowledge.corpus.topic_package_load import (
    LoadedTopicPackage,
    TopicPackageLoadError,
)
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic

from .query_contracts import (
    CorpusStatusData,
    CorpusStatusInput,
    GetTopicInput,
    LanguageCount,
    QueryFilters,
    ResponseEnvelope,
    SearchData,
    SearchInput,
    SearchItem,
    SearchProvenance,
    SourceCitation,
    StatusInventory,
    StatusSource,
    TopicData,
    TopicMetadataData,
    TopicSectionData,
)
from .query_cursor import CursorError, QueryCursor

MAX_DOMAIN_RESPONSE_BYTES = 12 * 1024
MAX_SNIPPET_CHARS = 512
SUPPORTED_TOPIC_KINDS = frozenset({"topics"})

T = TypeVar("T")
RequestT = TypeVar("RequestT", bound=BaseModel)


def _has_bypassed_fields(value: object) -> bool:
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        if any(key not in fields for key in value.__dict__):
            return True
        return any(_has_bypassed_fields(item) for item in value.__dict__.values())
    if isinstance(value, dict):
        return any(
            _has_bypassed_fields(key) or _has_bypassed_fields(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_has_bypassed_fields(item) for item in value)
    return False


def _validated_request(model_type: type[RequestT], request: object) -> RequestT | None:  # noqa: UP047
    """Revalidate even instances made with Pydantic bypass APIs."""
    if not isinstance(request, model_type) or _has_bypassed_fields(request):
        return None
    try:
        payload = request.model_dump(mode="python", warnings=False)
        return model_type.model_validate(payload)
    except Exception:
        return None


def _json_bytes(model: object) -> int:
    value: object
    if isinstance(model, BaseModel):
        value = model.model_dump(mode="json")
    else:
        value = model
    return len(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    )


def _filters_payload(filters: QueryFilters | None) -> object:
    return None if filters is None else filters.model_dump(mode="json")


def _unique_sources(sources: Iterable[SourceCitation]) -> tuple[SourceCitation, ...]:
    result: list[SourceCitation] = []
    seen: set[str] = set()
    for source in sources:
        key = source.model_dump_json()
        if key not in seen:
            seen.add(key)
            result.append(source)
    return tuple(result)


class TopicQueryService:
    """Serve one caller-owned, already validated package generation.

    The service never opens, reloads, or closes ``loaded``.  A cursor is valid
    only for this service instance and this exact manifest/artifact generation.
    """

    def __init__(self, loaded: LoadedTopicPackage | None) -> None:
        self._loaded = loaded
        self._cursor = QueryCursor(secrets.token_bytes(32))

    def _generation(self) -> str:
        assert self._loaded is not None
        manifest = self._loaded.manifest
        facts = {
            "package_snapshot_id": manifest.corpus_manifest.snapshot_id,
            "manifest": manifest.model_dump(mode="json"),
            "files": [file.model_dump(mode="json") for file in manifest.files],
        }
        return hashlib.sha256(
            json.dumps(
                facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    def _snapshot_ids(self) -> tuple[str, ...]:
        assert self._loaded is not None
        return (self._loaded.manifest.corpus_manifest.snapshot_id,)

    def _envelope(
        self,
        status: str,
        data: T | None = None,
        *,
        sources: tuple[SourceCitation, ...] = (),
        warnings: tuple[str, ...] = (),
        truncated: bool = False,
        next_cursor: str | None = None,
    ) -> ResponseEnvelope[T]:
        if self._loaded is None:
            snapshot_ids: tuple[str, ...] = ()
        else:
            try:
                snapshot_ids = self._snapshot_ids()
            except TopicPackageLoadError:
                snapshot_ids = ()
        return ResponseEnvelope[T](
            status=status,  # type: ignore[arg-type]
            snapshot_ids=snapshot_ids,
            data=data,
            sources=sources,
            warnings=warnings,
            truncated=truncated,
            next_cursor=next_cursor,
        )

    def _error(self, message: str) -> ResponseEnvelope[T]:
        # Messages are fixed service-domain text; no exception or path detail is
        # ever returned to a caller.
        return self._envelope("error", warnings=(message,))

    def _not_available(self, message: str) -> ResponseEnvelope[T]:
        return self._envelope("not_available", warnings=(message,))

    def _source(self, reference: SourceReference) -> SourceCitation:
        assert self._loaded is not None
        snapshot = next(
            source
            for source in self._loaded.manifest.corpus_manifest.sources
            if (
                source.source_id,
                source.snapshot_id,
                source.language,
            )
            == (reference.source_id, reference.snapshot_id, reference.language)
        )
        return SourceCitation(
            **reference.model_dump(mode="python"),
            documented_version=snapshot.documented_version,
            applicability=snapshot.applicability,
        )

    @staticmethod
    def _snippet(topic: Topic) -> str:
        content = topic.title
        if topic.sections:
            section = topic.sections[0]
            if section.kind == "table":
                content = " | ".join(cell for row in section.rows for cell in row)
            else:
                content = (
                    section.text if section.text is not None else section.code or ""
                )
        return (
            content
            if len(content) <= MAX_SNIPPET_CHARS
            else content[:MAX_SNIPPET_CHARS] + "…"
        )

    def _supported_filters(self, filters: QueryFilters | None) -> str | None:
        if filters is None:
            return None
        for field in (
            "library_id",
            "product_family",
            "documented_version",
            "device_revision",
        ):
            if getattr(filters, field) is not None:
                return f"unsupported filter: {field}"
        return None

    def _package_snapshot_filter(self, snapshot_id: str | None) -> bool:
        assert self._loaded is not None
        return (
            snapshot_id is None
            or snapshot_id == self._loaded.manifest.corpus_manifest.snapshot_id
        )

    def _fits(self, response: object) -> bool:
        return _json_bytes(response) <= MAX_DOMAIN_RESPONSE_BYTES

    def search(self, request: SearchInput) -> ResponseEnvelope[SearchData]:
        """Search indexed topics with stable, bounded, authenticated pages."""
        validated_request = _validated_request(SearchInput, request)
        if validated_request is None:
            return self._error("invalid search input")
        request = validated_request
        if self._loaded is None:
            return self._not_available("validated topic corpus is not available")
        unsupported = self._supported_filters(request.filters)
        if unsupported is not None:
            return self._error(unsupported)
        if not request.kinds:
            return self._not_available("no searchable category was requested")
        if any(kind not in SUPPORTED_TOPIC_KINDS for kind in request.kinds):
            return self._not_available("requested search category is not available")
        try:
            generation = self._generation()
            filters_payload = {
                "filters": _filters_payload(request.filters),
                "kinds": request.kinds,
            }
            state = None
            if request.cursor is not None:
                state = self._cursor.decode(
                    request.cursor,
                    tool="tc_search",
                    generation=generation,
                    query=request.query,
                    filters=filters_payload,
                    selected_sections=None,
                    limit=request.limit,
                )
            position = 0 if state is None else state.position
            snapshot_id = (
                None if request.filters is None else request.filters.snapshot_id
            )
            if not self._package_snapshot_filter(snapshot_id):
                return self._envelope("not_found")
            language = None if request.filters is None else request.filters.language
            if language == "any":
                language = None
            topics: tuple[Topic, ...] = self._loaded.index.search(
                request.query,
                language=language,
                source_snapshot_id=None,
                limit=request.limit,
                offset=position,
            )
            lookahead: tuple[Topic, ...] = ()
            if (
                len(topics) == request.limit
                and position + request.limit <= MAX_SEARCH_OFFSET
            ):
                lookahead = self._loaded.index.search(
                    request.query,
                    language=language,
                    source_snapshot_id=None,
                    limit=1,
                    offset=position + request.limit,
                )
            has_more_at_limit = bool(lookahead)
            prefix_items: list[SearchItem] = []
            prefix_sources: list[SourceCitation] = []
            items: list[SearchItem] = []
            sources: list[SourceCitation] = []
            next_cursor: str | None = None
            for topic in topics:
                prefix_items.append(
                    SearchItem(
                        id=topic.id,
                        title=topic.title,
                        snippet=self._snippet(topic),
                        source=SearchProvenance(
                            source_id=topic.source.source_id,
                            snapshot_id=topic.source.snapshot_id,
                            topic_id=topic.source.topic_id,
                        ),
                    )
                )
                topic_source = self._source(topic.source)
                prefix_sources.append(topic_source)
                candidate_items = tuple(prefix_items)
                candidate_sources = _unique_sources(prefix_sources)
                candidate_has_more = (
                    len(candidate_items) < len(topics) or has_more_at_limit
                )
                candidate_cursor = None
                if candidate_has_more:
                    try:
                        candidate_cursor = self._cursor.encode(
                            tool="tc_search",
                            generation=generation,
                            query=request.query,
                            filters=filters_payload,
                            selected_sections=None,
                            limit=request.limit,
                            position=position + len(candidate_items),
                        )
                    except CursorError:
                        return self._error(
                            "search cursor cannot be issued within bounds"
                        )
                candidate = self._envelope(
                    "ok",
                    SearchData(
                        items=candidate_items,
                        total=None,
                        has_more=candidate_has_more,
                        applied_filters=request.filters,
                    ),
                    sources=candidate_sources,
                    truncated=candidate_has_more,
                    next_cursor=candidate_cursor,
                )
                if not self._fits(candidate):
                    continue
                items = list(candidate_items)
                sources = list(candidate_sources)
                next_cursor = candidate_cursor
            if not items and topics:
                return self._error("search result exceeds the response bound")
            consumed = len(items)
            has_more = consumed < len(topics) or has_more_at_limit
            if not has_more:
                next_cursor = None
            status = "ok" if items else "not_found"
            result = self._envelope(
                status,
                SearchData(
                    items=tuple(items),
                    total=None,
                    has_more=has_more,
                    applied_filters=request.filters,
                ),
                sources=_unique_sources(sources),
                truncated=has_more,
                next_cursor=next_cursor,
            )
            if not self._fits(result):
                return self._error("search result exceeds the response bound")
            return result
        except Exception:
            return self._error("topic search failed")

    def _section_data(self, section: Section) -> TopicSectionData:
        payload = section.model_dump(mode="python")
        payload["source"] = self._source(section.source)
        return TopicSectionData(**payload)

    def _topic_data(
        self, topic: Topic, sections: tuple[Section, ...], complete: bool
    ) -> TopicData:
        return TopicData(
            topic_id=topic.id,
            title=topic.title,
            original_topic_id=topic.original_topic_id,
            library=topic.library,
            language=topic.language,
            metadata=tuple(
                TopicMetadataData(**metadata.model_dump(mode="python"))
                for metadata in topic.metadata
            ),
            sections=tuple(self._section_data(section) for section in sections),
            image_refs=topic.image_refs,
            help_ids=topic.help_ids,
            complete=complete,
        )

    def get_topic(self, request: GetTopicInput) -> ResponseEnvelope[TopicData]:
        """Resolve one exact indexed ID and page only complete sections."""
        validated_request = _validated_request(GetTopicInput, request)
        if validated_request is None:
            return self._error("invalid topic input")
        request = validated_request
        if self._loaded is None:
            return self._not_available("validated topic corpus is not available")
        try:
            generation = self._generation()
            topic = self._loaded.index.get_topic(request.topic_id)
            if topic is None:
                return self._envelope("not_found")
            requested = request.section_ids
            if requested is not None and len(set(requested)) != len(requested):
                return self._error("section selection contains duplicate IDs")
            by_id = {section.id: section for section in topic.sections}
            if requested is not None:
                unknown = [
                    section_id for section_id in requested if section_id not in by_id
                ]
                if unknown:
                    return self._error("section selection contains an unknown ID")
                selected = tuple(
                    section for section in topic.sections if section.id in requested
                )
                selected_key: tuple[str, ...] | None = tuple(
                    section.id for section in selected
                )
            else:
                selected = topic.sections
                selected_key = None
            state = None
            if request.cursor is not None:
                state = self._cursor.decode(
                    request.cursor,
                    tool="tc_get_topic",
                    generation=generation,
                    query=topic.id,
                    filters=None,
                    selected_sections=selected_key,
                    limit=request.limit,
                )
                if requested is None and state.sections is not None:
                    if any(section_id not in by_id for section_id in state.sections):
                        return self._error("topic cursor refers to unknown sections")
                    selected = tuple(by_id[section_id] for section_id in state.sections)
                    selected_key = state.sections
                elif requested is not None and state.sections != selected_key:
                    return self._error("topic cursor does not match section selection")
            position = 0 if state is None else state.position
            if position > len(selected):
                return self._error("topic cursor is outside the section range")
            topic_source = self._source(topic.source)
            base = self._topic_data(topic, (), complete=position >= len(selected))
            base_response = self._envelope("ok", base, sources=(topic_source,))
            if not self._fits(base_response):
                return self._error("topic metadata is oversized for the response bound")
            prefix_page: list[Section] = []
            page: list[Section] = []
            next_cursor: str | None = None
            for section in selected[position : position + request.limit]:
                prefix_page.append(section)
                candidate_sections = tuple(prefix_page)
                candidate_data = self._topic_data(
                    topic,
                    candidate_sections,
                    complete=position + len(candidate_sections) >= len(selected),
                )
                candidate_sources = _unique_sources(
                    [
                        topic_source,
                        *(self._source(item.source) for item in candidate_sections),
                    ]
                )
                candidate_has_more = position + len(candidate_sections) < len(selected)
                candidate_cursor = None
                if candidate_has_more:
                    try:
                        candidate_cursor = self._cursor.encode(
                            tool="tc_get_topic",
                            generation=generation,
                            query=topic.id,
                            filters=None,
                            selected_sections=selected_key,
                            limit=request.limit,
                            position=position + len(candidate_sections),
                        )
                    except CursorError:
                        return self._error(
                            "topic cursor cannot be issued within bounds"
                        )
                candidate = self._envelope(
                    "ok",
                    candidate_data,
                    sources=candidate_sources,
                    truncated=candidate_has_more,
                    next_cursor=candidate_cursor,
                )
                if not self._fits(candidate):
                    continue
                page = list(candidate_sections)
                next_cursor = candidate_cursor
            if not page and selected[position:]:
                return self._error("oversized content cannot fit in one section")
            consumed = len(page)
            has_more = position + consumed < len(selected)
            if not has_more:
                next_cursor = None
            data = self._topic_data(topic, tuple(page), complete=not has_more)
            sources = _unique_sources(
                [topic_source, *(self._source(section.source) for section in page)]
            )
            result = self._envelope(
                "ok",
                data,
                sources=sources,
                truncated=has_more,
                next_cursor=next_cursor,
            )
            if not self._fits(result):
                return self._error("topic result exceeds the response bound")
            return result
        except Exception:
            return self._error("topic retrieval failed")

    def _status_source(self, source: object) -> StatusSource:
        # The loader has already validated this model; keep rights references and
        # operator paths out of status projections.
        return StatusSource(
            source_id=source.source_id,  # type: ignore[attr-defined]
            snapshot_id=source.snapshot_id,  # type: ignore[attr-defined]
            language=source.language,  # type: ignore[attr-defined]
            content_hash=source.content_hash,  # type: ignore[attr-defined]
            documented_version=source.documented_version,  # type: ignore[attr-defined]
            applicability=source.applicability,  # type: ignore[attr-defined]
        )

    def get_corpus_status(
        self, request: CorpusStatusInput
    ) -> ResponseEnvelope[CorpusStatusData]:
        """Project validated manifest/summary facts and a bounded source inventory."""
        validated_request = _validated_request(CorpusStatusInput, request)
        if validated_request is None:
            return self._error("invalid status input")
        request = validated_request
        if self._loaded is None:
            return self._not_available("validated topic corpus is not available")
        try:
            manifest = self._loaded.manifest
            package_snapshot = manifest.corpus_manifest.snapshot_id
            if (
                request.snapshot_id is not None
                and request.snapshot_id != package_snapshot
            ):
                return self._envelope("not_found")
            generation = self._generation()
            filter_payload = {
                "snapshot_id": request.snapshot_id,
                "detail": request.detail,
            }
            state = None
            if request.cursor is not None:
                state = self._cursor.decode(
                    request.cursor,
                    tool="tc_get_corpus_status",
                    generation=generation,
                    query=request.detail,
                    filters=filter_payload,
                    selected_sections=None,
                    limit=request.limit,
                )
            position = 0 if state is None else state.position
            all_sources = manifest.corpus_manifest.sources
            source_count = len(all_sources)
            if position > source_count:
                return self._error("status cursor is outside the source range")
            summary = self._loaded.summary
            counts = tuple(
                LanguageCount(language=cast(Literal["de", "en"], language), count=count)
                for language, count in sorted(summary.language_counts.items())
            )
            prefix_page: list[StatusSource] = []
            page: list[StatusSource] = []
            next_cursor: str | None = None
            for source in all_sources[position : position + request.limit]:
                prefix_page.append(self._status_source(source))
                candidate_has_more = position + len(prefix_page) < source_count
                candidate_cursor = None
                if candidate_has_more:
                    try:
                        candidate_cursor = self._cursor.encode(
                            tool="tc_get_corpus_status",
                            generation=generation,
                            query=request.detail,
                            filters=filter_payload,
                            selected_sections=None,
                            limit=request.limit,
                            position=position + len(prefix_page),
                        )
                    except CursorError:
                        return self._error(
                            "status cursor cannot be issued within bounds"
                        )
                data = CorpusStatusData(
                    package_snapshot_id=package_snapshot,
                    topic_count=summary.topic_count,
                    section_count=summary.section_count,
                    language_counts=counts,
                    search_modes=("lexical",),
                    implemented_categories=("topics",),
                    count_fields=("topics", "sections", "languages"),
                    source_count=source_count,
                    sources=tuple(prefix_page),
                    inventory=StatusInventory(
                        **manifest.corpus_manifest.inventory.model_dump(mode="python")
                    ),
                )
                candidate = self._envelope(
                    "ok",
                    data,
                    warnings=(
                        "coverage counts describe validated topics only; other entity "
                        "categories are not implemented",
                    ),
                    truncated=candidate_has_more,
                    next_cursor=candidate_cursor,
                )
                if not self._fits(candidate):
                    continue
                page = list(prefix_page)
                next_cursor = candidate_cursor
            if not page and all_sources[position:]:
                return self._error("corpus status exceeds the response bound")
            has_more = position + len(page) < source_count
            if not has_more:
                next_cursor = None
            data = CorpusStatusData(
                package_snapshot_id=package_snapshot,
                topic_count=summary.topic_count,
                section_count=summary.section_count,
                language_counts=counts,
                search_modes=("lexical",),
                implemented_categories=("topics",),
                count_fields=("topics", "sections", "languages"),
                source_count=source_count,
                sources=tuple(page),
                inventory=StatusInventory(
                    **manifest.corpus_manifest.inventory.model_dump(mode="python")
                ),
            )
            result = self._envelope(
                "ok",
                data,
                warnings=(
                    "coverage counts describe validated topics only; other entity "
                    "categories are not implemented",
                ),
                truncated=has_more,
                next_cursor=next_cursor,
            )
            if not self._fits(result):
                return self._error("corpus status exceeds the response bound")
            return result
        except Exception:
            return self._error("corpus status failed")


__all__ = [
    "MAX_DOMAIN_RESPONSE_BYTES",
    "TopicQueryService",
]
