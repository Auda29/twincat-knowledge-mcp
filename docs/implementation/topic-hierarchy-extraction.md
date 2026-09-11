# Topic hierarchy metadata extraction

This slice extracts explicit Microsoft Help Viewer TOC metadata from an already
normalized `Topic`. It does not add fields to `Topic`, rewrite JSONL records, or
resolve a graph.

## API

```python
from twincat_knowledge.ingest.topic_hierarchy import extract_topic_hierarchy

assessment = extract_topic_hierarchy(normalized_topic)
```

`TopicHierarchyAssessment` is immutable and source-bound. Its `topic_id` is the
normalized canonical topic ID and its `source` is the topic's existing
article-level `SourceReference`, copied without inventing a section anchor.
`hierarchy` is either `None` or a `TopicHierarchy` containing:

- `parent_original_topic_id`: the exact `Microsoft.Help.TocParent` content;
  `-1` is the only explicit root marker;
- `toc_order`: a positive integer from `Microsoft.Help.TocOrder`, or `None`
  when no usable explicit order exists.

A real parent ID remains unresolved. This module makes no assumptions about
library, language, snapshot, or catalog scope, and does not detect cycles or
claim that the result is a valid tree. `hierarchy=None` is unavailable, not a
root.

## Metadata rules and bounds

The extractor reads only case-insensitive matches for
`Microsoft.Help.TocParent` and `Microsoft.Help.TocOrder`. All other metadata,
links, title, locator/path, body text, and archive order are ignored. The
normalized topic's raw metadata remains untouched.

- At most 4,096 metadata entries, 4,096 attributes per metadata entry, and
  100,000 sections/links are accepted during revalidation.
- A parent ID is at most 512 characters. Blank, edge-whitespace, control,
  malformed, or oversized values make hierarchy unavailable; the value is
  never stripped or repaired. Duplicate parent metadata is unavailable even
  when both values are identical.
- An order uses ASCII decimal digits only, with at most 8 lexical digits and
  an implementation resource bound of 1 through 10,000,000 for this extractor;
  this is not a Microsoft Help Viewer format limit. Signs, floats, Unicode
  digits, zero, and oversized values are not normalized. Missing, invalid, or
  duplicate order preserves a valid parent but returns `toc_order=None` plus an
  enum diagnostic.

Diagnostics are `HierarchyDiagnosticCode` enum members, never raw metadata or
exception text. Invalid `model_construct`/`model_copy` inputs are rebuilt
through bounded field copies rather than blindly serialized, so cyclic caller
objects are rejected with a fixed extraction error. Ordinary exceptions are
sanitized while cancellation/base exceptions propagate.

The installed wheel and source-archive path exercise reader → normalization →
export → package build/load → extraction. Existing topic schema, reader,
index, package versions, CLI, MCP catalog, SDK, dependencies, and CI remain
unchanged in this slice.
