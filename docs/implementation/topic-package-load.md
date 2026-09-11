# Topic package loader

`twincat_knowledge.corpus.topic_package_load.load_topic_package` is the
read-only package boundary for an already published topic package. It does not
ingest sources, activate a package, make rights decisions, or scan a directory.

## Contract

```python
with load_topic_package(
    package_path,
    expected_manifest_sha256=operator_pin,
    cache_dir=stable_operator_cache_parent,
) as loaded:
    topic = loaded.index.get_topic(topic_id)
    matches = loaded.index.search('timer')
```

`expected_manifest_sha256` is mandatory and must be exactly 64 lowercase hex
characters. The caller-provided pin is an out-of-band operator anchor. A
matching hash proves only that the descriptor bytes match the requested pin; it
does not prove source authenticity, licensing, or vendor rights.

The package directory and cache parent must already exist as non-symlink
regular directories. The cache parent must be outside the package directory.
The loader uses one private `TemporaryDirectory` below that parent and fixed
names only: `manifest.json`, `topics.jsonl`, and `topics.sqlite`. It never
modifies, deletes, or scans the source package.

## Ordered verification

1. Validate the exact fingerprint before reading package data.
2. Read only the fixed manifest path through a regular-file, no-follow,
   nonblocking descriptor with the shared 16 MiB `MAX_MANIFEST_BYTES` bound.
3. Compare the manifest SHA-256 before JSON/model parsing or SQLite opening.
   Raw JSON is strict UTF-8, rejects duplicate object fields and non-standard
   constants, and is validated as the supported `TopicPackageManifest` and
   nested `CorpusManifest`.
4. Validate each fixed artifact descriptor's size bound before opening it.
   Each source artifact is copied to an exclusive private cache file through a
   regular-file `lstat`/`fstat` check, bounded chunk reads, a cumulative count,
   and an over-limit sentinel. The copied bytes must match both descriptor size
   and SHA-256. JSONL is capped at 64 MiB; SQLite is capped at 512 MiB.
5. Reload the verified private JSONL with `read_topic_export`, then run
   `validate_topic_corpus`. Manifest language counts must equal the validated
   summary.
6. Only after those checks does the loader open the private SQLite copy via
   `TopicIndex`. It checks both table counts and every validated topic's exact
   payload, rejecting foreign or extra rows. FTS search remains read-only.

No source SQLite file is opened. Later source edits cannot change topics already
served from the private copy. SQLite is configured by `TopicIndex` for
read-only/query-only access.

## Lifetime and failures

`LoadedTopicPackage` retains only the validated manifest, immutable summary,
and read-only index; it does not retain the topic tuple. `close()` is
idempotent. It closes the index before removing the private cache, including on
Windows, and manifest/summary/index access after close raises the generic
`TopicPackageLoadError`. The context manager closes automatically.

Failures use generic loader-domain messages rather than exposing source paths,
model details, or record contents. Missing/partial files, malformed or
unsupported metadata, bad pins, symlinks, special files, races, growth,
size/hash/count/language mismatches, and semantic validation failures are
fail-closed. Private descriptors, SQLite connections, and cache files are
cleaned on ordinary errors and cancellation; caller-owned package and cache
parents are not broadly cleaned. `BaseException` cancellation is not swallowed.

The loader's hashes are corruption/integrity checks, not an authentication or
sandbox boundary. A malicious same-account operator can still modify the
source or cache while the loader is running; network-filesystem deadlines,
activation, rollback, and full-host authorization remain outside this slice.

## Coordinator API and cache-boundary corrections

The public call now returns a fully validated `LoadedTopicPackage` immediately,
not a deferred generator context manager. Direct access plus explicit `close()`
and `with` both work. Exceptions from the caller's `with` body retain their
original identity instead of being translated into load failures. Two regression
tests demonstrated the prior API mismatch and exception reclassification.

The outside-package cache rule compares resolved physical paths, not lexical
path prefixes. Two regressions demonstrated that symlinked ancestors on either
the package or cache side could otherwise place the private cache inside the
source package. Both now reject before cache creation. This check does not
claim protection against hostile concurrent parent-directory replacement.

Coordinator verification: 21 focused loader tests and 232 full tests passed on
each of CPython 3.12.10 and 3.13.12 with external pytest basetemps; Ruff check,
format, and mypy passed. Independent review and native CI remain open.
