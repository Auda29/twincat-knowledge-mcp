# Python InfoSys `.mshc` reader

## Scope

This slice adds a bounded, read-only XHTML article reader for operator-supplied
`.mshc` files. An `.mshc` is treated as a ZIP container; no member is extracted
to disk, executed, or fetched from the network. The reader does not inspect an
installed-package manifest, assert that a library is active or build-valid, or
create a SQLite catalog.

The public entry points are:

```python
from twincat_knowledge.ingest.infosys import InfoSysReader, read_infosys
```

`InfoSysReader(source, source_id=..., snapshot_id=..., limits=...)` accepts a
path, bytes, or a binary stream. `read(libraries=..., language=...)` returns an
immutable tuple of `InfoSysTopic` values in archive order. Library is the first
path component and the second component is interpreted as a language directory
(`1033`/`en`/`en-us` → `en`; `1031`/`de`/`de-de` → `de`). The reader never
hardcodes a library name. `language="any"` is the default.

Each topic contains:

- original ZIP entry locator and an exact SHA-256 hash of the uncompressed XHTML
  bytes in a validated `SourceReference`;
- language, path-derived library, title, optional `Microsoft.Help.Id` topic ID;
- ordered immutable metadata entries (repeated names are retained);
- ordered paragraph, code, table, and explicitly marked warning sections;
- code text with `br` converted to newlines and whitespace-only nodes retained;
- table rows/cells including empty and whitespace-only cells;
- image/object/embed references and `ms-xhelp` `Id` values in source order.

Pydantic frozen models provide JSON round-tripping through
`model_dump_json()`/`model_validate_json()`. Reader source bytes are cached after
the first successful read, so repeated reads from a stream are deterministic.

## Security and resource limits

`InfoSysLimits` defaults are:

| Limit | Default |
|---|---:|
| source bytes read | 64 MiB |
| archive entries | 10,000 |
| decompressed bytes per entry | 8 MiB |
| decompressed bytes across entries | 256 MiB |
| XML element depth | 128 |

The source and every ZIP member are read incrementally with a bounded reader;
`ZipInfo.file_size` is checked before decompression and actual bytes are
counted while reading. Declared and actual aggregate sizes are enforced.
Directories are validated but not opened as files. Absolute paths, traversal,
control characters, encoded traversal, URI/drive paths, backslashes, ADS-like
segments, Windows device names, duplicate/case-colliding names, and symlinks are
rejected. XHTML is parsed with `defusedxml` with DTD, entity, and external
reference processing forbidden. The parser enforces the XML nesting limit while
building the tree.

## TDD and verification record

The first vertical test was written before production code and run as RED:

```text
uv run pytest tests/unit/test_infosys_reader.py::test_reader_returns_topic_with_locator_library_language_and_hash -v
```

It failed during collection with `ModuleNotFoundError: No module named
`twincat_knowledge.ingest`` (exit 4). The minimal reader slice then made the
same test GREEN (`1 passed`). Subsequent structure and security tests were added
as vertical slices and the focused suites were rerun after each correction.

Commands and observed results in this worktree:

```text
uv sync --frozen --dev --python 3.12
# exit 0; CPython 3.12.13 environment created/updated

uv run pytest tests/security/test_infosys_reader.py -q
# 6 passed

uv run pytest tests/unit/test_infosys_reader.py -q
# 6 passed

uv run pytest --import-mode=importlib tests/unit tests/security -q
# 52 passed

uv run ruff format src/twincat_knowledge/ingest tests/unit/test_infosys_reader.py tests/security/test_infosys_reader.py
# exit 0

uv run ruff check src/twincat_knowledge/ingest tests/unit/test_infosys_reader.py tests/security/test_infosys_reader.py
# All checks passed!

uv run mypy src/twincat_knowledge/ingest
# Success: no issues found in 2 source files
```

A full `uv run pytest --import-mode=importlib tests -q` run reached 51 passing
tests but the two pre-existing wheel-installation tests failed while uv was
downloading `mcp==2.2.0`: `/tmp` reported `No space left on device`. This is an
environment capacity failure, not a reader assertion failure. Running both new
test files in one default-mode pytest command also hits pytest's pre-existing
same-basename import collision (`tests/unit/test_infosys_reader.py` versus
`tests/security/test_infosys_reader.py`); `--import-mode=importlib` avoids it.

No vendor corpus or vendor text was added.
