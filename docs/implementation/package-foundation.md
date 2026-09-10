# Package foundation

This worktree implements only the data-source-neutral packaging and CLI base.
It deliberately does not import Beckhoff/TwinCAT libraries, read a corpus, or
register an MCP server. `serve` is not an advertised command until a real
server implementation exists.

## Commands

```text
twincat-knowledge --version
twincat-knowledge init --config <config.toml>
twincat-knowledge doctor --config <config.toml> [--json]
```

`init` creates a small TOML configuration atomically. Existing regular files,
directories, and symlinks are never replaced. `doctor` emits only statuses and
generic details: it checks Python support, the exact `mcp==2.2.0` distribution,
SQLite FTS5, and whether the configured corpus directory exists. It never
serializes the TOML document, secret values, or configured paths.

## Development

The project requires Python 3.12 or newer. Development dependencies are in
the `dev` dependency group and the exact dependency graph is locked in
`uv.lock`.

```text
uv sync --frozen --dev
uv run pytest tests/unit/test_config.py tests/e2e/test_installation.py -v
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

The wheel test serializes build and installation through
`/home/hermes/workspace/.hermes/twincat-build.lock`, builds a PEP 517 wheel,
installs it into a fresh non-editable Python 3.13 environment, and invokes
`python -m twincat_knowledge --version` from an unrelated working directory
with `PYTHONPATH` removed.

The checks performed here are Linux checks. They do not constitute Windows
acceptance, MCP protocol compliance, corpus coverage, or a real Beckhoff data
source validation.
