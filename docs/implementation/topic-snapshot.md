# Topic snapshot activation

`twincat_knowledge.corpus.topic_snapshot` is the operator-side pointer for
validated topic packages. It does not add MCP methods, expose filesystem paths
to model tools, import sources, migrate SQLite schemas, or delete packages and
caches.

## State contract

The fixed operator file is `active.json` in an existing operator-owned
`state_dir`. Its UTF-8 JSON object is versioned (`format_version: "1.0"`) and
contains exactly one `active` reference and an optional `previous` reference.
Each reference contains:

- a resolved absolute local `package_path`;
- the exact caller-provided lowercase 64-character manifest SHA-256 pin; and
- the package manifest's corpus `snapshot_id`.

`SnapshotReference` and `SnapshotState` are frozen strict Pydantic models. JSON
has duplicate-key detection, unknown-field rejection, strict supported-version
validation, and a 64 KiB total state-file bound. State reads use `lstat`,
regular-file checks, no-follow/nonblocking opens where supported, descriptor
`fstat`, a cumulative bounded read plus sentinel, and a final size check. A
missing `active.json` raises `SnapshotNotFound`, which is the only intentional
empty-first-startup distinction. Malformed, oversized, duplicate, unsupported,
path, and pin inputs fail closed as `SnapshotError` without forwarding parser
or filesystem details.

The state directory, candidate package, and cache must be physically disjoint
resolved directories. The package and cache are validated by the existing
`load_topic_package` loader. That loader's caller-supplied manifest pin remains
the integrity trust anchor; a matching hash is not a vendor signature or a
rights assertion. The package snapshot ID is checked separately from source
snapshot IDs.

## Operations

```python
activate_snapshot(
    state_dir,
    package_path,
    expected_manifest_sha256=pin,
    cache_dir=cache_dir,
) -> SnapshotState

rollback_snapshot(state_dir, cache_dir=cache_dir) -> SnapshotState
load_active_snapshot(state_dir, cache_dir=cache_dir) -> LoadedTopicPackage
read_snapshot_state(state_dir) -> SnapshotState
```

Activation verifies and fully loads the candidate before publication. The first
activation writes `previous: null`; a later activation moves the current
active reference to `previous`. Activating an identical active reference is a
no-op and preserves the existing rollback reference. Rollback verifies the
stored previous package and pin before swapping active and previous in one
state object. Missing or invalid rollback targets do not alter `active.json`.
No migration or package deletion occurs.

`load_active_snapshot` reads and parses one complete immutable state-file
snapshot before loading its reference. A concurrent pointer replacement cannot
retarget that call. Its returned `LoadedTopicPackage` owns a private cache
generation; callers must close it (or use it as a context manager). Existing
loaded resources therefore continue serving their generation after activation
or rollback, while newly loaded resources use the new pointer.

## Atomic update protocol

Writers cooperate through the fixed `.active.lock` file. Lock creation is
exclusive and fail-fast (`SnapshotBusy`); readers never acquire this lock. A
pre-existing lock is never judged stale or deleted automatically. The lock is
released only by the call that created it, after closing its descriptor and then
unlinking its own path. A crash can leave a stale lock; an operator must inspect
and remove it manually after confirming no updater remains.

State publication creates a private same-filesystem `.active-*` temporary,
flushes and `fsync`s it through a writable descriptor, closes it, and then uses
`os.replace` on the fixed `active.json` target. Temporary cleanup is limited to
the private file created by that call. Existing regular state bytes remain in
place when candidate validation, serialization, fsync, or replacement fails.
Foreign symlink and special-file state targets are rejected; there is no copy
fallback or broad cleanup.

This gives atomic visibility of the complete active/previous object. It does
not claim crash durability of the containing directory entry because directory
`fsync` is deliberately outside this component's contract. The deployment must
provide a stable trusted parent and sandbox the operator process against
malicious same-account path replacement; these checks are not a defense against
that race or against an untrusted state owner.

Unreferenced packages and cache generations are retained. Retention and
cleanup, if later required, must be an explicit operator operation that can
prove ownership and preserve in-flight readers.

## Verification

The unit tests use only synthetic packages. They cover activation A → B,
in-flight A isolation, restart reads, rollback, identical no-op behavior,
source immutability and private-cache cleanup, invalid candidates, malformed /
duplicate / oversized / unsupported state, strict model revalidation, symlink
and FIFO rejection, busy-lock preservation, replacement and fsync failure,
and cancellation cleanup. These tests do not constitute real InfoSys coverage,
vendor authenticity, rights verification, directory crash-durability proof, or
Windows execution evidence.

## Coordinator boundary regressions

The coordinator reproduced two lock-acquisition leaks: both an `fstat` error
and cancellation after exclusive creation left the descriptor and lock owned but
unreleased. Acquisition now starts cleanup ownership immediately after open and
releases on either failure, while preserving cancellation.

A separate public-reader regression atomically replaces the pointer between
preflight stat and open with a different-sized valid generation. The read is now
bound to the opened descriptor's size and bytes, not the prior pathname's size.
Regular-file, byte-bound and growth checks remain; no retry or partial-state
fallback is introduced. This does not claim hostile same-account race protection
or guaranteed successful Windows replacement while another reader holds a handle.

After these RED/GREEN corrections, 17 focused snapshot tests and 257 full tests
passed on each of CPython 3.12.10 and 3.13.12. Ruff check/format and mypy passed.
Independent review and native Windows CI of the final component remain required.
