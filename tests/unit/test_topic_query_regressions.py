"""Regression tests for bounded topic query service review findings."""

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
    QueryFilters,
    ResponseEnvelope,
    SearchInput,
)
from twincat_knowledge.services.topic_queries import (
    MAX_DOMAIN_RESPONSE_BYTES,
    TopicQueryService,
    _json_bytes,
)

HASH = "a" * 64


def _source(snapshot: str, *, source_id: str = "synthetic") -> SourceSnapshot:
    return SourceSnapshot(
        source_id=source_id,
        snapshot_id=snapshot,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language="en",
        content_hash=HASH,
        rights_reference="operator-approved-fixture",
        parser_version="reader-1",
    )


def _topic(
    number: int,
    *,
    title_len: int = 30,
    locator_len: int = 40,
    url_len: int = 40,
    sections: int = 1,
    snapshot: str | None = None,
    source_id: str = "synthetic",
) -> Topic:
    snapshot = snapshot or f"source-{number}"
    locator = "docs/" + ("x" * max(1, locator_len - 5))
    title = "Needle " + ("T" * max(1, title_len - 7))
    topic_id = canonical_topic_id(source_id, snapshot, "en", locator)
    reference = SourceReference(
        source_id=source_id,
        snapshot_id=snapshot,
        topic_id=f"help.topic-{number}",
        title=title,
        language="en",
        canonical_url="https://example.com/" + ("u" * max(1, url_len - 20)),
        locator=locator,
        content_hash=HASH,
    )
    section_list = tuple(
        Section(
            id=canonical_section_id(topic_id, index),
            kind="paragraph",
            text=f"body-{number}-{index}",
            source=reference.model_copy(
                update={"section_id": canonical_section_id(topic_id, index)}
            ),
        )
        for index in range(sections)
    )
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id=f"help.topic-{number}",
        library="motion",
        language="en",
        source=reference,
        sections=section_list,
    )


def _manifest(
    topics: tuple[Topic, ...], package_snapshot: str = "package-1"
) -> CorpusManifest:
    snapshots: list[SourceSnapshot] = []
    seen: set[tuple[str, str, str]] = set()
    for item in topics:
        key = (item.source.source_id, item.source.snapshot_id, item.language)
        if key not in seen:
            seen.add(key)
            snapshots.append(
                _source(item.source.snapshot_id, source_id=item.source.source_id)
            )
    if not snapshots:
        snapshots.append(_source("source-empty"))
    return CorpusManifest(
        package_schema_version="1.0",
        snapshot_id=package_snapshot,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        sources=tuple(snapshots),
        inventory=InventoryBalance(
            documents_total=len(topics),
            documents_imported=len(topics),
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(
            topics=len(topics), sections=sum(len(item.sections) for item in topics)
        ),
    )


def _service(
    root: Path,
    topics: tuple[Topic, ...],
    package_snapshot: str = "package-1",
) -> tuple[TopicQueryService, object]:
    result = build_topic_package(
        root / "package", _manifest(topics, package_snapshot), topics
    )
    cache = root / "cache"
    cache.mkdir()
    loaded = load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )
    return TopicQueryService(loaded), loaded


def _assert_bounded_error(response: ResponseEnvelope[object]) -> None:
    assert response.status == "error"
    assert _json_bytes(response) <= MAX_DOMAIN_RESPONSE_BYTES
    text = str(response)
    assert "Traceback" not in text
    assert "/" not in text
    assert "object at 0x" not in text


@pytest.mark.parametrize("loaded", [False, True])
def test_all_public_apis_revalidate_bypassed_models_before_corpus_logic(
    tmp_path: Path, loaded: bool
) -> None:
    service: TopicQueryService
    handle: object | None = None
    if loaded:
        service, handle = _service(tmp_path, (_topic(1),))
        topic_id = _topic(1).id
    else:
        service = TopicQueryService(None)
        topic_id = "valid-topic-id"

    invalid_requests = (
        (service.search, SearchInput(query="Needle").model_copy(update={"limit": 0})),
        (
            service.search,
            SearchInput(query="Needle").model_copy(update={"limit": True}),
        ),
        (service.search, SearchInput(query="Needle").model_copy(update={"limit": 21})),
        (
            service.search,
            SearchInput(query="Needle").model_copy(update={"query": None}),
        ),
        (
            service.search,
            SearchInput(query="Needle").model_copy(
                update={
                    "filters": QueryFilters(language="en").model_copy(
                        update={"language": "fr"}
                    )
                }
            ),
        ),
        (
            service.search,
            SearchInput(query="Needle").model_copy(update={"unexpected": "x"}),
        ),
        (service.search, SearchInput.model_construct(query="Needle", limit=0)),
        (service.search, SearchInput.model_construct(query="Needle", limit=True)),
        (service.search, SearchInput.model_construct(query="Needle", limit=21)),
        (service.search, SearchInput.model_construct(query=123, limit=5)),
        (
            service.search,
            SearchInput.model_construct(
                query="Needle",
                filters=QueryFilters.model_construct(language="fr"),
            ),
        ),
        (service.get_topic, GetTopicInput.model_construct(topic_id=topic_id, limit=0)),
        (
            service.get_topic,
            GetTopicInput.model_construct(topic_id=topic_id, limit=True),
        ),
        (service.get_topic, GetTopicInput.model_construct(topic_id=topic_id, limit=21)),
        (
            service.get_topic,
            GetTopicInput(topic_id=topic_id).model_copy(update={"unexpected": "x"}),
        ),
        (
            service.get_corpus_status,
            CorpusStatusInput.model_construct(snapshot_id=None, limit=0),
        ),
        (
            service.get_corpus_status,
            CorpusStatusInput.model_construct(snapshot_id=None, limit=True),
        ),
        (
            service.get_corpus_status,
            CorpusStatusInput.model_construct(snapshot_id=None, limit=21),
        ),
        (
            service.get_corpus_status,
            CorpusStatusInput(snapshot_id=None).model_copy(update={"unexpected": "x"}),
        ),
    )
    for method, request in invalid_requests:
        _assert_bounded_error(method(request))
    if handle is not None:
        handle.close()


def test_valid_strict_models_and_package_only_snapshot_filter(tmp_path: Path) -> None:
    topics = (_topic(1, snapshot="source-a"), _topic(2, snapshot="source-b"))
    service, loaded = _service(tmp_path, topics)
    package = service.search(
        SearchInput(query="Needle", filters=QueryFilters(snapshot_id="package-1"))
    )
    source = service.search(
        SearchInput(query="Needle", filters=QueryFilters(snapshot_id="source-a"))
    )
    assert package.status == "ok" and package.data is not None
    assert len(package.data.items) == 2
    assert source.status == "not_found"
    assert QueryFilters(snapshot_id="package-1").snapshot_id == "package-1"
    loaded.close()


def test_search_fits_actual_cursor_and_reuses_it(tmp_path: Path) -> None:
    topics = tuple(
        _topic(
            index,
            title_len=2000,
            locator_len=1000,
            url_len=1000,
        )
        for index in range(3)
    )
    service, loaded = _service(tmp_path, topics)
    first = service.search(SearchInput(query="Needle", limit=2))
    assert first.status == "ok" and first.data is not None
    assert len(first.data.items) == 1 and first.next_cursor
    assert _json_bytes(first) <= MAX_DOMAIN_RESPONSE_BYTES
    ids: list[str] = []
    page = first
    while True:
        assert page.data is not None
        ids.extend(item.id for item in page.data.items)
        assert _json_bytes(page) <= MAX_DOMAIN_RESPONSE_BYTES
        if page.next_cursor is None:
            assert page.data.has_more is False
            break
        page = service.search(
            SearchInput(query="Needle", limit=2, cursor=page.next_cursor)
        )
        assert page.status == "ok"
    assert len(ids) == len(set(ids)) == 3
    loaded.close()


def test_get_fits_actual_cursor_and_reuses_it(tmp_path: Path) -> None:
    topic = _topic(3, title_len=1100, locator_len=825, url_len=825, sections=3)
    service, loaded = _service(tmp_path, (topic,))
    first = service.get_topic(GetTopicInput(topic_id=topic.id, limit=2))
    assert first.status == "ok" and first.data is not None
    assert len(first.data.sections) == 1 and first.next_cursor
    assert _json_bytes(first) <= MAX_DOMAIN_RESPONSE_BYTES
    ids: list[str] = []
    page = first
    while True:
        assert page.data is not None
        ids.extend(section.id for section in page.data.sections)
        assert _json_bytes(page) <= MAX_DOMAIN_RESPONSE_BYTES
        if page.next_cursor is None:
            assert page.data.complete is True
            break
        page = service.get_topic(
            GetTopicInput(topic_id=topic.id, limit=2, cursor=page.next_cursor)
        )
        assert page.status == "ok"
    assert len(ids) == len(set(ids)) == 3
    loaded.close()


def test_status_shrinks_source_page_without_loss_or_duplicates(tmp_path: Path) -> None:
    topics = tuple(
        _topic(
            100 + index,
            snapshot=(f"s{index:03d}" + ("z" * 252))[:256],
            source_id=(f"source-{index:03d}" + ("q" * 188))[:200],
        )
        for index in range(20)
    )
    service, loaded = _service(tmp_path, topics)
    request = CorpusStatusInput(limit=20)
    pages = []
    cursor: str | None = None
    while True:
        page = service.get_corpus_status(request.model_copy(update={"cursor": cursor}))
        assert page.status == "ok" and page.data is not None
        assert _json_bytes(page) <= MAX_DOMAIN_RESPONSE_BYTES
        pages.append(page)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    ids = [source.source_id for page in pages for source in page.data.sources]
    assert len(ids) == len(set(ids)) == 20
    assert pages[0].data.source_count == 20
    assert pages[-1].data.sources
    loaded.close()


def test_contract_constructors_remain_strict() -> None:
    with pytest.raises(ValidationError):
        SearchInput(query="x", limit=True)
    with pytest.raises(ValidationError):
        SearchInput(query="x", unexpected="nope")
    with pytest.raises(ValidationError):
        QueryFilters(language="fr")
