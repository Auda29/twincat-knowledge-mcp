"""Vertical TDD coverage for the bounded topic query service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic
from twincat_knowledge.services.query_contracts import (
    CorpusStatusInput,
    GetTopicInput,
    SearchInput,
)
from twincat_knowledge.services.topic_queries import TopicQueryService

SOURCE_HASH = "b" * 64
CONTENT_HASH = "a" * 64


def _source(language: str = "en", snapshot_id: str = "source-1") -> SourceSnapshot:
    return SourceSnapshot(
        source_id="synthetic",
        snapshot_id=snapshot_id,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language=language,
        content_hash=SOURCE_HASH,
        rights_reference="operator-approved-fixture",
        parser_version="reader-1",
    )


def _topic(
    locator: str,
    title: str,
    *,
    language: str = "en",
    snapshot_id: str = "source-1",
    sections: tuple[Section, ...] | None = None,
) -> Topic:
    topic_id = canonical_topic_id("synthetic", snapshot_id, language, locator)
    source = SourceReference(
        source_id="synthetic",
        snapshot_id=snapshot_id,
        topic_id=f"help.{title.lower()}",
        title=title,
        language=language,
        locator=locator,
        content_hash=CONTENT_HASH,
    )
    if sections is None:
        sid = canonical_section_id(topic_id, 0)
        sections = (
            Section(
                id=sid,
                kind="paragraph",
                text=f"Documentation for {title}.",
                source=source.model_copy(update={"section_id": sid}),
            ),
        )
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id=f"help.{title.lower()}",
        library="motion",
        language=language,
        source=source,
        sections=sections,
    )


def _manifest(topics: tuple[Topic, ...]) -> CorpusManifest:
    seen: set[tuple[str, str]] = set()
    source_list: list[SourceSnapshot] = []
    for topic in topics:
        key = (topic.language, topic.source.snapshot_id)
        if key not in seen:
            seen.add(key)
            source_list.append(_source(*key))
    sources = tuple(source_list) or (_source(),)
    return CorpusManifest(
        package_schema_version="1.0",
        snapshot_id="package-1",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        sources=sources,
        inventory=InventoryBalance(
            documents_total=len(topics),
            documents_imported=len(topics),
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(
            topics=len(topics), sections=sum(len(topic.sections) for topic in topics)
        ),
    )


@pytest.fixture
def service(tmp_path: Path) -> tuple[TopicQueryService, object]:
    topics = (
        _topic("motion/en/alpha.html", "Alpha"),
        _topic("motion/en/beta.html", "Beta"),
        _topic("motion/de/gamma.html", "Gamma", language="de", snapshot_id="source-de"),
    )
    result = build_topic_package(tmp_path / "package", _manifest(topics), topics)
    cache = tmp_path / "cache"
    cache.mkdir()
    loaded = load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )
    return TopicQueryService(loaded), loaded


def test_missing_loaded_is_not_available() -> None:
    result = TopicQueryService(None).search(SearchInput(query="anything"))
    assert result.status == "not_available"
    assert result.data is None
    assert result.snapshot_ids == ()


def test_empty_loaded_corpus_is_available_but_has_no_topics(tmp_path: Path) -> None:
    result = build_topic_package(tmp_path / "empty-package", _manifest(()), ())
    cache = tmp_path / "empty-cache"
    cache.mkdir()
    loaded = load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )
    service = TopicQueryService(loaded)
    search = service.search(SearchInput(query="missing"))
    missing = service.get_topic(GetTopicInput(topic_id="missing-topic"))
    assert search.status == "not_found"
    assert search.data is not None and search.data.items == ()
    assert missing.status == "not_found"
    loaded.close()


def test_search_is_real_indexed_and_provenanced(service) -> None:
    query, loaded = service
    result = query.search(SearchInput(query="Alpha"))
    assert result.status == "ok"
    assert result.data is not None
    assert [item.title for item in result.data.items] == ["Alpha"]
    assert result.data.items[0].kind == "topics"
    assert result.data.items[0].source.snapshot_id == "source-1"
    assert result.sources[0].locator == "motion/en/alpha.html"
    assert result.sources[0].applicability == "unknown"
    loaded.close()


def test_search_pagination_has_lookahead_without_duplicates(service) -> None:
    query, loaded = service
    first = query.search(SearchInput(query="Documentation", limit=2))
    assert first.data is not None and first.data.has_more
    assert first.next_cursor
    second = query.search(
        SearchInput(query="Documentation", limit=2, cursor=first.next_cursor)
    )
    assert second.data is not None
    assert second.data.has_more is False
    assert set(i.id for i in first.data.items).isdisjoint(
        i.id for i in second.data.items
    )
    assert first.truncated and not second.truncated
    loaded.close()


def test_search_limit_twenty_uses_lookahead_page(tmp_path: Path) -> None:
    topics = tuple(
        _topic(f"motion/en/topic-{number}.html", f"Topic {number}")
        for number in range(21)
    )
    result = build_topic_package(tmp_path / "many-package", _manifest(topics), topics)
    cache = tmp_path / "many-cache"
    cache.mkdir()
    loaded = load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )
    service = TopicQueryService(loaded)
    first = service.search(SearchInput(query="Documentation", limit=20))
    assert first.status == "ok" and first.data is not None
    assert len(first.data.items) == 20
    assert first.data.has_more and first.next_cursor
    second = service.search(
        SearchInput(query="Documentation", limit=20, cursor=first.next_cursor)
    )
    assert second.status == "ok" and second.data is not None
    assert len(second.data.items) == 1
    assert not second.data.has_more and second.next_cursor is None
    assert set(item.id for item in first.data.items).isdisjoint(
        item.id for item in second.data.items
    )
    loaded.close()


def test_get_topic_preserves_section_order_selection_and_code(
    service, tmp_path: Path
) -> None:
    _, loaded = service
    topic = loaded.index.get_topic(
        canonical_topic_id("synthetic", "source-1", "en", "motion/en/alpha.html")
    )
    assert topic is not None
    locator = "motion/en/ordered.html"
    ordered_id = canonical_topic_id("synthetic", "source-1", "en", locator)
    source = SourceReference(
        source_id="synthetic",
        snapshot_id="source-1",
        topic_id="help.ordered",
        title="Ordered",
        language="en",
        locator=locator,
        content_hash=CONTENT_HASH,
    )
    sections = tuple(
        Section(
            id=canonical_section_id(ordered_id, index),
            kind=kind,
            text=text if kind in {"paragraph", "warning"} else None,
            code=code if kind == "code" else None,
            rows=rows,
            source=source.model_copy(
                update={"section_id": canonical_section_id(ordered_id, index)}
            ),
        )
        for index, (kind, text, code, rows) in enumerate(
            (
                ("paragraph", "first", None, ()),
                ("code", None, "IF x THEN\n y := '☃';\nEND_IF;", ()),
                ("table", None, None, (("A", "B"),)),
                ("warning", "last warning", None, ()),
            )
        )
    )
    replacement = Topic(
        id=ordered_id,
        title="Ordered",
        original_topic_id="help.ordered",
        library="motion",
        language="en",
        source=source,
        sections=sections,
    )
    result = build_topic_package(
        tmp_path / "ordered-package", _manifest((replacement,)), (replacement,)
    )
    cache = tmp_path / "ordered-cache"
    cache.mkdir()
    ordered_loaded = load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )
    ordered_query = TopicQueryService(ordered_loaded)
    response = ordered_query.get_topic(
        GetTopicInput(
            topic_id=replacement.id, section_ids=(sections[3].id, sections[1].id)
        )
    )
    assert response.status == "ok"
    assert response.data is not None
    assert [section.kind for section in response.data.sections] == ["code", "warning"]
    unknown = ordered_query.get_topic(
        GetTopicInput(topic_id=replacement.id, section_ids=("unknown-section",))
    )
    assert unknown.status == "error"
    first = ordered_query.get_topic(GetTopicInput(topic_id=replacement.id, limit=1))
    assert first.next_cursor
    second = ordered_query.get_topic(
        GetTopicInput(topic_id=replacement.id, limit=1, cursor=first.next_cursor)
    )
    assert second.status == "ok"
    assert second.data is not None
    assert second.data.sections[0].kind == "code"
    assert second.data.sections[0].code == "IF x THEN\n y := '☃';\nEND_IF;"
    assert first.truncated and second.truncated
    ordered_loaded.close()
    loaded.close()


def test_status_reports_only_implemented_topic_counts(service) -> None:
    query, loaded = service
    result = query.get_corpus_status(CorpusStatusInput(detail="coverage", limit=1))
    assert result.status == "ok"
    assert result.data is not None
    assert result.data.topic_count == 3
    assert result.data.section_count == 3
    assert [(item.language, item.count) for item in result.data.language_counts] == [
        ("de", 1),
        ("en", 2),
    ]
    assert result.data.implemented_categories == ("topics",)
    assert result.data.count_fields == ("topics", "sections", "languages")
    assert result.data.inventory.documents_imported == 3
    assert len(result.data.sources) == 1
    assert result.next_cursor
    loaded.close()


def test_cursor_is_authenticated_and_bound(service) -> None:
    query, loaded = service
    first = query.search(SearchInput(query="Documentation", limit=1))
    assert first.next_cursor
    tampered = first.next_cursor[:-1] + ("A" if first.next_cursor[-1] != "A" else "B")
    assert (
        query.search(
            SearchInput(query="Documentation", limit=1, cursor=tampered)
        ).status
        == "error"
    )
    assert (
        query.search(
            SearchInput(query="Alpha", limit=1, cursor=first.next_cursor)
        ).status
        == "error"
    )
    assert (
        TopicQueryService(loaded)
        .search(SearchInput(query="Documentation", limit=1, cursor=first.next_cursor))
        .status
        == "error"
    )
    loaded.close()


def test_unsupported_filters_and_categories_are_explicit(service) -> None:
    query, loaded = service
    assert (
        query.search(
            SearchInput(query="Alpha", filters={"library_id": "motion"})
        ).status
        == "error"
    )
    assert (
        query.search(SearchInput(query="Alpha", kinds=("symbols",))).status
        == "not_available"
    )
    assert query.search(SearchInput(query="Alpha", kinds=())).status == "not_available"
    loaded.close()


def test_contract_is_strict_and_unicode_boundary_is_character_based(service) -> None:
    query, loaded = service
    assert query.search(SearchInput(query="☃" * 512)).status == "not_found"
    with pytest.raises(ValidationError):
        SearchInput(query="☃" * 513)
    with pytest.raises(ValidationError):
        SearchInput(query="x", limit=True)
    with pytest.raises(ValidationError):
        SearchInput(query="x", unexpected="nope")
    loaded.close()


def test_closed_handle_is_controlled_error(service) -> None:
    query, loaded = service
    loaded.close()
    result = query.search(SearchInput(query="Alpha"))
    assert result.status == "error"
    assert "cache" not in str(result)
    assert "secret" not in str(result)


def test_oversized_section_is_explicit_error(tmp_path: Path) -> None:
    topic = _topic("motion/en/huge.html", "Huge")
    huge_source = topic.source
    sid = canonical_section_id(topic.id, 0)
    huge = _topic(
        "motion/en/huge.html",
        "Huge",
        sections=(
            Section(
                id=sid,
                kind="code",
                code="x := '" + ("☃" * 10_000) + "';",
                source=huge_source.model_copy(update={"section_id": sid}),
            ),
        ),
    )
    result = build_topic_package(tmp_path / "package", _manifest((huge,)), (huge,))
    cache = tmp_path / "cache"
    cache.mkdir()
    loaded = load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )
    response = TopicQueryService(loaded).get_topic(GetTopicInput(topic_id=huge.id))
    assert response.status == "error"
    assert any("oversized" in warning.lower() for warning in response.warnings)
    loaded.close()
