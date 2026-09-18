# TwinCAT Knowledge MCP

A local, read-only knowledge interface for Beckhoff and TwinCAT documentation. It gives agents access to a validated topic package without requiring a TwinCAT installation, a PLC connection, or access to an engineering project.

**Status: working development implementation, not a production release.** The repository contains an installable Python CLI, a four-tool MCP server over stdio, an operator `ingest` command for locally installed InfoSys archives, and the topic ingestion, package validation, snapshot, search, and hierarchy components. The larger tool catalog in the implementation plan is not yet available.

No Beckhoff documentation or ready-to-use knowledge corpus is bundled. You must supply local source material that you are authorized to process and an approved topic package before the server can answer documentation queries.

## What is available

| Component | Current implementation |
| --- | --- |
| Source inspection | Read selected local InfoSys content and report metadata; inspection does not import or activate a corpus. |
| InfoSys ingest | Operator CLI that discovers a locally installed InfoSys `.mshc` archive (or takes an explicit path) and builds a validated topic package from selected libraries and one language. |
| Topic pipeline | Python APIs for reading and normalizing topics, exporting JSONL, building a SQLite/FTS5 index, and assembling topic packages. |
| Package integrity | Validate the package manifest, artifact hashes, and topic consistency against an operator-supplied manifest SHA-256. |
| Snapshot management | Operator CLI commands to activate a package, inspect the selected snapshot state, and roll back to the stored previous snapshot. |
| Query service | Topic retrieval, full-text search, bounded responses, and cursor-based pagination. |
| Hierarchy | Extraction, graph validation, and domain-level topic browsing, exposed as the `tc_browse_topics` MCP tool. |
| MCP server | A fixed catalog of four read-only tools over stdio. |

### Available MCP tools

| Tool | Purpose |
| --- | --- |
| `tc_browse_topics` | Browse content-tree roots or one level of children with breadcrumbs. |
| `tc_get_corpus_status` | Report the selected corpus's availability and coverage within the implemented topic scope. |
| `tc_get_topic` | Retrieve a topic or selected sections by identifier. |
| `tc_search` | Search the loaded topic package. Unsupported knowledge categories are not implemented. |

The adapter uses the pinned MCP Python SDK `mcp==2.2.0` and the MCP `2026-07-28` protocol profile. Client compatibility must be checked against that profile; compatibility with every MCP host is not claimed. See the [adapter contract](docs/implementation/topic-mcp-adapter.md) for schemas, protocol metadata, response limits, and SDK coupling.

## Install from source

Requirements:

- Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Python 3.12 or newer. CI explicitly tests Python **3.12.10** and **3.13.12** on Ubuntu 24.04 and Windows Server 2022.
- SQLite with FTS5 support in the selected Python runtime.
- Repository access if the repository is private.

The following creates a local development environment using the checked-in dependency lock:

```sh
git clone https://github.com/Auda29/twincat-knowledge-mcp.git
cd twincat-knowledge-mcp
uv sync --frozen --dev --python 3.12.10
uv run --frozen twincat-knowledge --version
uv run --frozen twincat-knowledge --help
```

The distribution and console command are named `twincat-knowledge`; the Python import package is `twincat_knowledge`. These instructions install from the checkout and do not assume a published PyPI release.

## Start the MCP server

From the checkout:

```sh
uv run --frozen twincat-knowledge serve --transport stdio
```

This is a protocol process, not an interactive chat or an HTTP endpoint. A compatible MCP client must launch it and exchange JSON-RPC messages through stdin/stdout. Without configured snapshot paths, tool discovery works, but knowledge calls report `not_available`. No corpus is downloaded or created. Existing `TCK_STATE_DIR` or `TCK_CACHE_DIR` environment variables still apply; unset them if you want an unconfigured first start.

For client launch settings, use the absolute path to the installed console entry point:

- Linux: `/absolute/path/to/twincat-knowledge-mcp/.venv/bin/twincat-knowledge`
- Windows: `C:\absolute\path\to\twincat-knowledge-mcp\.venv\Scripts\twincat-knowledge.exe`

Pass `serve`, `--transport`, and `stdio` as separate arguments. For a configured corpus, also pass `--config` and the absolute path to your TOML file. Client-specific configuration formats vary.

The server loads and pins the selected package at startup. After activation or rollback, restart the server to load the new selection. See [stdio serving](docs/implementation/stdio-serving-cli.md) for startup behavior and failure conditions.

## Configure and select a topic package

### 1. Create an operator configuration

```sh
uv run --frozen twincat-knowledge init --config ./config.toml
```

`init` refuses to overwrite an existing file. Edit its snapshot paths, for example:

```toml
[paths]
state = "./state"
cache = "./cache"
```

Create both directories yourself before using them. Keep the state and private cache directories outside the topic package directory. Relative TOML paths resolve against the configuration file's directory. `init` does not create these directories.

Snapshot path precedence is explicit CLI flags, then `TCK_STATE_DIR` / `TCK_CACHE_DIR`, then TOML. The legacy `paths.corpus` setting is not a fallback for snapshot selection.

### 2. Build a package from your local InfoSys installation

A topic package contains `manifest.json`, `topics.jsonl`, and `topics.sqlite`. It is distinct from the Python software wheel or source archive.

If the official Beckhoff offline documentation (`TC3-InfoSys.exe`) is installed locally, `ingest` discovers its Help Library archive and builds a package:

```sh
uv run --frozen twincat-knowledge ingest --format infosys-mshc --language en --output "PATH_TO_NEW_PACKAGE_DIR" --rights-reference "YOUR_RIGHTS_DECISION_REFERENCE" --json
```

Use `--source` for an explicit `.mshc` path, `--library` (repeatable) to restrict the selection, and `--catalog-root` for a custom Help Library location. One run imports one archive and one language; the report prints the manifest SHA-256 needed below. The mandatory `--rights-reference` records your own usage-rights decision; it does not establish vendor authenticity, licensing, or source approval. See the [ingest contract](docs/implementation/infosys-ingest-cli.md).

If you prepare packages elsewhere, obtain the expected SHA-256 of `manifest.json` through your trusted package preparation process. A hash checks integrity; it does not establish vendor authenticity, licensing, or source approval. The `inspect-infosys` command remains metadata-only and cannot create a package for serving.

### 3. Validate, activate, and serve

Replace `PATH_TO_PACKAGE` and `EXPECTED_MANIFEST_SHA256` below with your package directory and its expected 64-character lowercase hexadecimal manifest hash. These examples assume `config.toml`, `state`, and `cache` are in the repository root; run the commands there:

```sh
uv run --frozen twincat-knowledge corpus validate "PATH_TO_PACKAGE" --expected-manifest-sha256 "EXPECTED_MANIFEST_SHA256" --cache-dir ./cache --json
uv run --frozen twincat-knowledge corpus activate "PATH_TO_PACKAGE" --expected-manifest-sha256 "EXPECTED_MANIFEST_SHA256" --config ./config.toml --json
uv run --frozen twincat-knowledge corpus list --config ./config.toml --json
uv run --frozen twincat-knowledge serve --transport stdio --config ./config.toml
```

`corpus list` reports stored snapshot references, not a fresh package validation or a full readiness check. To restore a previously activated snapshot:

```sh
uv run --frozen twincat-knowledge corpus rollback --config ./config.toml --json
```

Rollback requires a stored previous selection; it does not choose an arbitrary package. The separate `doctor --config ./config.toml --json` command checks the runtime and legacy corpus configuration. A `not_ready` result is not, by itself, a failure of stdio discovery or proof that snapshot activation failed. See the [snapshot CLI](docs/implementation/snapshot-cli.md) and [validation CLI](docs/implementation/corpus-validation-cli.md) for the exact contracts.

## Development and verification

Run from the repository root after installing the locked development dependencies:

```sh
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen mypy
uv pip check
uv run --frozen python -m pytest -q tests
uv build
```

The suite includes synthetic source and package fixtures, security regressions, real wheel and sdist installation in fresh environments, execution outside the source checkout, and stdio/snapshot lifecycle tests. Native CI runs the Python matrix on Linux and Windows, plus the PowerShell InfoSys probe tests. Passing synthetic tests does not establish real InfoSys coverage or full-product readiness.

Normal push/PR CI builds and verifies the software without uploading artifacts. Explicit package upload is opt-in through `workflow_dispatch` with `upload_packages: true` and remains subject to storage quota. CI runner minutes are a separate limit. See [merge policy](docs/MERGE_POLICY.md).

## Not implemented

- The full planned tool catalog, including symbol, library, device, error, example, and relationship tools.
- Streamable HTTP, remote authentication, and host-specific deployment support.
- Semantic search or a ready-to-use licensed corpus.
- A universal response-size guarantee for every SDK-generated protocol error or arbitrary request metadata.

These are roadmap items or documented limitations, not features enabled by configuration. See the [implementation plan](docs/PLAN.md) and [current status](docs/STATUS.md).

## Safety, content rights, and licensing

MCP tools are read-only. They do not control PLCs, open ADS connections, modify engineering projects, or execute code from retrieved content. Package activation and rollback are separate operator commands that change local snapshot state; they are not agent tools.

Only process sources you are entitled to use. Beckhoff documentation is not redistributed with this repository. Source acquisition, indexing, and use rights must be resolved before ingestion. Package checksums do not replace those decisions.

This is an independent project, not an official Beckhoff product. A software license and any public release remain undecided; do not assume an open-source license grant merely because you can access the repository.

## Documentation

Some project-planning and historical status documents are still in German. Component documentation records earlier review stages; use the current status and merge policy for the integration outcome and current gates.

- [Current status and verification evidence](docs/STATUS.md)
- [Merge policy](docs/MERGE_POLICY.md)
- [Implementation plan and planned tool contracts](docs/PLAN.md)
- [Primary sources](docs/SOURCES.md)
- [MCP adapter contract](docs/implementation/topic-mcp-adapter.md)
- [Stdio serving and client launch behavior](docs/implementation/stdio-serving-cli.md)
- [Snapshot activation, listing, and rollback](docs/implementation/snapshot-cli.md)
- [Topic package construction](docs/implementation/topic-package-build.md)
