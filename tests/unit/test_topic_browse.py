from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_hierarchy_graph import GraphDiagnosticCode
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.services.query_contracts import BrowseTopicsInput
from twincat_knowledge.services.topic_queries import TopicQueryService

HASH = "a" * 64


def _topic(
    locator: str,
    title: str,
    parent: str | None,
    *,
    library: str = "motion",
    original_topic_id: str | None = None,
) -> Topic:
    original = original_topic_id or f"help.{title.lower()}"
    source = SourceReference(
        source_id="source",
        snapshot_id="source-1",
        topic_id=original,
        title=title,
        language="en",
        locator=locator,
        content_hash=HASH,
    )
    tid = canonical_topic_id("source", "source-1", "en", locator)
    sid = canonical_section_id(tid, 0)
    metadata = (
        ()
        if parent is None
        else (
            TopicMetadata(name="Microsoft.Help.TocParent", content=parent),
            TopicMetadata(name="Microsoft.Help.TocOrder", content="1"),
        )
    )
    return Topic(
        id=tid,
        title=title,
        original_topic_id=original,
        library=library,
        language="en",
        source=source,
        metadata=metadata,
        sections=(
            Section(
                id=sid,
                kind="paragraph",
                text=title,
                source=source.model_copy(update={"section_id": sid}),
            ),
        ),
    )


def _loaded(tmp_path: Path, topics: tuple[Topic, ...] | None = None):
    if topics is None:
        topics = (
            _topic("root", "Root", "-1"),
            _topic("root2", "Root2", "-1"),
            _topic("child", "Child", "help.root"),
            _topic("grand", "Grand", "help.child"),
        )
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id="package-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sources=(
            SourceSnapshot(
                source_id="source",
                snapshot_id="source-1",
                imported_at=datetime(2026, 1, 1, tzinfo=UTC),
                language="en",
                content_hash=HASH,
                rights_reference="fixture",
                parser_version="test",
            ),
        ),
        inventory=InventoryBalance(
            documents_total=len(topics),
            documents_imported=len(topics),
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(topics=len(topics), sections=len(topics)),
    )
    result = build_topic_package(tmp_path / "package", manifest, topics)
    cache = tmp_path / "cache"
    cache.mkdir()
    return load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    )


def test_browse_roots_children_and_breadcrumb(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    service = TopicQueryService(loaded)
    root = service.browse_topics(BrowseTopicsInput(limit=5))
    assert root.status == "ok" and root.data is not None
    assert {item.title for item in root.data.items} == {"Root", "Root2"}
    root_item = next(item for item in root.data.items if item.title == "Root")
    page = service.browse_topics(BrowseTopicsInput(limit=1))
    assert page.next_cursor
    page2 = service.browse_topics(BrowseTopicsInput(limit=1, cursor=page.next_cursor))
    assert page2.status == "ok" and page2.data is not None
    assert [item.title for item in page2.data.items] == ["Root"]
    assert page2.next_cursor is None
    child = service.browse_topics(BrowseTopicsInput(parent_topic_id=root_item.topic_id))
    assert child.status == "ok" and child.data is not None
    assert [item.title for item in child.data.items] == ["Child"]
    assert [crumb.title for crumb in child.data.items[0].breadcrumb] == [
        "Root",
        "Child",
    ]
    loaded.close()


def test_browse_distinguishes_unknown_and_known_empty_parent(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    service = TopicQueryService(loaded)
    unknown = service.browse_topics(BrowseTopicsInput(parent_topic_id="unknown"))
    assert unknown.status == "not_found"
    grand_id = _topic("grand", "Grand", "help.child").id
    empty = service.browse_topics(BrowseTopicsInput(parent_topic_id=grand_id))
    assert empty.status == "ok" and empty.data is not None
    assert empty.data.items == ()
    loaded.close()


def test_browse_revalidates_constructed_inputs(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    result = TopicQueryService(loaded).browse_topics(
        BrowseTopicsInput.model_construct(parent_topic_id=123, limit=True)
    )
    assert result.status == "error"
    loaded.close()


def test_browse_retains_incomplete_root_path_diagnostic(tmp_path: Path) -> None:
    topics = (
        _topic("root", "Root", "-1"),
        _topic("bad", "Bad", "help.missing"),
        _topic("grand", "Grand", "help.bad"),
    )
    loaded = _loaded(tmp_path, topics)
    result = TopicQueryService(loaded).browse_topics(
        BrowseTopicsInput(parent_topic_id=topics[1].id)
    )
    assert result.status == "ok" and result.data is not None
    item = result.data.items[0]
    assert item.hierarchy == "available"
    assert item.breadcrumb_complete is False
    assert item.breadcrumb_truncated is True
    assert item.breadcrumb_diagnostic is GraphDiagnosticCode.UNRESOLVED_PARENT
    assert [crumb.title for crumb in item.breadcrumb] == ["Bad", "Grand"]
    loaded.close()


def test_browse_exposes_complete_explicit_root_and_final_ascii_budget(
    tmp_path: Path,
) -> None:
    loaded = _loaded(tmp_path)
    result = TopicQueryService(loaded).browse_topics(BrowseTopicsInput())
    assert result.status == "ok" and result.data is not None
    assert result.actual_ascii_bytes <= result.ascii_byte_budget
    assert result.actual_ascii_bytes == len(result.model_dump_json().encode("ascii"))
    assert all(
        item.breadcrumb_complete
        and not item.breadcrumb_truncated
        and item.breadcrumb_diagnostic is None
        for item in result.data.items
    )
    loaded.close()


def test_browse_marks_missing_hierarchy_unavailable(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path, (_topic("orphan", "Orphan", None),))
    result = TopicQueryService(loaded).browse_topics(BrowseTopicsInput())
    assert result.status == "not_available"
    assert result.data is None
    loaded.close()


def test_browse_does_not_infer_ambiguous_parent_edges(tmp_path: Path) -> None:
    parent_one = _topic("parent-one", "Parent", "-1")
    parent_two = _topic("parent-two", "Parent", "-1")
    ambiguous_child = _topic("child", "Child", "help.parent")
    loaded = _loaded(tmp_path, (parent_one, parent_two, ambiguous_child))
    service = TopicQueryService(loaded)

    roots = service.browse_topics(BrowseTopicsInput(limit=5))
    assert roots.status == "ok" and roots.data is not None
    assert {item.topic_id for item in roots.data.items} == {
        parent_one.id,
        parent_two.id,
    }
    for parent in (parent_one, parent_two):
        children = service.browse_topics(
            BrowseTopicsInput(parent_topic_id=parent.id, limit=5)
        )
        assert children.status == "ok" and children.data is not None
        assert children.data.items == ()
    loaded.close()


def test_browse_filter_and_cursor_bindings_are_strict(tmp_path: Path) -> None:
    root = _topic("root", "Root", "-1", library="motion")
    second_root = _topic("second-root", "Second root", "-1", library="motion")
    child = _topic("child", "Child", "help.root", library="io")
    loaded = _loaded(tmp_path, (root, second_root, child))
    service = TopicQueryService(loaded)

    filtered = service.browse_topics(
        BrowseTopicsInput(
            parent_topic_id=root.id,
            filters={"language": "any", "library_id": "io"},
        )
    )
    assert filtered.status == "ok" and filtered.data is not None
    assert [item.topic_id for item in filtered.data.items] == [child.id]

    first = service.browse_topics(BrowseTopicsInput(limit=1))
    assert first.status == "ok" and first.next_cursor
    assert (
        service.browse_topics(BrowseTopicsInput(cursor="malformed")).status == "error"
    )
    assert (
        service.browse_topics(
            BrowseTopicsInput(limit=2, cursor=first.next_cursor)
        ).status
        == "error"
    )
    assert (
        service.browse_topics(
            BrowseTopicsInput(parent_topic_id=root.id, cursor=first.next_cursor)
        ).status
        == "error"
    )
    assert (
        service.browse_topics(
            BrowseTopicsInput(filters={"language": "de"}, cursor=first.next_cursor)
        ).status
        == "error"
    )
    assert (
        TopicQueryService(loaded)
        .browse_topics(BrowseTopicsInput(limit=1, cursor=first.next_cursor))
        .status
        == "error"
    )
    loaded.close()


def test_browse_unicode_pages_have_no_loss_and_final_bound(tmp_path: Path) -> None:
    topics = tuple(
        _topic(
            f"long/{index}.html",
            f"{index:02d}-" + "☃" * 250,
            "-1",
            original_topic_id=f"help.long-{index}",
        )
        for index in range(12)
    )
    loaded = _loaded(tmp_path, topics)
    service = TopicQueryService(loaded)
    seen: list[str] = []
    page_count = 0
    response = service.browse_topics(BrowseTopicsInput(limit=20))
    while True:
        page_count += 1
        assert response.actual_ascii_bytes <= response.ascii_byte_budget
        assert response.data is not None
        seen.extend(item.topic_id for item in response.data.items)
        assert response.data.has_more == (response.next_cursor is not None)
        if response.next_cursor is None:
            break
        response = service.browse_topics(
            BrowseTopicsInput(limit=20, cursor=response.next_cursor)
        )
    assert page_count > 1
    assert seen == sorted(topic.id for topic in topics)
    assert len(seen) == len(set(seen)) == len(topics)
    assert response.status == "ok"
    loaded.close()


def test_browse_rejects_one_oversized_record_without_cursor(tmp_path: Path) -> None:
    huge = _topic(
        "huge.html",
        "☃" * 4096,
        "-1",
        original_topic_id="help.huge",
    )
    loaded = _loaded(tmp_path, (huge,))
    result = TopicQueryService(loaded).browse_topics(BrowseTopicsInput())
    assert result.status == "error"
    assert result.data is None
    assert result.next_cursor is None
    assert result.warnings == ("browse record exceeds the response bound",)
    loaded.close()
