# Topic JSONL export

`twincat_knowledge.corpus.topic_export` is a source-neutral package component for
transporting normalized `Topic` models. It does not import documents, use an
LLM, normalize text, or access SQLite.

## Format and API

```python
from pathlib import Path
from twincat_knowledge.corpus.topic_export import (
    read_topic_export,
    write_topic_export,
)

summary = write_topic_export(Path("topics.jsonl"), topics)
topics = read_topic_export(Path("topics.jsonl"))
```

`write_topic_export` accepts an iterable of `Topic` instances and returns the
immutable `ExportSummary` fields `count`, `bytes`, and `sha256`. Each output
record is exactly `Topic.model_dump_json()` encoded as UTF-8, followed by one
LF byte. The writer does not reconstruct models, sort records, alter strings,
or remove repeated metadata and attributes. The reader returns records in file
order and uses the public `Topic.model_validate_json` API for consistency and
provenance validation. It accepts a final record without an LF; all other
records must be line-delimited.

The SHA-256 is calculated over the exact bytes published in the file. It can
detect later byte changes, but it is not a signature, trust decision, or proof
that the bytes match an original source document. Package manifests, indexes,
activation, source snapshots, signatures, and MCP integration are separate
future components.

## Bounds

The defaults and hard maxima are:

| option | default and hard maximum |
| --- | ---: |
| `max_topics` | 100,000 records |
| `max_total_bytes` | 64 MiB, including LF bytes |
| `max_record_bytes` | 1 MiB of JSON payload bytes, excluding its optional LF |

Options must be real positive integers (booleans are rejected) and cannot exceed
these hard maxima. The writer consumes an iterable incrementally and retains
only the bounded duplicate-ID set; it never materializes the input iterable.
The reader uses binary `readline(max_record_bytes + 1)` calls, accounts for
bytes as they are read, and also performs an early file-size check. A file that
grows after that check is still rejected when incremental accounting crosses
the total bound. The returned tuple is bounded by `max_topics`.

The reader rejects blank lines, a UTF-8 BOM, invalid UTF-8, malformed JSON,
multiple JSON values on one line, trailing non-JSON data, invalid `Topic`
models, and duplicate topic IDs. Validation, serialization, iterator, and I/O
failures are reported through domain errors with stable messages that do not
include private paths or full record content. A failed build never publishes a
partial file.

## Safe publication

The writer requires an already-existing parent directory and a new output
name. It creates a private temporary directory in that same parent, writes the
complete file with a writable handle, flushes and `fsync`s it, closes it, then
publishes with an exclusive same-filesystem hard link. This makes publication
refuse pre-existing regular files, directories, dangling symlinks, and targets
created concurrently. There is deliberately no rename/replace or copy
fallback: a filesystem without the required hard-link operation produces a
clear domain error instead of risking overwrite. Only the writer-owned private
temporary directory is cleaned up; neighboring files and sidecars are never
removed.

Reading is side-effect free: it opens the selected file only for binary read
and does not create temporary files, indexes, sidecars, or activation state.


## Coordinator integration checkpoint

The reviewed Windows staging-fsync fix from `cde8a56` was merged into this branch;
export writes already fsync their writable `xb` stream. The coordinator then found
that rejecting the UTF-8 BOM byte sequence anywhere in a record incorrectly
rejected legitimate U+FEFF inside JSON strings. An actual write/read roundtrip
failed before restricting BOM rejection to the start of a record. JSON framing
BOMs remain invalid; embedded code/metadata content survives unchanged.

Final combined verification: 23 export tests and 151 full tests passed, the latter
on both CPython 3.12.10 and 3.13.12. Ruff check and mypy passed. These are real
coordinator reruns, not an independent approval. Dedicated installed-export and
native CI checks plus independent review remain open at this checkpoint.
