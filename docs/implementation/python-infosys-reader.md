# Python InfoSys `.mshc` reader

## Scope

This slice provides a bounded, read-only XHTML article reader for operator-supplied
`.mshc` files. An `.mshc` is treated as a ZIP container; no member is extracted
to disk, executed, or fetched from the network. The reader does not inspect an
installed-package manifest, assert that a library is active or build-valid, or
create a SQLite catalog.

The public entry points are:

```python
from twincat_knowledge.ingest.infosys import InfoSysReader, read_infosys
```

`InfoSysReader(source, source_id=..., snapshot_id=..., limits=...)` accepts a
path, bounded in-memory bytes, or a binary stream. A path is opened directly as
a seekable file-backed ZIP source; the archive is not copied into memory. Bytes
and streams are bounded by the in-memory source limit and may be cached for
repeat reads. `read(libraries=..., language=...)` returns an immutable tuple of
`InfoSysTopic` values in archive order. Library is the first path component and
the second component is interpreted as a language directory
(`1033`/`en`/`en-us` -> `en`; `1031`/`de`/`de-de` -> `de`). The reader never
hardcodes a library name. `language="any"` is the default.

Before any member is opened or decompressed, the reader validates every central
directory name, symlink flag, and duplicate/canonical collision, then filters
for HTML/XHTML entries matching the requested library and language. Unselected
assets therefore do not consume selected-read limits and are never decompressed.

Each topic contains:

- original ZIP entry locator and an exact SHA-256 hash of the uncompressed XHTML
  bytes in a validated `SourceReference`;
- language, path-derived library, title, optional `Microsoft.Help.Id` topic ID;
- ordered immutable metadata entries (repeated names are retained);
- ordered paragraph, list, code, table, and explicitly marked warning sections;
- article/body text only, with script/style and other active elements removed;
  removed elements' tails are retained;
- code text with `br` converted to newlines and whitespace-only nodes retained;
- table rows/cells including empty and whitespace-only cells, with nested
  paragraphs and list text glued with block boundaries;
- image references and `ms-xhelp` `Id` values from article content in source
  order.

Pydantic frozen models provide JSON round-tripping through
`model_dump_json()`/`model_validate_json()`.

## Security and resource limits

`InfoSysLimits` defaults are:

| Limit | Default |
|---|---:|
| physical path archive bytes | 16 GiB |
| in-memory source bytes | 64 MiB |
| archive entries | 100,000 |
| central-directory bytes | 64 MiB |
| selected XHTML bytes per entry | 8 MiB |
| selected XHTML bytes across entries | 256 MiB |
| XML element depth | 128 |

The path archive limit is a file-size check and does not allocate an archive-sized
buffer. The in-memory source limit applies separately to bytes and streams.
The central-directory size is checked from the ZIP end record before `ZipFile`
reads that directory. Selected entry and aggregate limits are checked before
and during decompression. The old `max_source_bytes`, `max_entry_bytes`, and
`max_aggregate_bytes` keyword names remain compatibility aliases for the
in-memory or selected-read limits; they do not turn a path into an in-memory
source.

Directories are validated but not opened as files. Absolute paths, traversal,
control characters, encoded traversal, URI/drive paths, backslashes, ADS-like
segments, Windows device names, duplicate/case-colliding names, and symlinks
are rejected. XHTML is parsed with `defusedxml` with DTD, entity, and external
reference processing forbidden. The parser enforces the XML nesting limit while
building the tree.

## TDD and verification record

The corrected regression tests were written first and observed failing before
implementation:

- a sparse path archive larger than the in-memory budget with an oversized,
unselected asset;
- article-only extraction with script/style removal, tail preservation, list
text, table-cell paragraphs, and explicit warning semantics;
- central-directory bounds checked before `ZipFile` consumes the directory.

All commands below used the shared build lock and a temporary directory outside
`/tmp`:

```text
TMPDIR=/home/hermes/workspace/.hermes/experiments/twincat-python-tmp \
  flock /home/hermes/workspace/.hermes/twincat-build.lock uv run pytest tests -q
# 57 passed in 4.45s (CPython 3.12.13; normal pytest import mode)

TMPDIR=/home/hermes/workspace/.hermes/experiments/twincat-python-tmp \
  flock /home/hermes/workspace/.hermes/twincat-build.lock uv run ruff check \
  src/twincat_knowledge/ingest tests/unit/test_infosys_reader.py \
  tests/security/test_infosys_reader_security.py
# All checks passed!

TMPDIR=/home/hermes/workspace/.hermes/experiments/twincat-python-tmp \
  flock /home/hermes/workspace/.hermes/twincat-build.lock uv run mypy \
  src/twincat_knowledge/ingest
# Success: no issues found in 2 source files
```

The security test basename collision was introduced by the earlier reader-test
slice, not pre-existing repository state. The parent renamed the security file
to `test_infosys_reader_security.py`; normal full pytest now runs without an
`--import-mode` override. The full suite proves the synthetic and repository
tests only; it is not acceptance of a real vendor InfoSys corpus.

No vendor corpus or vendor text was added. No coordinator dependency, CLI, or
CI file was changed.
