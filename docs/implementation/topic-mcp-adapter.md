# Bounded topic MCP adapter

This implementation is the first read-only MCP slice, not the planned 15-tool
product. It exposes exactly these four stable tool names, in this order:

1. `tc_browse_topics`
2. `tc_get_corpus_status`
3. `tc_get_topic`
4. `tc_search`

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
`section_ids`, `limit`, and `cursor`; `tc_browse_topics` accepts
`parent_topic_id`, `filters`, `limit`, and `cursor`; status accepts
`snapshot_id`, `detail`, `limit`, and `cursor`. Wire arrays are converted to the strict tuple-based
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
cross the MCP boundary. Each service call has its own ordinary-exception boundary,
so even a service-raised adapter-private protocol error is translated before
protocol dispatch sees it. Cancellation (`BaseException`) still propagates.
This is error-data hygiene, not a sandbox against arbitrary in-process code.

All four tools advertise the four read-only annotations:
`readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, and
`openWorldHint=false`. These annotations are descriptive and are not the access
control boundary.

## Modern protocol profile

The server identity is `twincat-knowledge-topic` version `0.1.1`. Discovery
supports only MCP `2026-07-28` and includes the self-contained selection
instructions in the first 512 characters. Modern calls carry the required
protocol-version, client-info, and client-capabilities metadata in each request;
`initialize` is not needed. Discovery advertises only `tools` with
`listChanged=false`. No prompt, resource, subscription, or list-change
capability is implemented or advertised. Unsupported protocol versions return
`-32022` with the requested and supported versions. Unknown methods and malformed
requests remain protocol errors rather than tool execution results.

## Bounds and pagination

The domain service keeps its serialized envelope within 12 KiB. For adapter-generated
successful tool results and fixed-size fallback results, the adapter measures the
complete UTF-8 JSON-RPC response, including request ID, server-info metadata, text,
and structured content, against `WIRE_RESPONSE_LIMIT` (32,768 bytes). It only emits
complete service records and preserves the service's authenticated cursor. Cursor
traversal is tied to the service instance, package generation, query/filter
selection, tool, and page size; stale, forged, cross-query, and cross-service
cursors fail safely.

This is not a universal 32 KiB bound for every JSON-RPC response. SDK-generated
protocol-error envelopes are outside the adapter's measurement boundary: for
example, an unsupported protocol version is echoed in the SDK's `-32022` error data.
A 40,000-character unsupported version therefore produces an oversized protocol
error under the locked SDK. JSON-RPC also does not impose a universal maximum on an
attacker-controlled request ID. A very large valid ID can make even the adapter's
fixed fallback response exceed the budget before serialization. The contract tests
exercise both cases and record them as current budget exceptions, not as accepted
normal-operation payloads. The adapter does not silently constrain these valid
protocol fields.

The 32 KiB claim is consequently limited to adapter-generated tool-result paths for
bounded SDK-admitted metadata. It does not claim a universal maximum for SDK
protocol errors, arbitrary request IDs, or all protocol metadata. The contract tests
measure real subprocess responses containing Unicode and server metadata, and
exercise multiple cursor calls over real build-and-load fixture packages.

The test fixture is local synthetic data used only to exercise the production
package builder, loader, service, and adapter. It is not Beckhoff content and
proves neither InfoSys coverage nor product readiness. A missing validated corpus
remains `not_available` while discovery and the fixed four-tool catalog continue
to work.

## SDK coupling and upgrade gate

The wire adapter is pinned to `mcp==2.2.0` in `pyproject.toml` and `uv.lock`, with
matching `mcp-types==2.2.0` resolved by the lock. Stdio framing, JSON-RPC dispatch,
and protocol validation remain SDK-owned; this project does not add a transport.
The exact-wire catalog currently depends on these SDK internals:

- `MCPServer._lowlevel_server` to reach the low-level server owned by the public
  `MCPServer` instance;
- low-level `Server._request_handlers` to remove default handlers that this
  fixed-capability adapter must not advertise;
- low-level `server_info_stamp` to put the SDK's server identity/version stamp in
  each adapter-generated result;
- the adapter-local `MCPServer._topic_tools` attribute for the fixed in-process
  catalog used by contract tests.

These are private instance attributes, not a public compatibility contract. Any
upgrade of `mcp` or `mcp-types` must first pass a compatibility gate that inspects
those attributes and reruns discovery, list, call, strict-schema, error-boundary,
wire-budget, and EOF tests on Python 3.12 and 3.13. The pin must not be loosened
until that gate passes; a public `MCPServer.list_tools()`/`call_tool()` success is
not sufficient evidence because the public in-process API is separate from the
strict manually published wire schemas and does not provide the wire server-info
metadata in the same way.

## Acceptance status

This document describes the implemented four-tool slice only. The mandatory
acceptance criteria in `docs/PLAN.md` remain **OPEN**: in particular, this slice
is not the planned 15-tool product and these adapter tests do not establish real
InfoSys coverage, Streamable HTTP, host compatibility, or full product acceptance.
Documentation of a limitation does not waive a PLAN gate.
