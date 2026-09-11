# Bounded topic MCP adapter

This implementation is the first read-only MCP slice, not the planned 15-tool
product. It exposes exactly these three stable tool names, in this order:

1. `tc_get_corpus_status`
2. `tc_get_topic`
3. `tc_search`

The adapter uses the installed MCP Python SDK (`mcp==2.2.0`) for stdio framing,
JSON-RPC dispatch, request metadata validation, result serialization, and
shutdown. It uses the official low-level handler registration seam only to keep
the wire catalog and discovery capabilities exact. It does not implement HTTP,
authentication, prompts, resources, subscriptions, sampling, or dynamic tool
lists.

## Contract

`create_topic_server(service)` receives an already constructed
`TopicQueryService`. The service must be caller-owned and must already represent a
validated package generation. The factory does not load, activate, refresh, or
close it. `run_topic_stdio(service)` has the same ownership rule; a launcher that
created a package handle closes that handle in its `finally` block.

Tool arguments are top-level JSON object fields. `tc_search` accepts `query`,
`kinds`, `filters`, `limit`, and `cursor`; `tc_get_topic` accepts `topic_id`,
`section_ids`, `limit`, and `cursor`; status accepts `snapshot_id`, `detail`,
`limit`, and `cursor`. Wire arrays are converted to the strict tuple-based
service contracts. Unknown fields and type coercion (including boolean `limit`)
are rejected as JSON-RPC invalid parameters. Unsupported but syntactically valid
search categories reach the service and return `not_available`; unsupported
filter fields return the service's explicit error status.

Each tool publishes the corresponding typed `ResponseEnvelope` output schema and
returns `structuredContent` matching it. The text block is intentionally a short
English summary containing the actual status, returned count, and truncation
flag; it does not duplicate document content. `not_found` and `not_available`
are ordinary, non-error tool results. Only `status="error"` produces
`isError=true`. Unexpected service failures are converted to the fixed warning
`topic service execution failed`; exception text, paths, secrets, and SQL do not
cross the MCP boundary.

All three tools advertise the four read-only annotations:
`readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, and
`openWorldHint=false`. These annotations are descriptive and are not the access
control boundary.

## Modern protocol profile

The server identity is `twincat-knowledge-topic` version `0.1.0`. Discovery
supports only MCP `2026-07-28` and includes the self-contained selection
instructions in the first 512 characters. Modern calls carry the required
protocol-version, client-info, and client-capabilities metadata in each request;
`initialize` is not needed. Discovery advertises only `tools` with
`listChanged=false`. No prompt, resource, subscription, or list-change
capability is implemented or advertised. Unsupported protocol versions return
`-32022` with the requested and supported versions. Unknown methods and malformed
requests remain protocol errors rather than tool execution results.

## Bounds and pagination

The domain service keeps its serialized envelope within 12 KiB. The adapter also
measures the complete UTF-8 JSON-RPC response, including request ID, server-info
metadata, text, and structured content, against `WIRE_RESPONSE_LIMIT` (32,768
bytes). It only emits complete service records and preserves the service's
authenticated cursor. Cursor traversal is tied to the service instance,
package generation, query/filter selection, tool, and page size; stale,
forged, cross-query, and cross-service cursors fail safely.

The 32 KiB claim applies to request IDs accepted by the MCP SDK and to ordinary
bounded protocol metadata. JSON-RPC itself does not impose a universal maximum
on an attacker-controlled request ID, so an arbitrarily huge ID can consume the
wire budget before a result is serialized. Such IDs are outside this adapter's
admitted response-budget envelope; this is a limitation, not a universal bound
claim. The contract tests measure real subprocess responses containing Unicode
and the server metadata, and exercise multiple cursor calls over real
build-and-load fixture packages.

The test fixture is local synthetic data used only to exercise the production
package builder, loader, service, and adapter. It is not Beckhoff content and
proves neither InfoSys coverage nor product readiness. A missing validated
corpus remains `not_available` while discovery and the fixed three-tool catalog
continue to work.
