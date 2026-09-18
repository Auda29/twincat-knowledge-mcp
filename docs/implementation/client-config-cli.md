# Operator CLI: host client configuration printer

This implements the `config print-client` operator command from PLAN section
10.2 for the `claude` and `codex` clients. It prints one MCP server block to
stdout; it never reads, writes, or modifies any host or agent configuration
file, and the operator adopts the block deliberately.

```text
twincat-knowledge config print-client --client <claude|codex|hermes> \
  [--config <operator-config.toml>]
```

## Behavior

- The `command` value is the absolute installed console entry point, resolved
  next to the running interpreter first and through `PATH` second. A missing
  entry point is a controlled exit 1, not a guessed path.
- The `args` value is exactly `serve --transport stdio`, plus
  `--config <absolute path>` when `--config` names an existing file. A missing
  configuration file is rejected instead of emitting a block that cannot
  start.
- `--client claude` prints the JSON `mcpServers` block used by Claude Code's
  `.mcp.json` format. `--client codex` prints the TOML `[mcp_servers."…"]`
  block used by the Codex CLI configuration. String escaping uses JSON string
  encoding, which is valid in both formats, so Windows paths survive.
- `--client hermes` fails explicitly with exit 1: that host's configuration
  schema has not been verified against its documentation, and no block is
  invented. This remains an open PLAN item.
- Exit 2 is argparse usage handling, including an omitted `--client`.

The printed block contains operator-local absolute paths by design; this is an
operator command whose output is destined for the operator's own host
configuration. It prints no secrets, tokens, document content, or rights
references. Printing a block does not verify host compatibility; the PLAN's
host-matrix live tests remain open.
