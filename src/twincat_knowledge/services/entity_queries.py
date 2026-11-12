"""Lazy typed views over an already verified topic package."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, cast

from twincat_knowledge.corpus.entity_index import EntityIndex
from twincat_knowledge.corpus.topic_package_load import LoadedTopicPackage
from twincat_knowledge.ingest.entities import EXTRACTOR_VERSION

from .entity_contracts import (
    EntityResponse,
    EntityResults,
    FindEntitiesInput,
    GetLibraryInput,
    GetSymbolInput,
    LookupErrorInput,
)
from .query_contracts import SourceCitation
from .query_cursor import QueryCursor
from .topic_queries import MAX_DOMAIN_RESPONSE_BYTES, _json_bytes, _validated_request


class EntityQueryService:
    def __init__(self, loaded: LoadedTopicPackage | None) -> None:
        self._loaded = loaded
        self._index: EntityIndex | None = None
        self._cursor = QueryCursor(secrets.token_bytes(32))

    def _envelope(
        self,
        status: str,
        data: EntityResults | None = None,
        *,
        sources: tuple[SourceCitation, ...] = (),
        warnings: tuple[str, ...] = (),
        next_cursor: str | None = None,
    ) -> EntityResponse:
        try:
            ids = (
                ()
                if self._loaded is None
                else (self._loaded.manifest.corpus_manifest.snapshot_id,)
            )
        except Exception:
            ids = ()
        return EntityResponse(
            status=status,  # type: ignore[arg-type]
            snapshot_ids=ids,
            data=data,
            sources=sources,
            warnings=warnings,
            truncated=next_cursor is not None,
            next_cursor=next_cursor,
        )

    def _get_index(self) -> EntityIndex:
        assert self._loaded is not None
        # Check the caller-owned handle even after extraction is cached.
        index = self._loaded.index
        if self._index is None:
            with index.iter_topics() as topics:
                self._index = EntityIndex(topics)
        return self._index

    def _source(self, ref: Any) -> SourceCitation:
        assert self._loaded is not None
        snapshot = next(
            s
            for s in self._loaded.manifest.corpus_manifest.sources
            if (s.source_id, s.snapshot_id, s.language)
            == (ref.source_id, ref.snapshot_id, ref.language)
        )
        return SourceCitation(
            **ref.model_dump(mode="python"),
            documented_version=snapshot.documented_version,
            applicability=snapshot.applicability,
        )

    def _find(
        self, kind: str, request: object, model: type, tool: str
    ) -> EntityResponse:
        request = _validated_request(model, request)
        if request is None:
            return self._envelope("error", warnings=("invalid entity query input",))
        if self._loaded is None:
            return self._envelope(
                "not_available", warnings=("validated topic corpus is not available",)
            )
        try:
            index = self._get_index()
            query = request.query if kind != "error" else request.code
            filters = (
                {}
                if request.filters is None
                else request.filters.model_dump(exclude_none=True)
            )
            if kind == "error":
                filters.update(error_code=request.code, error_domain=request.domain)
            else:
                filters["name"] = request.query
            generation = hashlib.sha256(
                json.dumps(
                    {
                        "manifest": self._loaded.manifest.model_dump(mode="json"),
                        "extractor": EXTRACTOR_VERSION,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            cursor_args = dict(
                tool=tool,
                generation=generation,
                query=query,
                filters=filters,
                selected_sections=None,
                limit=request.limit,
            )
            position = (
                0
                if request.cursor is None
                else self._cursor.decode(request.cursor, **cursor_args).position
            )
            lookup = {key: value for key, value in filters.items() if value is not None}
            matches_first = index.find(kind=kind, limit=2, offset=0, **lookup)
            coverage = bool(index.find(kind=kind, limit=1, offset=0))
            candidates = index.find(
                kind=kind, limit=request.limit, offset=position, **lookup
            )
            if position and not candidates:
                return self._envelope(
                    "error", warnings=("entity cursor is outside the result range",)
                )
            items: list[Any] = []
            for entity in candidates:
                candidate = items + [entity]
                more = bool(
                    index.find(
                        kind=kind, limit=1, offset=position + len(candidate), **lookup
                    )
                )
                cursor = (
                    self._cursor.encode(
                        position=position + len(candidate), **cursor_args
                    )
                    if more
                    else None
                )
                sources = tuple(
                    dict.fromkeys(
                        self._source(ref) for item in candidate for ref in item.sources
                    )
                )
                response = self._envelope(
                    "ambiguous" if len(matches_first) > 1 else "ok",
                    EntityResults(
                        items=tuple(candidate),
                        has_more=more,
                        coverage_available=coverage,
                    ),
                    sources=sources,
                    next_cursor=cursor,
                )
                if _json_bytes(response) > MAX_DOMAIN_RESPONSE_BYTES:
                    break
                items = candidate
            if not items and candidates:
                return self._envelope(
                    "error", warnings=("entity record exceeds the response bound",)
                )
            more = (
                bool(
                    index.find(
                        kind=kind, limit=1, offset=position + len(items), **lookup
                    )
                )
                if items
                else False
            )
            cursor = (
                self._cursor.encode(position=position + len(items), **cursor_args)
                if more
                else None
            )
            sources = tuple(
                dict.fromkeys(
                    self._source(ref) for item in items for ref in item.sources
                )
            )
            status = (
                "ambiguous"
                if len(matches_first) > 1
                else "ok"
                if items
                else "not_found"
            )
            warnings = (
                () if coverage else ("no typed entities of this kind were extracted",)
            )
            return self._envelope(
                status,
                EntityResults(
                    items=tuple(items), has_more=more, coverage_available=coverage
                ),
                sources=sources,
                warnings=warnings,
                next_cursor=cursor,
            )
        except Exception:
            return self._envelope("error", warnings=("entity query failed",))

    def find_symbols(self, request: FindEntitiesInput) -> EntityResponse:
        return self._find("symbol", request, FindEntitiesInput, "tc_find_symbols")

    def find_libraries(self, request: FindEntitiesInput) -> EntityResponse:
        return self._find("library", request, FindEntitiesInput, "tc_find_libraries")

    def lookup_error(self, request: LookupErrorInput) -> EntityResponse:
        return self._find("error", request, LookupErrorInput, "tc_lookup_error")

    def _get(self, kind: str, request: object) -> EntityResponse:
        request = _validated_request(
            GetSymbolInput if kind == "symbol" else GetLibraryInput, request
        )
        if request is None:
            return self._envelope("error", warnings=("invalid entity query input",))
        if self._loaded is None:
            return self._envelope(
                "not_available", warnings=("validated topic corpus is not available",)
            )
        try:
            index = self._get_index()
            entity = index.get(
                cast(GetSymbolInput, request).symbol_id
                if kind == "symbol"
                else cast(GetLibraryInput, request).library_id
            )
            coverage = bool(index.find(kind=kind, limit=1, offset=0))
            items = (entity,) if entity is not None and entity.kind == kind else ()
            sources = tuple(
                dict.fromkeys(
                    self._source(ref) for item in items for ref in item.sources
                )
            )
            response = self._envelope(
                "ok" if items else "not_found",
                EntityResults(items=items, has_more=False, coverage_available=coverage),
                sources=sources,
                warnings=()
                if coverage
                else ("no typed entities of this kind were extracted",),
            )
            if _json_bytes(response) > MAX_DOMAIN_RESPONSE_BYTES:
                return self._envelope(
                    "error", warnings=("entity record exceeds the response bound",)
                )
            return response
        except Exception:
            return self._envelope("error", warnings=("entity query failed",))

    def get_symbol(self, request: GetSymbolInput) -> EntityResponse:
        return self._get("symbol", request)

    def get_library(self, request: GetLibraryInput) -> EntityResponse:
        return self._get("library", request)
