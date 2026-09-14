# Topic normalization

This slice converts immutable `InfoSysTopic` reader records into immutable
`Topic`/`Section` domain records. The normalized models live in
`twincat_knowledge.domain.topics` and do not import an ingest adapter.

## API

```python
from twincat_knowledge.ingest.normalize import normalize_infosys

normalized = normalize_infosys(info_sys_topics, source_snapshots)
```

`normalize_infosys` returns a `tuple[Topic, ...]`. It requires every topic to
match a supplied `SourceSnapshot` by `(source_id, snapshot_id, language)`, and
rejects duplicate mappings, duplicate normalized IDs, malformed input models,
and a topic iterator larger than `max_topics` (default `100_000`). Snapshot
metadata is bounded to `10_000` records. Iterators are consumed incrementally;
there is no unbounded `list(iterator)` conversion.

## Identity and provenance

Topic IDs are opaque SHA-256 identifiers over canonical JSON containing exactly
the source ID, snapshot ID, topic language, and the raw locator. Section IDs
are opaque SHA-256 identifiers over the topic ID and zero-based section index.
Consequently, title similarity does not merge topics: different snapshots,
languages, or locators remain distinct. The raw locator is retained unchanged.

The topic `source` and every section `source` retain the source ID, snapshot ID,
original topic/help ID, title, language, canonical URL, locator, and content
hash. Section references add their own `section_id`. Article content hashes are
not compared with `SourceSnapshot.content_hash`, which may be a whole-source
archive hash; the normalizer cannot verify bytes it cannot see.

## Content and safety boundaries

Paragraph, code, table, and warning sections retain their typed payloads in
source order. Code whitespace and language, table row/cell boundaries (including
empty or whitespace-only cells), and warning text are not normalized. Help and
image references are retained as untrusted strings. No URL is fetched, opened,
resolved, or executed, and document text is never treated as instructions.

`SourceSnapshot`'s missing documented version remains absent with
`applicability="unknown"`; this slice infers no product, symbol, version, or
applicability facts. Rights are not approved by normalization: the supplied
snapshot's rights reference remains operator metadata.

## Review remediation and verification

Public `Topic` and `Section` constructors and JSON validation enforce consistent
provenance, not merely immutable field types. Section IDs must match their source
section IDs. A topic has an article-level source, matching language and original
help ID; every section must have identical shared source fields, and duplicate
section IDs are rejected. A supplied source title must match the topic title;
`None` remains unknown and is not replaced with an inferred title.

`TopicMetadata` preserves reader metadata names, values, attributes, order and
repetitions as uninterpreted evidence. Conflicting version strings do not become
validated applicability facts. Metadata is covered by the enclosing article's
source hash/locator; normalization neither verifies that hash nor interprets the
claims. The domain models remain independent of the InfoSys adapter.

Independent-review regression evidence:

- M-01 public provenance boundary: 13 failing JSON regressions before correction;
  then 22 focused tests passed, including the existing normalization suite.
- M-02 metadata preservation: one failing reader-to-normalizer regression before
  adding `TopicMetadata`; then 23 focused tests passed.
- L-01 title disagreement: two failing public-boundary regressions before
  correction; an absent-title compatibility case already passed and remains valid.
- Final new regressions: 17 passed.
- Full suite: 107 passed on CPython 3.12.10 and 3.13.12, including independent
  wheel and sdist installation with `python -I` in a foreign working directory,
  installed-module location checks and reader/normalizer/JSON roundtrips.
- Ruff check, format check and mypy passed. Independent follow-up review remains
  required; these coordinator tests are not an approval.

## Deliberate non-scope

This is only the bounded normalization boundary. It adds no importer, crawler,
SQLite/index storage, package activation, MCP tool, rights decision, or source
byte verification. Public package re-exports and integration wiring belong to
an owning integration slice.
