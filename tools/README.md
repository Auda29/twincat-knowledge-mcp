# Installed InfoSys read-only diagnostic

`Test-InfoSys.ps1` is a standalone diagnostic, not the finished MCP importer.
Download this one file from GitHub while signed in to the private repository.
No Python, 7-Zip, Pester, administrator rights or extra modules are needed to run it.
Target: Windows PowerShell 5.1 / PowerShell 7; synthetic archives also run on Linux.

## Windows quick start

Open PowerShell in the folder containing the downloaded file. Review the script
in a text editor. If Windows marked the download as blocked, unblock **only this
reviewed file** using Properties > Unblock. Do not change machine execution policy
or bypass an organization policy. If execution is blocked, send the error instead.

```powershell
.\Test-InfoSys.ps1
```

Default: locate a unique English Beckhoff `.mshc` candidate under
`$env:ProgramData\Microsoft\HelpLibrary2\Catalogs\*\ContentStore\EN-US`, then search
`tcplclib_tc2_mc2/1033/*.html` for the exact title `MC_MoveAbsolute` (case-insensitive).
This diagnostic discovers candidate files, **not manifest-verified active packages**.
It does not yet parse `installedBooks.*.xml` or registry custom locations. Multiple
candidates fail explicitly rather than silently choosing the highest revision.
For custom storage, specify the directory containing catalog folders with
`-CatalogRoot`, or the exact existing file with `-ArchivePath`:

```powershell
.\Test-InfoSys.ps1 -ArchivePath 'C:\ProgramData\Microsoft\HelpLibrary2\Catalogs\VisualStudio15\ContentStore\EN-US\BKINFOSYS3_VS_100_EN-US.47.mshc'
```

That path is the observed test installation, not a universally fixed filename.
Use `-Locale DE-DE` for the German package (`1031`), and `-Topic 'Overview'` for
another exact title in the same library. Other libraries are outside this probe.

## Output and privacy

The script writes **JSON to the console only**. There are no filesystem writes,
network requests, HTML/script execution, installer/Help Viewer calls or PLC access.
The default report includes package basename, archive-relative article path, title,
locale and structural counts; no article body, link targets, metadata or user path.
Review it before sharing. A parse error can contain a path or a small source fragment.

Expected status is `matched`, with `scannedArticles` and `matches`. This is NOT a
claim of semantic correctness or complete import. Exit codes: 0 matched; 2 not
found; 1 error. No generated example output is represented as a real InfoSys run.

To inspect actual extracted content locally, opt in explicitly:

```powershell
.\Test-InfoSys.ps1 -IncludeContent
```

This includes text, metadata, code blocks (`pre`/`code`), table rows/cells and links.
Line breaks from `br` are retained; block elements get newline boundaries and
adjacent table cells get tab separators in the flattened article text. Inline
spans are not split. Existing code whitespace, including blank lines, tabs and
non-breaking spaces, is preserved; XML normalizes literal CRLF to LF. This is
structural text extraction, not CSS-aware browser layout reconstruction.

JSON represents line breaks as `\n`. To display only the code blocks as actual
multiline text locally (rather than escaped JSON strings):

```powershell
$report = .\Test-InfoSys.ps1 -IncludeContent | ConvertFrom-Json
$report.matches[0].code | ForEach-Object { $_; '' }
```

Do not post this full output to GitHub or send it to a model by default: it contains
vendor documentation. The script itself never uploads anything. To save a local
report, redirect to a **new path outside the InfoSys installation**; PowerShell
redirection may overwrite an existing file, so check the destination first.

## Limits and next validation

- Uses a strict namespace-independent XHTML/XML reader. DTDs and external entity
  resolution are prohibited. Unsupported/malformed HTML fails rather than silently
  returning a partial successful report. Report the error; do not weaken the parser.
- Reads at most 1,000 selected articles, 4 MiB per article and 64 MiB declared
  uncompressed bytes. XML character count is also capped. ZIP central-directory
  parsing is not a sandbox for arbitrary untrusted huge archives; use installed
  vendor packages, not unknown downloads.
- Help-ID targets are resolved through an in-memory index built after the complete
  selected-library scan. `resolutionScope` explicitly identifies that archive prefix
  and language; cross-library/package/locale lookup and anchors remain unsupported.
  The default report adds `linkResolution` counters, without exposing link targets.
  Counters count link occurrences, not unique destinations, and sum to `linkCount`.
  With `-IncludeContent`, each link retains its original `href`/`text` and gains
  `resolution` containing status, decoded Help-ID and an array of candidate files.
  Empty link labels stay empty; target titles are separate metadata, not replacements.
  Statuses: `resolved` (one file), `not-found-in-scope` (not a global missing-link
  claim), `ambiguous` (all candidates retained, none selected), `external` (HTTP/S,
  never requested), `unsupported` (other forms), `invalid` (rejected syntax).
  Only canonical `ms-xhelp:///?Id=...` queries are resolved; extra parameters and
  fragments are marked unsupported. Percent decoding happens once, ID lookup is
  case-insensitive, and duplicate IDs within one file do not create false ambiguity.
  No URI is executed or opened. File resolution does not certify target semantics.
- No stylesheet/image rendering.
  Table spans, semantic warnings and code represented only by styled divs are not
  reconstructed. Structural counts do not prove full-fidelity extraction.
- XML metadata versions do not establish applicability to a TwinCAT build.
- No local index, snapshot, MCP server or publication of vendor content is included.
- Synthetic tests are not the real Windows/InfoSys acceptance. The user's actual
  archive must still be tested and checked against the Help Viewer article.

## Developer tests

Fixtures are original synthetic XHTML generated in Pester's temporary directory;
no Beckhoff article content or corpus is committed.

```powershell
Import-Module Pester -RequiredVersion 5.7.1
$r = Invoke-Pester ./tests/powershell -Output Detailed -PassThru
if ($r.FailedCount -or $r.Result -ne 'Passed') { exit 1 }
```

TDD evidence during creation: first real archive-to-structure test failed with
missing `Invoke-InfoSysProbe`, then passed. Discovery, unsafe-name and oversized
article tests failed before the corresponding implementation; subsequently green.
CI exercises Windows PowerShell 5.1, Windows PowerShell 7 and Linux PowerShell 7.
Only a completed green CI run establishes those platform results.
