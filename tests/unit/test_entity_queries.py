"""Tests for typed query disambiguation and bounded cursors."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from twincat_knowledge.domain.entities import TypedEntity
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.services.entity_contracts import (
    EntityFilters,
    FindEntitiesInput,
    GetSymbolInput,
    LookupErrorInput,
)
from twincat_knowledge.services.entity_queries import EntityQueryService


def _service(monkeypatch):
    ref = SourceReference(
        source_id="synthetic",
        snapshot_id="source",
        topic_id="topic",
        title="Fixture",
        language="en",
        locator="fixture.html",
        content_hash="a" * 64,
    )

    def entity(id, kind, name, **kwargs):
        return TypedEntity(
            id=id,
            kind=kind,
            name=name,
            topic_id="topic",
            sources=(ref,),
            missing_fields=(),
            warnings=(),
            **kwargs,
        )

    items = (
        entity(
            "s1",
            "symbol",
            "Run",
            namespace="A",
            library="One",
            declaration="FUNCTION Run : BOOL",
        ),
        entity(
            "s2",
            "symbol",
            "Run",
            namespace="B",
            library="Two",
            declaration="FUNCTION Run : BOOL",
        ),
        entity("e1", "error", "Fault A", error_code="0x10", error_domain="A"),
        entity("e2", "error", "Fault B", error_code="0x10", error_domain="B"),
        entity("e3", "error", "Fault C", error_code="16", error_domain="A"),
    )
    snapshot = SimpleNamespace(
        source_id="synthetic",
        snapshot_id="source",
        language="en",
        documented_version=None,
        applicability="unknown",
    )
    loaded = SimpleNamespace(
        manifest=SimpleNamespace(
            corpus_manifest=SimpleNamespace(snapshot_id="package", sources=(snapshot,)),
            model_dump=lambda **kwargs: {"snapshot_id": "package"},
        )
    )

    def find(*, kind, limit, offset, **filters):
        def matches(item):
            for key, expected in filters.items():
                value = getattr(item, key)
                if value is None or (
                    value != expected
                    if key in ("error_code", "documented_version")
                    else value.casefold() != expected.casefold()
                ):
                    return False
            return item.kind == kind

        return tuple(item for item in items if matches(item))[offset : offset + limit]

    index = SimpleNamespace(
        entities=items,
        get=lambda id: next((item for item in items if item.id == id), None),
        find=find,
    )
    service = EntityQueryService(loaded)
    monkeypatch.setattr(service, "_get_index", lambda: index)
    return service


def test_disambiguation_exact_ids_and_provenance(monkeypatch):
    service = _service(monkeypatch)
    first = service.find_symbols(FindEntitiesInput(query="run", limit=1))
    assert first.status == "ambiguous" and first.next_cursor
    assert (
        first.snapshot_ids == ("package",)
        and first.sources[0].locator == "fixture.html"
    )
    second = service.find_symbols(
        FindEntitiesInput(query="run", limit=1, cursor=first.next_cursor)
    )
    assert second.data.items[0].id != first.data.items[0].id
    tampered = first.next_cursor[:-1] + ("A" if first.next_cursor[-1] != "A" else "B")
    assert (
        service.find_symbols(
            FindEntitiesInput(query="run", limit=1, cursor=tampered)
        ).status
        == "error"
    )
    assert (
        _service(monkeypatch)
        .find_symbols(FindEntitiesInput(query="run", limit=1, cursor=first.next_cursor))
        .status
        == "error"
    )
    assert (
        service.find_symbols(
            FindEntitiesInput(query="run", filters=EntityFilters(namespace="A"))
        )
        .data.items[0]
        .id
        == "s1"
    )
    assert (
        service.find_symbols(
            FindEntitiesInput(
                query="run", filters=EntityFilters(documented_version="unknown")
            )
        ).status
        == "not_found"
    )
    assert (
        service.get_symbol(GetSymbolInput(symbol_id="s1")).data.items[0].declaration
        == "FUNCTION Run : BOOL"
    )
    assert service.get_symbol(GetSymbolInput(symbol_id="run")).status == "not_found"
    service._loaded.manifest.model_dump = lambda **kwargs: {"snapshot_id": "changed"}
    assert (
        service.find_symbols(
            FindEntitiesInput(query="run", limit=1, cursor=first.next_cursor)
        ).status
        == "error"
    )
    assert (
        service.find_symbols(
            FindEntitiesInput(query="other", limit=1, cursor=first.next_cursor)
        ).status
        == "error"
    )


def test_error_code_is_opaque_and_domain_disambiguates(monkeypatch):
    service = _service(monkeypatch)
    assert service.lookup_error(LookupErrorInput(code="0x10")).status == "ambiguous"
    result = service.lookup_error(LookupErrorInput(code="0x10", domain="A"))
    assert [e.id for e in result.data.items] == ["e1"]
    assert [
        e.id for e in service.lookup_error(LookupErrorInput(code="16")).data.items
    ] == ["e3"]
    assert service.lookup_error(LookupErrorInput(code="0X10")).status == "not_found"
    empty = service.find_libraries(FindEntitiesInput(query="missing"))
    assert empty.status == "not_found" and not empty.data.coverage_available
    assert empty.warnings


def test_strict_request_validation_and_absent_package(monkeypatch):
    with pytest.raises(ValidationError):
        FindEntitiesInput(query="x", limit=True)
    with pytest.raises(ValidationError):
        LookupErrorInput(code=16)
    with pytest.raises(ValidationError):
        LookupErrorInput(code="0xGG")
    assert (
        EntityQueryService(None).find_symbols(FindEntitiesInput(query="x")).status
        == "not_available"
    )
    assert (
        _service(monkeypatch)
        .find_symbols(FindEntitiesInput.model_construct(query="x", limit=True))
        .status
        == "error"
    )


def test_real_loaded_package_extracts_lazily_and_closes(tmp_path):
    from test_topic_queries import _manifest, _topic

    from twincat_knowledge.corpus.topic_package import build_topic_package
    from twincat_knowledge.corpus.topic_package_load import load_topic_package
    from twincat_knowledge.domain.identity import canonical_section_id
    from twincat_knowledge.domain.topics import Section
    from twincat_knowledge.services.topic_queries import TopicQueryService

    base = _topic("motion/en/run.html", "Run")
    sid = canonical_section_id(base.id, 0)
    code = "FUNCTION Run : BOOL\nRun := TRUE;\nEND_FUNCTION"
    topic = base.model_copy(
        update={
            "sections": (
                Section(
                    id=sid,
                    kind="code",
                    code=code,
                    language="ST",
                    source=base.source.model_copy(update={"section_id": sid}),
                ),
            )
        }
    )
    package = build_topic_package(tmp_path / "package", _manifest((topic,)), (topic,))
    cache = tmp_path / "cache"
    cache.mkdir()
    loaded = load_topic_package(
        package.path, expected_manifest_sha256=package.manifest_sha256, cache_dir=cache
    )
    service = TopicQueryService(loaded).entity_service
    assert service._index is None
    response = service.find_symbols(FindEntitiesInput(query="Run"))
    assert response.status == "ok"
    assert response.data.items[0].declaration == code
    assert response.sources[0].section_id == sid
    loaded.close()
    assert service.find_symbols(FindEntitiesInput(query="Run")).status == "error"


def test_oversized_entity_is_controlled_error(monkeypatch):
    service = _service(monkeypatch)
    original_index = service._get_index()
    huge = original_index.entities[0].model_copy(update={"declaration": "x" * 20000})
    original_index.get = lambda entity_id: huge
    result = service.get_symbol(GetSymbolInput(symbol_id=huge.id))
    assert result.status == "error"
    assert "exceeds" in result.warnings[0]
