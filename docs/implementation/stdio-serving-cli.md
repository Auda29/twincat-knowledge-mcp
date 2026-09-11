# stdio serving CLI

`twincat-knowledge serve --transport stdio` is the operator entry point for the
read-only topic MCP server. `stdio` is the only transport accepted and is the
default, so `serve` is equivalent to `serve --transport stdio`.

## Configuration and first start

The optional `--config`, `--state-dir`, and `--cache-dir` values use the same
priority as snapshot commands: explicit flags, `TCK_STATE_DIR` /
`TCK_CACHE_DIR`, then `[paths].state` / `[paths].cache` in TOML. Relative TOML
paths are anchored to the config file. Empty TOML placeholders are unset.
Configuration files are bounded regular UTF-8 TOML files; malformed files,
unsafe file types, invalid values, and invalid selected paths fail closed.

With no selected state or cache path, the server starts with
`TopicQueryService(None)`. Discovery and the three topic tools remain available,
while knowledge calls report `not_available`. A valid config containing no
snapshot paths has the same behavior. The command never creates configuration,
state, cache, locks, package files, or downloads.

A selected state directory must already exist. If it has no `active.json`, it
may start without a cache for discovery-only use. A cache without state, or a
state directory with no active selection plus a configured cache, is rejected as
ambiguous partial configuration. An active selection requires a configured,
existing external cache. The selected package is verified and loaded once
before the stdio loop; the loaded package stays pinned for that process and is
closed on EOF, runtime failure, or interruption. Activation and reload are
operator operations performed by a later process.

## Protocol behavior

The MCP SDK owns UTF-8 JSON-RPC framing. Standard output contains only JSON-RPC
messages; startup and launch failures use the fixed stderr message `serve
startup failed`. Help and argparse usage are ordinary CLI output before the
active protocol starts. No package paths, source paths, configuration values,
or secrets are printed.

The current adapter exposes exactly these three read-only tools:

- `tc_get_corpus_status`
- `tc_get_topic`
- `tc_search`

Modern clients can call `server/discover`, `tools/list`, and `tools/call`
without an `initialize` handshake.
