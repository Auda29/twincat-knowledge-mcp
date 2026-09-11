# Operator snapshot CLI

The operator CLI selects immutable, already-built topic packages through the
verified snapshot API. It does not import sources, scan a corpus directory, or
remove packages and caches.

## Commands

```text
twincat-knowledge corpus activate <package-dir> \
  --expected-manifest-sha256 <64 lowercase hex characters> \
  [--config <config.toml>] [--state-dir <dir>] [--cache-dir <dir>] [--json]

twincat-knowledge corpus rollback \
  [--config <config.toml>] [--state-dir <dir>] [--cache-dir <dir>] [--json]

twincat-knowledge corpus list \
  [--config <config.toml>] [--state-dir <dir>] [--cache-dir <dir>] [--json]
```

`activate` validates and fully loads the candidate before publishing it. The
manifest fingerprint is an operator-supplied trust anchor and is never derived
by the CLI. `rollback` uses only the pinned `previous` reference stored in
`active.json`; it accepts no candidate directory or pin. The CLI reads
`active.json` again after every successful activation or rollback and compares
the complete returned state to that readback before printing success. A
post-commit exception is therefore not retried automatically: re-read state
before retrying because the outcome may be ambiguous.

`list` reads only the selected active/previous references from the configured
state directory. It never scans package directories or revalidates packages,
and it does not write the cache. A missing `active.json` is reported as
`status: "not_available"` with `scope: "selected_snapshot_state"`. An existing
selection is `status: "not_ready"`: its IDs and manifest hashes are
state-only/unverified metadata, not proof that a package is available, trusted,
or that the complete product is ready.

JSON output is bounded and allow-listed. Active and previous entries contain
only `snapshot_id`, `manifest_sha256`, and `availability`; absolute paths,
rights references, document text, secrets, and package metadata are excluded.
Text output has the same scope. Exit status is 0 for a report, including an
empty `list` report, 1 for an operation/read failure, and 2 for argparse usage
errors. JSON operation errors go to stdout; text errors go to stderr. Errors
are fixed generic messages and never include package/config paths or raw
exception details.

## Path configuration

For each path, priority is:

1. Explicit `--state-dir` / `--cache-dir` flags.
2. The corresponding `TCK_STATE_DIR` / `TCK_CACHE_DIR` environment variable.
3. `[paths] state` / `cache` in TOML.
4. Failure closed when a required path is absent.

No `MCP_*` variables, `paths.corpus` fallback, home-directory scan, or default
path is used. Relative paths from flags and environment variables are resolved
against the command's current working directory. Relative TOML paths are
resolved against the directory containing that config file. Flags and
environment values are accepted without a config file when all required paths
are supplied. If `--config` is supplied, it is always read and validated even
when flags/environment values override both paths; malformed or unsafe config
therefore still fails.

Snapshot config parsing reads only a bounded UTF-8 regular file and rejects
special files, oversized files, malformed TOML, wrong `[paths]` table types,
empty/non-string path values, and NUL-containing values with generic errors.
Unknown root keys (including legacy authentication settings) remain accepted
for compatibility and are never printed. Existing `doctor`, `init`, and
`corpus validate` behavior is retained. `init` adds blank snapshot path fields
to newly-created files only; it does not rewrite existing configuration or
create state/cache directories.

## Verification scope

The CLI tests use two synthetic packages to exercise activation A → B, list,
rollback to the stored A reference, invalid pins, missing settings, malformed
configuration, scoped output, and readback verification. The installed wheel
and source archive console entry points are exercised from a foreign working
directory. These fixtures prove operator wiring and package integrity only;
they do not prove vendor authenticity, rights approval, real InfoSys coverage,
Windows behavior, crash durability, or full-product readiness.
