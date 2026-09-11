"""Pure, bounded, immutable graph projection for explicit topic hierarchy metadata.

The graph is deliberately separate from ``Topic`` and package formats.  It
revalidates every topic through the bounded primitive-copy seam owned by
``ingest.topic_hierarchy``, derives the stored topic and assessment from that
same snapshot, resolves an original parent ID only in
``(source_id, snapshot_id, language)``, and never infers relationships from
library, title, path, links, or input order.

``MAX_GRAPH_DEPTH`` is an implementation limit.  Construction and breadcrumb
walks are iterative, so a deep or hostile input cannot consume the Python call
stack.  A graph with no usable hierarchy has ``has_hierarchy == False``;
``has_hierarchy == True`` with no roots means explicit hierarchy exists but no
root is currently resolvable.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from twincat_knowledge.domain.identity import canonical_topic_id
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topic_hierarchy import TopicHierarchy
from twincat_knowledge.domain.topics import Topic
from twincat_knowledge.ingest.topic_hierarchy import (
    _extract_topic_hierarchy_from_snapshot,
    _revalidate_topic,
)

MAX_GRAPH_TOPICS: Final = 100_000
MAX_GRAPH_DEPTH: Final = 4_096


class GraphDiagnosticCode(StrEnum):
    """Non-inferred states retained on nodes and breadcrumbs."""

    HIERARCHY_UNKNOWN = "hierarchy_unknown"
    UNRESOLVED_PARENT = "unresolved_parent"
    DUPLICATE_ORIGINAL_ID = "duplicate_original_id"
    AMBIGUOUS_PARENT = "ambiguous_parent"
    BREADCRUMB_CYCLE = "breadcrumb_cycle"
    BREADCRUMB_DEPTH = "breadcrumb_depth"


class TopicHierarchyGraphError(RuntimeError):
    """Base class for controlled graph construction failures."""


class TopicHierarchyGraphValidationError(TopicHierarchyGraphError, ValueError):
    """The supplied topic stream or graph input is invalid."""


class TopicHierarchyGraphBoundsError(TopicHierarchyGraphValidationError):
    """A topic-count or graph-depth bound was exceeded."""


class TopicHierarchyGraphDuplicateCanonicalIDError(TopicHierarchyGraphValidationError):
    """Two supplied topics use the same canonical topic ID."""


class TopicHierarchyGraphCanonicalIDError(TopicHierarchyGraphValidationError):
    """A topic ID does not match its source-derived canonical identity."""


class TopicHierarchyGraphScopeError(TopicHierarchyGraphValidationError):
    """An explicit parent exists only outside the child's source scope."""


class TopicHierarchyGraphCycleError(TopicHierarchyGraphValidationError):
    """Resolved explicit parent edges contain a cycle."""


@dataclass(frozen=True, slots=True)
class TopicHierarchyDiagnostic:
    """One source-bound, non-inferred graph diagnostic."""

    code: GraphDiagnosticCode
    topic_id: str
    source: SourceReference
    parent_original_topic_id: str | None = None


@dataclass(frozen=True, slots=True)
class TopicHierarchyNode:
    """Immutable topic view returned by graph accessors."""

    canonical_id: str
    topic: Topic
    original_topic_id: str | None
    parent_canonical_id: str | None
    parent_original_topic_id: str | None
    toc_order: int | None
    order_tied: bool
    technical_order: bool
    diagnostics: tuple[TopicHierarchyDiagnostic, ...]

    @property
    def ordering(self) -> Literal["toc_order", "technical_canonical_id"]:
        """Describe whether ordering is source order or a technical fallback."""
        return "toc_order" if not self.technical_order else "technical_canonical_id"

    @property
    def id(self) -> str:
        """Alias for the canonical topic ID."""
        return self.canonical_id


@dataclass(frozen=True, slots=True)
class TopicHierarchyEdge:
    """One resolved edge, retaining the exact source parent value and provenance."""

    child_canonical_id: str
    parent_canonical_id: str
    parent_original_topic_id: str
    source: SourceReference
    toc_order: int | None

    @property
    def child_id(self) -> str:
        return self.child_canonical_id

    @property
    def parent_id(self) -> str:
        return self.parent_canonical_id


@dataclass(frozen=True, slots=True)
class TopicBreadcrumb:
    """A bounded on-demand root-to-topic walk.

    ``diagnostic is None`` means the walk reached an explicit ``-1`` root.
    Otherwise the returned items are only the verified prefix; no completeness
    claim is synthesized for an unresolved or unknown chain.
    """

    items: tuple[TopicHierarchyNode, ...]
    diagnostic: GraphDiagnosticCode | None


@dataclass(frozen=True, slots=True)
class TopicHierarchyGraph:
    """Read-only graph over a finite normalized topic collection."""

    has_hierarchy: bool
    _nodes: Mapping[str, TopicHierarchyNode]
    _edges: Mapping[str, TopicHierarchyEdge]
    _children: Mapping[str, tuple[str, ...]]
    _roots: tuple[str, ...]
    _diagnostics: tuple[TopicHierarchyDiagnostic, ...]
    _max_depth: int = MAX_GRAPH_DEPTH

    def __post_init__(self) -> None:
        object.__setattr__(self, "_nodes", MappingProxyType(dict(self._nodes)))
        object.__setattr__(self, "_edges", MappingProxyType(dict(self._edges)))
        object.__setattr__(self, "_children", MappingProxyType(dict(self._children)))

    def roots(self) -> tuple[TopicHierarchyNode, ...]:
        """Return explicit ``TocParent=-1`` roots in deterministic order."""
        return tuple(self._nodes[item] for item in self._roots)

    def direct_children(self, canonical_id: str) -> tuple[TopicHierarchyNode, ...]:
        """Return only directly resolved children of a canonical topic ID."""
        if not isinstance(canonical_id, str):
            raise TopicHierarchyGraphValidationError("canonical topic ID is invalid")
        return tuple(self._nodes[item] for item in self._children.get(canonical_id, ()))

    def get_node(self, canonical_id: str) -> TopicHierarchyNode | None:
        """Return a node by canonical ID without exposing internal maps."""
        if not isinstance(canonical_id, str):
            raise TopicHierarchyGraphValidationError("canonical topic ID is invalid")
        return self._nodes.get(canonical_id)

    def diagnostics(
        self, canonical_id: str | None = None
    ) -> tuple[TopicHierarchyDiagnostic, ...]:
        """Return all diagnostics, or only those attached to one node."""
        if canonical_id is None:
            return self._diagnostics
        node = self.get_node(canonical_id)
        return () if node is None else node.diagnostics

    def edges(self) -> tuple[TopicHierarchyEdge, ...]:
        """Return resolved edges as an immutable, deterministic tuple."""
        return tuple(self._edges[item] for item in sorted(self._edges))

    def breadcrumb(self, canonical_id: str) -> TopicBreadcrumb | None:
        """Compute one bounded breadcrumb without enumerating the whole graph."""
        if not isinstance(canonical_id, str):
            raise TopicHierarchyGraphValidationError("canonical topic ID is invalid")
        current = self._nodes.get(canonical_id)
        if current is None:
            return None
        walked: list[TopicHierarchyNode] = []
        visited: set[str] = set()
        diagnostic: GraphDiagnosticCode | None = None
        for _ in range(self._max_depth + 1):
            if current.canonical_id in visited:
                diagnostic = GraphDiagnosticCode.BREADCRUMB_CYCLE
                break
            visited.add(current.canonical_id)
            walked.append(current)
            edge = self._edges.get(current.canonical_id)
            if edge is None:
                diagnostic = (
                    None
                    if current.parent_original_topic_id == "-1"
                    else _node_terminal_diagnostic(current)
                )
                break
            parent = self._nodes.get(edge.parent_canonical_id)
            if parent is None:
                diagnostic = GraphDiagnosticCode.UNRESOLVED_PARENT
                break
            current = parent
        else:
            diagnostic = GraphDiagnosticCode.BREADCRUMB_DEPTH
        walked.reverse()
        return TopicBreadcrumb(tuple(walked), diagnostic)


def _limit(value: object, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TopicHierarchyGraphBoundsError(f"{name} is outside its supported bound")
    if value < 1 or value > maximum:
        raise TopicHierarchyGraphBoundsError(f"{name} is outside its supported bound")
    return value


def _caller_topics(topics: Iterable[Topic]) -> Iterator[Topic]:
    try:
        iterator = iter(topics)
    except Exception:
        raise TopicHierarchyGraphValidationError("topic iterator is invalid") from None
    while True:
        try:
            item = next(iterator)
        except StopIteration:
            return
        except Exception:
            raise TopicHierarchyGraphValidationError(
                "topic iterator is invalid"
            ) from None
        yield item


def _scope(topic: Topic) -> tuple[str, str, str]:
    return (topic.source.source_id, topic.source.snapshot_id, topic.language)


def _node_terminal_diagnostic(
    node: TopicHierarchyNode,
) -> GraphDiagnosticCode:
    for diagnostic in node.diagnostics:
        if diagnostic.code in {
            GraphDiagnosticCode.HIERARCHY_UNKNOWN,
            GraphDiagnosticCode.UNRESOLVED_PARENT,
            GraphDiagnosticCode.AMBIGUOUS_PARENT,
        }:
            return diagnostic.code
    return GraphDiagnosticCode.UNRESOLVED_PARENT


def _make_node(
    topic: Topic,
    hierarchy: TopicHierarchy | None,
    *,
    parent_id: str | None = None,
    diagnostics: tuple[TopicHierarchyDiagnostic, ...] = (),
) -> TopicHierarchyNode:
    parent_original = None if hierarchy is None else hierarchy.parent_original_topic_id
    order = None if hierarchy is None else hierarchy.toc_order
    return TopicHierarchyNode(
        canonical_id=topic.id,
        topic=topic,
        original_topic_id=topic.original_topic_id,
        parent_canonical_id=parent_id,
        parent_original_topic_id=parent_original,
        toc_order=order,
        order_tied=False,
        technical_order=order is None,
        diagnostics=diagnostics,
    )


def _order_nodes(
    node_ids: list[str], nodes: dict[str, TopicHierarchyNode]
) -> tuple[tuple[str, ...], dict[str, TopicHierarchyNode]]:
    counts = Counter(
        nodes[item].toc_order for item in node_ids if nodes[item].toc_order is not None
    )
    tied = {item for item in node_ids if counts[nodes[item].toc_order] > 1}
    ordered = tuple(
        sorted(
            node_ids,
            key=lambda item: (
                0 if nodes[item].toc_order is not None else 1,
                nodes[item].toc_order if nodes[item].toc_order is not None else 0,
                item,
            ),
        )
    )
    for item in node_ids:
        node = nodes[item]
        nodes[item] = replace(
            node,
            order_tied=item in tied,
            technical_order=node.toc_order is None or item in tied,
        )
    return ordered, nodes


def build_topic_hierarchy_graph(
    topics: Iterable[Topic],
    *,
    max_topics: int = MAX_GRAPH_TOPICS,
    max_depth: int = MAX_GRAPH_DEPTH,
) -> TopicHierarchyGraph:
    """Build a graph from a finite topic iterable.

    The iterable is consumed incrementally through ``max_topics + 1`` attempts.
    Each topic is freshly checked by the reviewed bounded primitive-copy helper
    before graph ownership begins.  The returned checked topic and hierarchy
    assessment share that one owned snapshot; no caller serializer is invoked.
    No caller iterator is closed by this function.
    """
    topic_limit = _limit(max_topics, "max_topics", MAX_GRAPH_TOPICS)
    depth_limit = _limit(max_depth, "max_depth", MAX_GRAPH_DEPTH)
    checked_topics: list[Topic] = []
    assessments = []
    seen_ids: set[str] = set()

    for count, supplied in enumerate(_caller_topics(topics), start=1):
        if count > topic_limit:
            raise TopicHierarchyGraphBoundsError(
                "topic count exceeds its supported bound"
            )
        if not isinstance(supplied, Topic):
            raise TopicHierarchyGraphValidationError(
                "topics must contain only Topic models"
            )
        try:
            checked = _revalidate_topic(supplied)
            assessment = _extract_topic_hierarchy_from_snapshot(checked)
        except Exception:
            raise TopicHierarchyGraphValidationError("topic is invalid") from None
        expected_id = canonical_topic_id(
            checked.source.source_id,
            checked.source.snapshot_id,
            checked.language,
            checked.source.locator,
        )
        if checked.id != expected_id:
            raise TopicHierarchyGraphCanonicalIDError("topic canonical ID is invalid")
        if checked.id != assessment.topic_id or checked.source != assessment.source:
            raise TopicHierarchyGraphValidationError(
                "topic hierarchy provenance is invalid"
            )
        if checked.id in seen_ids:
            raise TopicHierarchyGraphDuplicateCanonicalIDError(
                "duplicate canonical topic ID"
            )
        seen_ids.add(checked.id)
        checked_topics.append(checked)
        assessments.append(assessment)

    nodes: dict[str, TopicHierarchyNode] = {}
    diagnostics_by_id: dict[str, list[TopicHierarchyDiagnostic]] = defaultdict(list)
    by_scope_original: dict[tuple[tuple[str, str, str], str], list[str]] = defaultdict(
        list
    )
    by_original: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for topic, assessment in zip(checked_topics, assessments, strict=True):
        hierarchy = assessment.hierarchy
        nodes[topic.id] = _make_node(topic, hierarchy)
        if topic.original_topic_id is not None:
            key = (_scope(topic), topic.original_topic_id)
            by_scope_original[key].append(topic.id)
            by_original[topic.original_topic_id].add(_scope(topic))
        if hierarchy is None:
            diagnostics_by_id[topic.id].append(
                TopicHierarchyDiagnostic(
                    GraphDiagnosticCode.HIERARCHY_UNKNOWN,
                    topic.id,
                    assessment.source,
                )
            )

    for (_scope_key, original), candidate_ids in by_scope_original.items():
        if len(candidate_ids) <= 1:
            continue
        for candidate in candidate_ids:
            candidate_topic = nodes[candidate].topic
            diagnostics_by_id[candidate].append(
                TopicHierarchyDiagnostic(
                    GraphDiagnosticCode.DUPLICATE_ORIGINAL_ID,
                    candidate,
                    candidate_topic.source,
                    original,
                )
            )

    edges: dict[str, TopicHierarchyEdge] = {}
    children: dict[str, list[str]] = defaultdict(list)
    root_ids: list[str] = []
    has_hierarchy = any(assessment.hierarchy is not None for assessment in assessments)

    for topic, assessment in zip(checked_topics, assessments, strict=True):
        hierarchy = assessment.hierarchy
        if hierarchy is None:
            continue
        parent_original = hierarchy.parent_original_topic_id
        if parent_original == "-1":
            root_ids.append(topic.id)
            continue
        candidates = by_scope_original.get((_scope(topic), parent_original), [])
        if len(candidates) > 1:
            diagnostics_by_id[topic.id].append(
                TopicHierarchyDiagnostic(
                    GraphDiagnosticCode.AMBIGUOUS_PARENT,
                    topic.id,
                    assessment.source,
                    parent_original,
                )
            )
            continue
        if not candidates:
            if by_original.get(parent_original, set()) - {_scope(topic)}:
                raise TopicHierarchyGraphScopeError(
                    "parent exists outside source scope"
                )
            diagnostics_by_id[topic.id].append(
                TopicHierarchyDiagnostic(
                    GraphDiagnosticCode.UNRESOLVED_PARENT,
                    topic.id,
                    assessment.source,
                    parent_original,
                )
            )
            continue
        parent_id = candidates[0]
        edge = TopicHierarchyEdge(
            child_canonical_id=topic.id,
            parent_canonical_id=parent_id,
            parent_original_topic_id=parent_original,
            source=assessment.source,
            toc_order=hierarchy.toc_order,
        )
        edges[topic.id] = edge
        children[parent_id].append(topic.id)
        nodes[topic.id] = _make_node(topic, hierarchy, parent_id=parent_id)

    for topic_id, node in tuple(nodes.items()):
        nodes[topic_id] = replace(
            node,
            diagnostics=tuple(diagnostics_by_id[topic_id]),
        )

    indegree = {topic_id: 0 for topic_id in nodes}
    for edge in edges.values():
        indegree[edge.child_canonical_id] += 1
    queue = deque(topic_id for topic_id, degree in indegree.items() if degree == 0)
    topological: list[str] = []
    while queue:
        current = queue.popleft()
        topological.append(current)
        for child in children.get(current, ()):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(topological) != len(nodes):
        raise TopicHierarchyGraphCycleError("resolved topic hierarchy contains a cycle")

    depths: dict[str, int] = {}
    for topic_id in topological:
        resolved_edge = edges.get(topic_id)
        depth = (
            1
            if resolved_edge is None
            else depths[resolved_edge.parent_canonical_id] + 1
        )
        if depth > depth_limit:
            raise TopicHierarchyGraphBoundsError(
                "topic hierarchy depth exceeds its bound"
            )
        depths[topic_id] = depth

    ordered_children: dict[str, tuple[str, ...]] = {}
    for parent_id, child_ids in children.items():
        ordered_children[parent_id], nodes = _order_nodes(child_ids, nodes)
    ordered_roots, nodes = _order_nodes(root_ids, nodes)
    all_diagnostics = tuple(
        diagnostic
        for topic_id in sorted(nodes)
        for diagnostic in nodes[topic_id].diagnostics
    )
    return TopicHierarchyGraph(
        has_hierarchy=has_hierarchy,
        _nodes=nodes,
        _edges=edges,
        _children=ordered_children,
        _roots=ordered_roots,
        _diagnostics=all_diagnostics,
        _max_depth=depth_limit,
    )


TopicNode = TopicHierarchyNode
TopicEdge = TopicHierarchyEdge
GraphDiagnostic = TopicHierarchyDiagnostic
build_graph = build_topic_hierarchy_graph


__all__ = [
    "GraphDiagnostic",
    "GraphDiagnosticCode",
    "MAX_GRAPH_DEPTH",
    "MAX_GRAPH_TOPICS",
    "TopicBreadcrumb",
    "TopicEdge",
    "TopicHierarchyDiagnostic",
    "TopicHierarchyGraph",
    "TopicHierarchyGraphBoundsError",
    "TopicHierarchyGraphCanonicalIDError",
    "TopicHierarchyGraphCycleError",
    "TopicHierarchyGraphDuplicateCanonicalIDError",
    "TopicHierarchyGraphError",
    "TopicHierarchyGraphScopeError",
    "TopicHierarchyGraphValidationError",
    "TopicHierarchyNode",
    "TopicNode",
    "build_graph",
    "build_topic_hierarchy_graph",
]
