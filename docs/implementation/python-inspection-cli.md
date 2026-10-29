# Python reader CLI inspection

This is a reader integration checkpoint, **not** the completed corpus importer.
`inspect-infosys` runs the Python reader from the installed package and prints
metadata-only JSON. It never writes an index, opens links, uploads documentation,
or changes the installed InfoSys source. No administrator rights are needed.

## Install a CI build

The private Foundation CI run provides `software-<os>-py<version>-<sha>` artifacts
containing a wheel, source archive and `SHA256SUMS.txt`. These are seven-day CI
builds, not releases. Review the run's exact commit and green test status. Download
while signed in, unpack outside the InfoSys installation and verify the wheel's
SHA-256 against the manifest. Python 3.12 or 3.13 is required.

Install the wheel in an isolated tool environment, for example:

```powershell
uv tool install --python 3.12 .\twincat_knowledge-0.1.1-py3-none-any.whl
```

Dependency installation needs registry access; the inspection itself does not.
Do not overwrite an existing tool installation blindly; test builds can instead
be installed into a dedicated Python virtual environment.

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

## Verification and open gates

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
