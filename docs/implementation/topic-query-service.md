# Bounded topic query service

`twincat_knowledge.services.TopicQueryService` is the domain retrieval service for
one caller-owned `LoadedTopicPackage`. It is not an MCP server or transport
adapter. The caller supplies either a validated loaded handle or `None`; the
service never loads, reloads, activates, or closes that handle.

## Browse

`browse_topics` exposes only explicit roots or direct resolved children. It returns
canonical topic IDs, titles, language/library, parent ID, hierarchy/order
availability, bounded identity-only breadcrumbs, and source citations; it never
returns topic bodies. A missing corpus or a package with no usable hierarchy is
`not_available`. An unknown parent ID is `not_found`, while a known parent with
no resolved children is an `ok` response with an empty item tuple. A hierarchy
with no resolvable explicit roots is an empty `not_found` root response with a
diagnostic warning, not an assertion that the corpus has no topics.

Browse accepts the package snapshot ID, `language`, and exact topic `library_id`
filters. Other existing filter fields are rejected explicitly. Snapshot filtering
uses package identity; graph parent resolution still retains each topic's
original `(source_id, snapshot_id, language)` scope. A breadcrumb may therefore
contain an ancestor outside the listing filter, because it is context rather than
an additional filtered result. Siblings use explicit `TocOrder` when available;
ties and missing order are deterministically resolved by canonical ID and marked
as technical ordering.

Each browse item reports `breadcrumb_complete`, `breadcrumb_truncated`, and the
typed `breadcrumb_diagnostic` enum. `hierarchy` describes the node's local
resolved edge availability; it does not claim that the full root path is
complete. An unresolved, ambiguous, unknown, cyclic, or depth-bounded ancestor
therefore remains a source-bound contextual prefix with a diagnostic rather than
an invented root or a false complete breadcrumb. An explicit `TocParent=-1`
root has a complete breadcrumb and a null diagnostic.

Browse responses additionally report `actual_ascii_bytes` for the final compact
ASCII JSON envelope and `ascii_byte_budget`. The size is measured after the
actual cursor, warnings, sources, completion flags, and browse fields are
present; it is not a projection of an intermediate candidate envelope.

Graph construction consumes the public `TopicIndex.iter_topics()` context
manager directly. The index issues a deterministic canonical-ID `ORDER BY id`
query with `LIMIT max_topics + 1`, checks the count sentinel and each payload's
byte bound before Pydantic parsing, and closes its cursor on normal exhaustion,
graph rejection, cancellation, and caller exceptions. The API is intended for
the trusted loaded index path: direct callers opening an arbitrary SQLite file
do not receive package-manifest/JSONL cross-verification, and this change does
not add a schema or package-format revision.

## Contracts

`SearchInput`, `GetTopicInput`, and `CorpusStatusInput` are frozen, strict
Pydantic models with forbidden extra fields. The service revalidates a fresh
Python payload at every public-method boundary, including nested filters, so
`model_construct` and `model_copy` cannot bypass the input contract. Their
responses are typed `ResponseEnvelope` models with `schema_version`, `status`,
`snapshot_ids`, `data`, `sources`, `warnings`, `truncated`, and `next_cursor`.
Search implements only `topics`; absent topic data and all other categories return
`not_available`, rather than pretending that manifest count fields are usable
entity indexes.

Search accepts `query` of 1--512 Unicode characters, rejects NUL, and enforces a
2048-byte UTF-8 ceiling (the index ceiling was raised from 512 bytes so the
character contract admits 512 four-byte characters). The index receives the
query as a literal quoted FTS phrase. Search pages are 1--20 items, ordered by
the existing deterministic BM25/ID ordering. `total` remains `null`: the
service does not perform an unbounded count. `has_more` is established by a
separate one-row lookahead (including for a page of 20), and a result item
contains only ID, title, a bounded snippet, kind, and provenance.

Supported filters are package `snapshot_id` (the loaded package snapshot
only) and language `de`, `en`, or `any`. A source snapshot ID is not a service
filter: querying it returns `not_found`; this preserves the original
package-generation-only contract. The independent review described accepting
indexed source snapshots as a possible dual-meaning API, but that was a
coordinator contract correction, not an authorized behavior change. `library_id`,
`product_family`, `documented_version`, and `device_revision` are rejected
explicitly. The topic model's raw `library` string is not promoted to a library
entity.

`get_topic` performs exact ID lookup only. It preserves source order and returns
whole paragraph, code, table, and warning sections. Explicit section selection
is source-ordered, and unknown section IDs are an error. Pagination stops only
between records; code and warning payloads are never cut. A section or metadata
record that cannot fit is reported as an explicit oversized-content error.

Pagination tests the actual final ASCII JSON envelope, including the exact
cursor (when one is needed), warnings, sources, and completion flags. Each
page is the maximal nonempty whole-record prefix up to the requested limit
that fits; only returned records are consumed, so authenticated cursor
positions advance monotonically without duplicates or loops. A final complete
page is measured without a cursor. If an individual whole item plus its
required cursor cannot fit, the service returns an explicit oversized-content
error rather than an unusable progress cursor.

The first implementation does not segment oversized individual sections; that
is a known follow-up limitation and is not represented as a complete response.

Corpus status is projected only from the validated manifest and immutable
summary. It reports package/source identity, actual topic/section/language
counts, the lexical search mode, topic as the only implemented category, and a
safe paginated source inventory. It omits rights references, local paths,
secrets, and unsupported entity-count claims. Source pages use the same
actual-envelope fitting rule and shrink to a whole prefix when the caller's
limit is too large; `source_count` remains the full validated inventory count
and cursor traversal covers every source once.

## Cursors and bounds

Cursors are opaque, HMAC-authenticated tokens created by a per-service
cryptographic secret. They bind the exact package generation (including
manifest artifact hashes and sizes), tool, query or status selection, filters,
selected sections, page size, and internal position. They contain no caller
supplied raw SQLite offset. Forged, stale, cross-query, cross-tool, and
cross-service/restart cursors are rejected with a generic error. The cursor
secret is never logged or returned; constructing a new service invalidates old
cursors. Cursor state is capped at 2048 ASCII bytes.

The serialized domain response is capped at 12 KiB using compact ASCII JSON,
leaving headroom for a later adapter. The plan's complete 32 KiB JSON-RPC
payload limit is **not** claimed here: the MCP adapter must measure and enforce
that whole-RPC limit separately.

Errors are fixed service-domain messages and do not include raw exception text,
package paths, SQL, or document payloads. `LoadedTopicPackage` lifetime errors
are translated to a controlled `error` response. The service remains side
-effect free and leaves handle ownership with its caller.
