# Operator CLI: InfoSys ingest into a topic package

This implements the `ingest` operator command from PLAN section 10.2 for the
`infosys-mshc` format. It is not an MCP tool: agents cannot trigger imports,
and serving remains a separate read-only process over validated packages.

```text
twincat-knowledge ingest --format infosys-mshc \
  --output <new-package-dir> --language <de|en> \
  --rights-reference <operator-rights-decision-reference> \
  [--source <archive.mshc>] [--catalog-root <dir>] \
  [--library <name>]... [--source-id <id>] [--snapshot-id <id>] [--json]
```

## Source resolution

Without `--source`, the command discovers the locally installed InfoSys
through the bounded Python discovery (`ingest/infosys_discovery.py`), which
mirrors `tools/Test-InfoSys.ps1`: it scans
`%ProgramData%\Microsoft\HelpLibrary2\Catalogs\*\ContentStore\<locale>` for
`BKINFOSYS3*_<locale>*.mshc` candidates. Zero candidates or more than one
candidate fail explicitly; no revision is selected automatically. Discovery
returns candidate files, not manifest-verified active Help Viewer packages;
`installedBooks.*.xml` and registry custom locations are not parsed.
`--catalog-root` overrides the scan root; `--source` bypasses discovery.

## Pipeline and scope

The command composes the existing bounded components without weakening their
checks: the InfoSys reader (with the selected-aggregate bound raised to 1 GiB
for full-locale imports; all other reader limits unchanged), normalization
against one `SourceSnapshot`, and the topic package builder. One run imports
one archive and one language. `--library` restricts the selection; omitting it
selects every library of that language.

The source snapshot records the SHA-256 of the archive file, the import time,
and the mandatory `--rights-reference`. That reference is the operator's own
statement about the usage-rights decision; the command does not establish
vendor authenticity, licensing, or source approval. The manifest inventory
balance covers exactly the selected libraries and language of the inventoried
archive — it is never a claim about the whole archive or "all of Beckhoff".
The reader is strict: a malformed selected article fails the run instead of
being counted as skipped, so `documents_skipped`/`documents_failed` are zero
in a successful report.

## Output and exit status

- Exit 0: the package was built. Text mode prints the snapshot ID,
  topic/section/library counts, and the manifest SHA-256 required by
  `corpus validate`/`corpus activate`. `--json` emits one object with
  `schema_version: infosys-ingest-1`, `status: ok`, counts per language and
  library, the reconciled inventory, and scope limitations. Neither format
  prints document text, titles, operator paths, or raw exception details.
- Exit 1: a controlled failure (source unresolved or unreadable, over limits,
  output directory unavailable). A fixed message goes to stderr; no partial
  package is reported as success. An interrupted build can leave a new
  incomplete output directory for the operator to remove, matching the
  package builder contract.
- Exit 2: malformed usage via argparse, including a missing
  `--rights-reference`; the rights decision is never defaulted.

## Verified real run

On 2026-09-18 the command imported a real locally installed
`BKINFOSYS3_VS_100_EN-US.47.mshc` (914,953,303 bytes) end-to-end on Windows
11: 49,911 EN topics across 281 libraries, 623 MiB of normalized JSONL,
followed by `corpus validate`, `corpus activate`, `serve --transport stdio`,
and successful `tc_search`/`tc_get_topic` calls over MCP. This proves the
import path for that installation; it is not a coverage or quality
acceptance, and other InfoSys revisions still need their own runs.

## Not in this slice

Activation (`corpus activate`) stays separate. No ESI import, no DE+EN
combined package, no incremental re-ingest, no scheduled updates, and no
parsing of Help Viewer installation metadata.
