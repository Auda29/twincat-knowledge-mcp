# InfoSys XML review fixes

This slice fixes the two XML findings from the independent reader review. It is
limited to XML selection and section extraction in
`src/twincat_knowledge/ingest/infosys.py`; archive, path, and API identity code
are unchanged.

## Active-content selection

Article, body, title, and metadata discovery now traverses only safe elements.
An article nested below `script`, `style`, `object`, or another active element
cannot become the content root. The same safe traversal prevents active
`meta`, `title`, image, and `ms-xhelp` link elements from being retained. The
inline renderer and ordinary-text traversal continue to retain the tail of an
active element when that tail is part of safe content.

## Ordinary article text

Section extraction now walks safe content in document order. Direct text in
`article`, `div`, `span`, `blockquote`, `dl`, `dt`, and `dd`, including tails,
is emitted as paragraph sections exactly once. Block wrapper boundaries keep
separate ordinary blocks separate; nested selected paragraphs and structured
`code`, `table`, and `warning` sections are emitted once and their descendants
are not emitted again as fallback paragraphs. Existing code/table/warning
payload behavior remains typed.

## TDD and verification record

The two new regression tests were written before the production change and
both failed against the old implementation:

```text
pytest tests/unit/test_infosys_xml_regressions.py -q
2 failed in 0.21s
```

After the XML-only fix:

```text
pytest tests/unit/test_infosys_xml_regressions.py -q
2 passed in 0.08s

pytest tests/unit/test_infosys_reader.py \
  tests/security/test_infosys_reader_security.py \
  tests/unit/test_infosys_xml_regressions.py -q
17 passed in 0.10s

pytest tests -q
62 passed in 4.29s

ruff check src/twincat_knowledge/ingest/infosys.py \
  tests/unit/test_infosys_reader.py \
  tests/security/test_infosys_reader_security.py \
  tests/unit/test_infosys_xml_regressions.py
All checks passed!

mypy src/twincat_knowledge/ingest
Success: no issues found in 2 source files
```

All commands used the shared build lock and
`TMPDIR=/home/hermes/workspace/.hermes/experiments/twincat-python-tmp` with
`uv run --frozen --python 3.12 --dev`. Tests use synthetic XHTML only and pass
explicit `source_id="synthetic"` and `snapshot_id="fixture-1"`; no vendor
corpus or network access was used.

## Limitations

This remains the intentionally bounded synthetic/operator-supplied InfoSys
reader. It does not add manifest/index/SQLite/MCP functionality, and this slice
does not change archive safety, path handling, decompression error handling, or
source/snapshot identity defaults.


## Coordinator integration follow-up

The worker commit was cherry-picked onto the ZIP/identity fixes. The normal
combined suite first passed 71 tests. Coordinator inspection then identified
three additional edge cases, each reproduced with a failing regression before
its fix:

- An active document root leaked its own direct text through fallback extraction.
  Traversal now checks root membership in the safe set as well as descendants.
- The initial wrapper fallback still dropped `strong`, `em`, `a`, `br`, and
  `section` content. Safe inline text and tails are now retained generically;
  explicit breaks and section boundaries are preserved. One old test expected
  link labels to be silently dropped; its assertion was strengthened to require
  the previously missing `onetwo` text as an additional paragraph. All original
  code/table/warning assertions remain.
- A document without a body exposed head/title content as article text. Head,
  title and meta nodes are excluded from section traversal while safe metadata
  and title extraction remain available.

Each focused regression failed first, then passed. Final focused XML suite:
5 passed. Combined full suite: 74 passed on CPython 3.13.12 (4.31s) and CPython
3.12.13 (8.32s), including installed wheel/sdist CLI tests. Ruff and mypy passed.
This integrated XML change still requires independent review at its final SHA;
these results do not claim real vendor-corpus acceptance.
