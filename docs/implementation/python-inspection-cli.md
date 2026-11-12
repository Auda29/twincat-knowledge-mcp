# Python reader CLI inspection

Published `0.1.2` includes both the metadata-only reader command below and the
separate [ingest command](infosys-ingest-cli.md). The verification section at the
end records an earlier reader checkpoint; its open gates are historical and do
not supersede [current status](../STATUS.md).

`inspect-infosys` runs the Python reader from the installed package and prints
metadata-only JSON. It never writes an index, opens links, uploads documentation,
or changes the installed InfoSys source. No administrator rights are needed.

## Install published software

Follow [published 0.1.2 setup](../setup.md) to download and verify the GitHub
Release wheel, hash-pinned runtime requirements, schemas and source receipt.
Install into a separate environment outside the InfoSys installation. Python
3.12 or newer with SQLite FTS5 is required; CI covers 3.12.10 and 3.13.12.

The ordinary version is `0.1.2`, not the dated private development candidate.
Optional seven-day CI artifacts are distinct from release assets and require
an explicit upload-enabled workflow run; normal CI does not provide them.

Dependency installation needs a registry or prepared wheelhouse; inspection
itself uses only the explicitly selected local source. Invoke the installed
console path, or activate that isolated environment for the command below.

## Test the observed installation

```powershell
twincat-knowledge inspect-infosys --source 'C:\ProgramData\Microsoft\HelpLibrary2\Catalogs\VisualStudio15\ContentStore\EN-US\BKINFOSYS3_VS_100_EN-US.47.mshc' --library tcplclib_tc2_mc2 --language en --title MC_MoveAbsolute
```

The source path is the observed user's installation, not a universal default.
`--source`, at least one `--library`, and `--language en|de` are required.
`--library` accepts the archive's first path component and can be repeated;
matching is exact. `--title` is optional and matches case-insensitively, without
silently substituting a different article. At most 20 topic summaries are emitted;
`total` counts matching topics and `truncated` explicitly reports omitted results.

Output contains archive-relative locators, raw article SHA-256, titles, library,
language and section/link counts. It does not contain article bodies, code,
full metadata, link targets or absolute source paths. Review before sharing.
Exit codes: 0 = topics found, 2 = no matching topics, 1 = reader failure. No partial
success is returned after a reader failure. Generic errors deliberately suppress
source details. Limits and supported XHTML are documented in
[python-infosys-reader.md](python-infosys-reader.md).

## Historical reader-checkpoint verification and open gates

The following evidence and then-open scope are retained from the initial reader
integration. Current topic ingestion, indexing and MCP availability are listed
in the documentation index and status; this evidence alone accepts neither the
published typed extraction nor a new real-document sample.

- Parent observed the command missing (RED), implemented the minimal command,
  then repeated for exact-title filtering (RED -> GREEN).
- Normal full suite: 60 passed on Linux Python 3.12.13 and 3.13.12.
- Installed wheel **and source-archive** E2E run this command from a foreign working
  directory with synthetic ZIP input. The checkout is not used by the installed
  console command.
- Windows CI, independent reader review and actual Python/InfoSys run are separate
  gates; their completion is not implied by these Linux results.
- Active package selection from the catalog manifest, persistent normalized
  corpus, SQLite/FTS, complete Help-ID resolution, and MCP remain unimplemented.
  The earlier PowerShell corpus test is not a Python reader acceptance.
