from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.services.query_contracts import BrowseTopicsInput
from twincat_knowledge.services.topic_queries import TopicQueryService

HASH = "a" * 64


def _topic(locator: str, title: str, parent: str) -> Topic:
    tid = canonical_topic_id("source", "source-1", "en", locator)
    source = SourceReference(
        source_id="source",
        snapshot_id="source-1",
        topic_id=f"help.{title.lower()}",
        title=title,
        language="en",
        locator=locator,
        content_hash=HASH,
    )
    sid = canonical_section_id(tid, 0)
    return Topic(
        id=tid,
        title=title,
        original_topic_id=f"help.{title.lower()}",
        library="motion",
        language="en",
        source=source,
        metadata=(
            TopicMetadata(name="Microsoft.Help.TocParent", content=parent),
            TopicMetadata(name="Microsoft.Help.TocOrder", content="1"),
        ),
        sections=(
            Section(
                id=sid,
                kind="paragraph",
                text=title,
                source=source.model_copy(update={"section_id": sid}),
            ),
        ),
    )


def _loaded(tmp_path: Path):
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
            documents_total=4,
            documents_imported=4,
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(topics=4, sections=4),
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
