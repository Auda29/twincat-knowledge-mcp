# Topic hierarchy graph

`twincat_knowledge.corpus.topic_hierarchy_graph` is a pure, read-only projection
of normalized `Topic` records. It does not change the `Topic` JSON shape, the
SQLite index, package manifests, or the MCP catalog.

```python
from twincat_knowledge.corpus.topic_hierarchy_graph import (
    build_topic_hierarchy_graph,
)

graph = build_topic_hierarchy_graph(topics)
roots = graph.roots()
children = graph.direct_children(roots[0].canonical_id)
trail = graph.breadcrumb(children[0].canonical_id)
```

## Resolution contract

Each input is freshly validated with `extract_topic_hierarchy` and copied into
the graph. A parent is resolved by exact original topic ID only within
`(source_id, snapshot_id, language)`. Libraries do not define identity scope,
so an explicit cross-library link inside that scope is valid. A match in another
source, snapshot, or language is rejected rather than crossed. A topic without
an original ID is never a parent candidate.

Only `Microsoft.Help.TocParent=-1` is a root. Missing/invalid hierarchy is
reported as `hierarchy_unknown`, not as a root. A missing same-scope parent is
`unresolved_parent`. Multiple same-scope candidates produce separate
`duplicate_original_id` diagnostics on the candidates and an
`ambiguous_parent` diagnostic on the child; no candidate is selected.
Resolved edges retain the exact parent value and the child `SourceReference`.

`graph.has_hierarchy` distinguishes capability from root count: `False` means
no input had usable hierarchy metadata, while `True` with `graph.roots() == ()`
means hierarchy was present but no explicit root was available.

## Bounds and ordering

The topic stream is consumed incrementally and the `max_topics + 1` item is the
first over-bound check. Caller iterators are not closed. Ordinary iterator and
validation failures become fixed graph errors; `BaseException` cancellation is
not swallowed.

Resolved edges are cycle-checked with iterative Kahn traversal in O(V+E), and
self-cycles/multi-node cycles raise `TopicHierarchyGraphCycleError`. The
implementation depth limit is `MAX_GRAPH_DEPTH` (4,096), configurable downward
with `max_depth`; deep input raises a typed bounds error without recursion.
Breadcrumbs are computed only when requested, with a visited set and the same
bound. An incomplete trail returns only the verified prefix and a diagnostic;
it does not claim completion.

Valid `TocOrder` sorts siblings. Missing orders and ties are deterministic by
canonical ID only as a technical fallback, and nodes expose `technical_order`,
`order_tied`, and `ordering` so this is never presented as source TOC order.
All accessor collections are tuples and internal maps are not exposed.
