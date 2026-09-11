# Topic package build

`twincat_knowledge.corpus.topic_package.build_topic_package` creates one
operator-owned topic package from a normalized `CorpusManifest` and an iterable
of `Topic` models. It performs no imports, network calls, model calls, serving,
activation, rollback, or source-trust decision.

## Artifacts and generation

A successful build contains exactly these fixed artifacts:

- `topics.jsonl`: the existing bounded JSONL writer's exact UTF-8
  `Topic.model_dump_json()` records, in caller order;
- `topics.sqlite`: the existing bounded SQLite/FTS5 index;
- `manifest.json`: a strict, versioned descriptor containing the supplied corpus
  manifest, immutable language counts, the actual SHA-256 and byte count for the
  two artifacts, and the actual index format (`sqlite-fts5`) and schema version.

The writer consumes the input once. The completed JSONL is then bounded-reloaded
and passed to `validate_topic_corpus` with the supplied corpus manifest before
index creation. The index is reopened read-only and every topic is compared by
exact ID and model value against that reload. Thus JSONL and SQLite are derived
from the same validated generation; no alternative JSON normalization is used.
Checksums detect later byte changes. They do not attest to source authenticity,
licensing, or vendor trust.

`manifest.json` is deliberately excluded from its own file-hash list. Its
returned `manifest_sha256` and `manifest_bytes` describe the exact emitted
UTF-8 JSON descriptor (including its final LF). A future loader must require and
verify this final marker and all listed hashes.

## Bounds

The defaults and hard maxima are inherited from the existing components:

| option | default | hard maximum |
| --- | ---: | ---: |
| `max_topics` | 100,000 | 100,000 |
| `max_total_bytes` | 67,108,864 | 67,108,864 |
| `max_record_bytes` | 1,048,576 | 1,048,576 |

Options are positive integers; booleans and values above the maxima are
rejected before the output directory is created. The limits apply during JSONL
write, reload, semantic validation, and index construction.

## Publication and failure policy

The caller must provide a stable, operator-controlled existing parent directory.
The package path itself must be new. Creation uses exclusive directory creation,
so an existing regular file, directory, dangling symlink, or target created
concurrently is rejected without replacement or modification. The two artifacts
use the existing exclusive writers. The descriptor is written last through a
private writable temporary file, flushed and `fsync`ed, closed, and published
with an exclusive same-filesystem hard link. There is no rename, replace, copy,
or best-effort deletion fallback. A filesystem without the required hard-link
operation fails closed without a success marker.

This is a final validity marker, not an atomic directory rename and not a crash
durability claim. A failed new build may leave its incomplete directory and
artifacts for explicit operator cleanup. Only private temporary files owned by
the current build are cleaned; existing neighbors, sidecars, suffixes, and
public paths are never broadly deleted. Concurrent directory replacement in a
hostile filesystem is outside this controlled operator-owned boundary and is not
claimed to be sandboxed.

Artifact names are fixed by the strict manifest model. Symlinked or non-regular
artifacts are rejected while their facts are collected. Paths and content from
models are never used to select output filenames. Exception messages from
caller generators, validation, path handling, and record content are suppressed
to generic package errors; cancellation-style `BaseException`s are not
swallowed.

Read-only serving, package loading, activation, and rollback are separate
components and are intentionally outside this build slice.

## Coordinator verification

A regression demonstrated that a same-length JSONL modification between export
and manifest publication was accepted. Publication now compares both actual byte
count and SHA-256 against the original export summary; the regression now rejects
that mismatched generation without a final manifest.

The coordinator ran 20 focused package tests and 204 full tests on each of
CPython 3.12.10 and 3.13.12, including wheel/sdist installation, with dedicated
pytest basetemps outside `/tmp`. All passed; Ruff check/format and mypy passed.
Earlier worker installation failures while mapping the installed pydantic_core
shared object did not reproduce with these test directories. They are not
counted as passes from the earlier failed run. Independent package review and
native CI for this component remain open.
