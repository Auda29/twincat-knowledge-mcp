# stdio serving CLI

`twincat-knowledge serve --transport stdio` is the operator entry point for the
read-only nine-tool MCP server in published software `0.1.2`. `stdio` is the only transport accepted and is the
default, so `serve` is equivalent to `serve --transport stdio`.

## Configuration and first start

The optional `--config`, `--state-dir`, and `--cache-dir` values use the same
priority as snapshot commands: explicit flags, `TCK_STATE_DIR` /
`TCK_CACHE_DIR`, then `[paths].state` / `[paths].cache` in TOML. Relative TOML
paths are anchored to the config file. Empty TOML placeholders are unset.
Configuration files are bounded regular UTF-8 TOML files; malformed files,
unsafe file types, invalid values, and invalid selected paths fail closed. An
explicitly supplied missing config file also fails closed, even when flags
provide both selected paths. Omitted `--config` means unconfigured; it is not
an instruction to ignore a path that was supplied. Empty explicit serve path
values are invalid and are checked before path normalization.

With no selected state or cache path, the server starts with
`TopicQueryService(None)`. Discovery lists all nine tools,
while knowledge calls report `not_available`. A valid config containing no
snapshot paths has the same behavior. The command never creates configuration,
state, cache, locks, package files, or downloads.

A selected state directory must already exist. If it has no `active.json`, it
may start without a cache for discovery-only use. It also starts with a
configured, existing valid cache and reports `not_available`; this is the
normal configured first-run state. A missing state directory, corrupt pointer,
wrong package pin, missing package, or invalid cache fails closed before MCP
protocol output and does not write state or cache files. An active selection
requires a configured, existing external cache. The selected package is
verified and loaded once before the stdio loop; the loaded package stays pinned
for that process and is closed on EOF, runtime failure, or interruption.
Activation and reload are operator operations performed by a later process.

Typed extraction is deferred until the first typed query and cached within that
validated generation. Startup still verifies and loads the selected topic
package. This deferral is not evidence that large-corpus cold-start, first-query
latency or memory targets have been met. See [published setup and acceptance](../setup.md).

## Protocol behavior

The MCP SDK owns UTF-8 JSON-RPC framing. Standard output contains only JSON-RPC
messages; startup and launch failures use the fixed stderr message `serve
startup failed`. Help and argparse usage are ordinary CLI output before the
active protocol starts. No package paths, source paths, configuration values,
or secrets are printed.

The current adapter exposes exactly these nine read-only tools:

- `tc_browse_topics`
- `tc_get_corpus_status`
- `tc_get_topic`
- `tc_search`
- `tc_find_symbols`
- `tc_get_symbol`
- `tc_find_libraries`
- `tc_get_library`
- `tc_lookup_error`

The [typed contracts](typed-entities.md) define the five additive tools and their
supported extraction grammar. Missing typed coverage, version/namespace/domain
ambiguity and source references are retained. Documented metadata cannot
establish locally installed libraries or live editor/compiled PLC state.

Modern clients can call `server/discover`, `tools/list`, and `tools/call`
without an `initialize` handshake.
