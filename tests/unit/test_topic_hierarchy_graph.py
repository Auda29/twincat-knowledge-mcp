"""Vertical TDD tests for the pure bounded topic hierarchy graph."""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar

import pytest
from pydantic import ValidationError

from twincat_knowledge.corpus.topic_hierarchy_graph import (
    GraphDiagnosticCode,
    TopicHierarchyGraphBoundsError,
    TopicHierarchyGraphCycleError,
    TopicHierarchyGraphDuplicateCanonicalIDError,
    TopicHierarchyGraphScopeError,
    TopicHierarchyGraphValidationError,
    build_topic_hierarchy_graph,
)
from twincat_knowledge.domain.identity import canonical_topic_id
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Topic, TopicMetadata

HASH = "a" * 64


def _topic(
    name: str,
    *,
    parent: str | None = "-1",
    order: str | None = "1",
    source_id: str = "source",
    snapshot: str = "snapshot",
    language: str = "en",
    library: str = "library",
    original: str | None = None,
    missing_original: bool = False,
    locator: str | None = None,
) -> Topic:
    if not missing_original:
        original = original if original is not None else f"help.{name}"
    locator = locator or f"{library}/{language}/{name}.html"
    topic_id = canonical_topic_id(source_id, snapshot, language, locator)
    metadata: list[TopicMetadata] = []
    if parent is not None:
        metadata.append(TopicMetadata(name="Microsoft.Help.TocParent", content=parent))
    if order is not None:
        metadata.append(TopicMetadata(name="Microsoft.Help.TocOrder", content=order))
    source = SourceReference(
        source_id=source_id,
        snapshot_id=snapshot,
        topic_id=original,
        title=name,
        language=language,
        canonical_url=None,
        locator=locator,
        content_hash=HASH,
    )
    return Topic(
        id=topic_id,
        title=name,
        original_topic_id=original,
        library=library,
        language=language,
        source=source,
        metadata=tuple(metadata),
    )


def test_roots_children_grandchild_and_breadcrumb_are_explicit() -> None:
    root = _topic("root", order="2")
    child = _topic("child", parent="help.root", order="1", library="other")
    grandchild = _topic("grandchild", parent="help.child", order="1")

    graph = build_topic_hierarchy_graph((grandchild, root, child))

    assert graph.has_hierarchy is True
    assert tuple(node.canonical_id for node in graph.roots()) == (root.id,)
    assert tuple(node.canonical_id for node in graph.direct_children(root.id)) == (
        child.id,
    )
    assert tuple(node.canonical_id for node in graph.direct_children(child.id)) == (
        grandchild.id,
    )
    edge = next(item for item in graph.edges() if item.child_canonical_id == child.id)
    assert edge.parent_original_topic_id == "help.root"
    assert edge.source == child.source
    breadcrumb = graph.breadcrumb(grandchild.id)
    assert tuple(node.canonical_id for node in breadcrumb.items) == (
        root.id,
        child.id,
        grandchild.id,
    )
    assert breadcrumb.diagnostic is None
    assert graph.get_node(root.id).topic == root


def test_unknown_hierarchy_is_not_an_empty_successful_root_set() -> None:
    graph = build_topic_hierarchy_graph((_topic("unknown", parent=None),))

    assert graph.has_hierarchy is False
    assert graph.roots() == ()
    assert graph.diagnostics()[0].code is GraphDiagnosticCode.HIERARCHY_UNKNOWN


def test_explicit_hierarchy_with_no_resolved_root_is_distinct() -> None:
    graph = build_topic_hierarchy_graph((_topic("orphan", parent="missing"),))

    assert graph.has_hierarchy is True
    assert graph.roots() == ()
    assert graph.diagnostics()[0].code is GraphDiagnosticCode.UNRESOLVED_PARENT
    breadcrumb = graph.breadcrumb(
        graph.get_node(_topic("orphan", parent="missing").id).canonical_id
    )
    assert breadcrumb.diagnostic is GraphDiagnosticCode.UNRESOLVED_PARENT


def test_missing_parent_original_id_is_not_an_inferred_candidate() -> None:
    missing_original = _topic("not-a-parent", parent="-1", missing_original=True)
    child = _topic("child", parent="help.not-a-parent")

    graph = build_topic_hierarchy_graph((missing_original, child))

    assert graph.direct_children(missing_original.id) == ()
    assert graph.diagnostics(child.id)[0].code is GraphDiagnosticCode.UNRESOLVED_PARENT


def test_topic_with_unknown_hierarchy_can_be_an_exact_parent_only() -> None:
    parent = _topic("parent", parent=None)
    child = _topic("child", parent="help.parent")

    graph = build_topic_hierarchy_graph((parent, child))

    assert graph.direct_children(parent.id)[0].canonical_id == child.id
    breadcrumb = graph.breadcrumb(child.id)
    assert breadcrumb is not None
    assert breadcrumb.diagnostic is GraphDiagnosticCode.HIERARCHY_UNKNOWN


def test_duplicate_original_ids_make_parent_ambiguous() -> None:
    first = _topic("first", parent="-1", original="help.parent")
    second = _topic(
        "second", parent="-1", original="help.parent", locator="library/en/second.html"
    )
    child = _topic("child", parent="help.parent")

    graph = build_topic_hierarchy_graph((first, second, child))

    assert graph.direct_children(first.id) == ()
    assert graph.direct_children(second.id) == ()
    assert graph.diagnostics(child.id)[0].code is GraphDiagnosticCode.AMBIGUOUS_PARENT
    assert {item.code for item in graph.diagnostics()} >= {
        GraphDiagnosticCode.DUPLICATE_ORIGINAL_ID,
        GraphDiagnosticCode.AMBIGUOUS_PARENT,
    }


def test_cross_scope_parent_is_rejected_but_cross_library_is_valid() -> None:
    parent = _topic("parent", library="one")
    same_source_different_library = _topic("child", parent="help.parent", library="two")
    graph = build_topic_hierarchy_graph((parent, same_source_different_library))
    assert (
        graph.direct_children(parent.id)[0].canonical_id
        == same_source_different_library.id
    )

    for scope_change in (
        {"source_id": "other-source"},
        {"snapshot": "other-snapshot"},
        {"language": "de"},
    ):
        foreign_parent = _topic("parent", **scope_change)
        with pytest.raises(TopicHierarchyGraphScopeError):
            build_topic_hierarchy_graph((foreign_parent, same_source_different_library))


def test_duplicate_canonical_ids_are_rejected() -> None:
    first = _topic("first")
    second = _topic("second", locator=first.source.locator)

    with pytest.raises(TopicHierarchyGraphDuplicateCanonicalIDError):
        build_topic_hierarchy_graph((first, second))


def test_noncanonical_opaque_id_is_rejected_without_rewriting_input() -> None:
    topic = _topic("noncanonical")
    forged = topic.model_copy(update={"id": "opaque-but-valid"})

    with pytest.raises(TopicHierarchyGraphValidationError) as error:
        build_topic_hierarchy_graph((forged,))

    assert str(error.value) == "topic canonical ID is invalid"
    assert forged.id == "opaque-but-valid"


class _HostileSerializationTopic(Topic):
    dump_calls: ClassVar[int] = 0

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        type(self).dump_calls += 1
        data = json.loads(super().model_dump_json(*args, **kwargs))
        data["metadata"] = [
            {"name": "Microsoft.Help.TocParent", "content": "-1"},
            {"name": "Microsoft.Help.TocOrder", "content": "999"},
        ]
        return json.dumps(data)


def test_graph_owns_one_snapshot_instead_of_calling_topic_serializer() -> None:
    parent = _topic("parent")
    child = _HostileSerializationTopic.model_validate(
        child_data := _topic("child", parent="help.parent").model_dump()
    )

    graph = build_topic_hierarchy_graph((parent, child))
    node = graph.get_node(child.id)
    assert node is not None
    edge = next(item for item in graph.edges() if item.child_canonical_id == child.id)
    assert _HostileSerializationTopic.dump_calls == 0
    assert node.parent_original_topic_id == "help.parent"
    assert node.topic.metadata[0].content == "help.parent"
    assert edge.parent_original_topic_id == node.topic.metadata[0].content
    assert edge.toc_order == 1
    assert child_data["metadata"][0]["content"] == "help.parent"


class _OverboundSerializationTopic(Topic):
    dump_calls: ClassVar[int] = 0

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        type(self).dump_calls += 1
        data = json.loads(super().model_dump_json(*args, **kwargs))
        data["metadata"] = [
            {"name": "Microsoft.Help.TocParent", "content": "-1"}
        ] * 5_001
        return json.dumps(data)


def test_serializer_overbound_metadata_is_not_materialized() -> None:
    topic = _OverboundSerializationTopic.model_validate(_topic("bounded").model_dump())

    graph = build_topic_hierarchy_graph((topic,))

    assert graph.get_node(topic.id) is not None
    assert len(graph.get_node(topic.id).topic.metadata) == 2
    assert _OverboundSerializationTopic.dump_calls == 0


def test_actual_overbound_metadata_is_rejected_before_materialization() -> None:
    ordinary = _topic("overbound")
    topic = Topic.model_construct(
        **{
            **ordinary.__dict__,
            "metadata": tuple(
                TopicMetadata(name="Microsoft.Help.TocParent", content="-1")
                for _ in range(4_097)
            ),
        }
    )

    with pytest.raises(TopicHierarchyGraphValidationError) as error:
        build_topic_hierarchy_graph((topic,))

    assert str(error.value) == "topic is invalid"


class _StatefulMetadata(list[TopicMetadata]):
    def __init__(self, first: list[TopicMetadata], second: list[TopicMetadata]) -> None:
        super().__init__(first)
        self._second = second
        self.reads = 0

    def __iter__(self):  # type: ignore[no-untyped-def]
        self.reads += 1
        return iter(super().__iter__() if self.reads == 1 else self._second)


def test_graph_does_not_repeat_stateful_metadata_reads() -> None:
    parent = _topic("parent")
    ordinary_child = _topic("child", parent="help.parent")
    first = list(ordinary_child.metadata)
    second = [
        TopicMetadata(name="Microsoft.Help.TocParent", content="-1"),
        TopicMetadata(name="Microsoft.Help.TocOrder", content="999"),
    ]
    stateful = _StatefulMetadata(first, second)
    child = Topic.model_construct(
        **{
            **ordinary_child.__dict__,
            "metadata": stateful,
        }
    )

    graph = build_topic_hierarchy_graph((parent, child))
    node = graph.get_node(child.id)
    assert node is not None
    edge = next(item for item in graph.edges() if item.child_canonical_id == child.id)
    assert stateful.reads == 1
    assert node.parent_original_topic_id == "help.parent"
    assert edge.parent_original_topic_id == "help.parent"
    assert edge.toc_order == 1


def test_self_and_long_cycles_are_rejected_iteratively() -> None:
    self_cycle = _topic("self", parent="help.self")
    with pytest.raises(TopicHierarchyGraphCycleError):
        build_topic_hierarchy_graph((self_cycle,))

    topics = [_topic("n0", parent="help.n2")]
    topics.extend(_topic(f"n{i}", parent=f"help.n{i - 1}") for i in range(1, 4))
    topics[2] = _topic("n2", parent="help.n3")
    with pytest.raises(TopicHierarchyGraphCycleError):
        build_topic_hierarchy_graph(topics)


def test_depth_bound_is_fixed_and_does_not_recurse() -> None:
    topics = [_topic("n0")]
    for index in range(1, 6):
        topics.append(_topic(f"n{index}", parent=f"help.n{index - 1}"))

    with pytest.raises(TopicHierarchyGraphBoundsError):
        build_topic_hierarchy_graph(topics, max_depth=3)


def test_unknown_and_tied_order_use_labeled_technical_order() -> None:
    root = _topic("root")
    unknown = _topic("unknown", parent="help.root", order=None)
    tied_a = _topic("a", parent="help.root", order="2")
    tied_b = _topic("b", parent="help.root", order="2")
    graph = build_topic_hierarchy_graph((tied_b, unknown, root, tied_a))

    children = graph.direct_children(root.id)
    assert children[0].toc_order == 2
    assert all(node.technical_order for node in children)
    assert all(node.ordering != "toc_order" for node in children)
    assert any(node.order_tied for node in children)
    assert any(node.toc_order is None for node in children)

    permuted = build_topic_hierarchy_graph((root, tied_a, tied_b, unknown))
    assert tuple(
        node.canonical_id for node in permuted.direct_children(root.id)
    ) == tuple(node.canonical_id for node in children)


def test_source_and_outputs_are_immutable() -> None:
    parent = _topic("parent")
    child = _topic("child", parent="help.parent")
    graph = build_topic_hierarchy_graph((parent, child))
    node = graph.get_node(child.id)
    assert node is not None
    with pytest.raises(ValidationError):
        node.topic.title = "changed"
    with pytest.raises((AttributeError, TypeError)):
        graph.roots().append(node)  # type: ignore[attr-defined]
    assert graph.get_node(child.id).topic.title == "child"


def test_bounds_consume_only_cap_plus_one_and_sanitize_iterator_errors() -> None:
    consumed = 0

    def bomb():
        nonlocal consumed
        while True:
            consumed += 1
            yield _topic(f"n{consumed}")

    with pytest.raises(TopicHierarchyGraphBoundsError):
        build_topic_hierarchy_graph(bomb(), max_topics=2)
    assert consumed == 3

    def fails():
        yield _topic("one")
        raise TopicHierarchyGraphValidationError("caller secret")

    with pytest.raises(TopicHierarchyGraphValidationError) as error:
        build_topic_hierarchy_graph(fails())
    assert str(error.value) != "caller secret"


def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    import twincat_knowledge.corpus.topic_hierarchy_graph as module

    def cancel(_topic: Topic):
        raise asyncio.CancelledError

    monkeypatch.setattr(module, "_extract_topic_hierarchy_from_snapshot", cancel)
    with pytest.raises(asyncio.CancelledError):
        build_topic_hierarchy_graph((_topic("cancel"),))
