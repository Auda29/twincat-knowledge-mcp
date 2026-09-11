# Bounded topic query service

`twincat_knowledge.services.TopicQueryService` is the domain retrieval service for
one caller-owned `LoadedTopicPackage`. It is not an MCP server or transport
adapter. The caller supplies either a validated loaded handle or `None`; the
service never loads, reloads, activates, or closes that handle.

## Contracts

`SearchInput`, `GetTopicInput`, and `CorpusStatusInput` are frozen, strict
Pydantic models with forbidden extra fields. Their responses are typed
`ResponseEnvelope` models with `schema_version`, `status`, `snapshot_ids`,
`data`, `sources`, `warnings`, `truncated`, and `next_cursor`. Search currently
implements only `topics`; absent topic data and all other categories return
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

Supported filters are `snapshot_id` (package snapshot or an indexed source
snapshot) and language `de`, `en`, or `any`. `library_id`, `product_family`,
`documented_version`, and `device_revision` are rejected explicitly. The topic
model's raw `library` string is not promoted to a library entity.

`get_topic` performs exact ID lookup only. It preserves source order and returns
whole paragraph, code, table, and warning sections. Explicit section selection
is source-ordered, and unknown section IDs are an error. Pagination stops only
between records; code and warning payloads are never cut. A section or metadata
record that cannot fit is reported as an explicit oversized-content error.
The first implementation does not segment oversized individual sections; that
is a known follow-up limitation and is not represented as a complete response.

Corpus status is projected only from the validated manifest and immutable
summary. It reports package/source identity, actual topic/section/language
counts, the lexical search mode, topic as the only implemented category, and a
safe paginated source inventory. It omits rights references, local paths,
secrets, and unsupported entity-count claims.

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
