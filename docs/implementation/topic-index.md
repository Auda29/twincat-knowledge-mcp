# Topic index component checkpoint

## Scope

`twincat_knowledge.corpus.topic_index` provides operator-side SQLite creation and
read-only lookup against a **caller-validated package artifact**. It does not yet
validate package hashes, rights, source bytes, adversarial SQLite files, or corpus
coverage. No MCP tool, package activation, complete importer, or CLI integration is
provided by this slice. SQLite is stdlib; FTS5 is checked by creating an actual
virtual table in a temporary in-memory database. There is no search fallback.

## API

- `create_topic_index(path, topics, *, max_topics=100000,
  max_topic_json_bytes=1048576, max_search_text_bytes=1048576) -> int`
- `with TopicIndex(path) as index: ...`
- `index.get_topic(topic_id) -> Topic | None`
- `index.search(query, *, language=None, library=None, source_snapshot_id=None,
  limit=20, offset=0) -> tuple[Topic, ...]`

Index schema version is 1. Normalized Topic JSON preserves metadata, ordered code,
paragraphs, warnings, tables, original IDs and section provenance. Search text is
the title followed by section text/code/table cells; metadata and links are not
included in the search text. FTS5 uses its default unicode61 tokenizer and BM25,
with Topic ID as a deterministic tie-breaker. Query strings are quoted as literal
FTS phrases; arbitrary FTS operators and SQL are not passed through. Multiword
queries currently mean a phrase, not an implicit bag-of-words AND query.

Language, library and source-snapshot filters use bound values. Missing IDs return
`None`, never another generation. Empty queries return no results. The component
returns full Topic records; bounded response envelopes, cursors and citation
formatting for MCP remain future integration work.

## Limits and file ownership

Topic count is bounded incrementally, retaining one serialized record at a time.
Each JSON record and generated search string is limited to 1 MiB UTF-8 after
serialization; these are output-size checks, not a claim that serialization of
arbitrarily large pre-existing in-memory objects allocates no memory. Query and
filter strings are limited to 512 UTF-8 bytes, results to 20 and offset to 100000.
Configurable build limits can only be lowered from the hard maxima.

The operator chooses an output in an existing directory. Build occurs inside an
owned private temporary directory on the same filesystem. SQLite connections are
closed before cleanup, including failure paths. The complete file is fsynced and
published with an exclusive hard link: existing files/symlinks and concurrently
created output files are never replaced. A filesystem without hard-link support
fails explicitly; there is no overwrite-capable fallback. This is atomic file
visibility, not full package activation or a power-loss durability guarantee.

Cleanup touches only the private staging directory, never `output-journal`,
`output-wal` or `output-shm` in the operator directory. The opener uses an encoded
file URI in `mode=ro`, checks schema version, and verifies `query_only=ON` and
`trusted_schema=OFF`. Caller-validated index artifacts must remain immutable while
open. These settings are not sufficient to trust an arbitrary external database.
Operator errors are not yet an agent-facing error envelope.

## Recovery and executed verification

The original index delegation lost its owner before completion and left only
three tests. The coordinator reproduced the missing-module RED, implemented the
minimal roundtrip, and observed 3 focused / 110 full tests passing in `cedc869`.
A second delegation also lost its terminal result, but preserved two clean
commits (`a35eda5`, `4760d2f`). Their results were not assumed: the coordinator
reran the code and observed 121 full tests, Ruff/format/mypy passing.

Coordinator review then reproduced four failures: deletion of foreign files with
SQLite sidecar suffixes and exposure of a partial output. Private staging and
exclusive publication changed these to 18 focused tests passing. Final full
suite: **125 passed on CPython 3.12.10 and 3.13.12**; Ruff check, format check and
mypy passed. Existing wheel/sdist tests ran, but they do not yet explicitly import
or query the new index module; that installed-index assertion remains open.

Independent index review and native Windows/Linux CI for this component remain
required. The upstream artifact-upload quota issue is separate and has not been
bypassed. No merge or complete-product acceptance is claimed.
