# Operator CLI: pinned topic-package validation

This implements the `corpus validate` operator command from PLAN section 10.2.
It is not an MCP tool and does not activate, repair or update a package.

```text
twincat-knowledge corpus validate <package-dir> \
  --expected-manifest-sha256 <64-lowercase-hex-digest> \
  --cache-dir <existing-operator-cache-directory> [--json]
```

The operator supplies the expected manifest fingerprint through an independently
trusted channel. Do not derive the expected fingerprint from an untrusted
package and treat it as evidence of authenticity. The explicit flags are required;
this slice adds no environment/TOML defaults or trust fallback.

The command calls the existing pinned package loader without bypassing its
bounds, hash checks, semantic checks, read-only index or physical cache separation.
The cache directory must already exist outside the source package. The returned
resource is closed before printing success, releasing the SQLite handle and
removing only the loader's private temporary cache. Source files are unchanged.

## Output and exit status

- Exit 0: topic-package validation succeeded. Text mode prints topic/section
  counts and scope limitations; `--json` emits a single JSON object with
  `schema_version: corpus-validation-1`, `status: valid`, `scope: topic_package`,
  the expected manifest SHA-256, topic/section counts, language counts and limits
  on the meaning of this validation. Neither format includes document text,
  titles, operator paths, rights-reference contents or raw exception details.
- Exit 1: package validation failed. Text mode prints a fixed message to stderr
  and no stdout. JSON mode emits a fixed error object to stdout and no stderr;
  it never emits a success report for a rejected package.
- Exit 2: malformed command-line usage, including omitted mandatory arguments,
  is handled by argparse. Neither omitted pin nor omitted cache is guessed.

The validated scope is the existing topic package: artifact integrity and
logical topic/index consistency. This is not source authenticity, rights
approval, complete entity-category coverage, real InfoSys acceptance, active
snapshot readiness or full-product acceptance. It does not extend the loader's
trust or concurrency guarantees.

## Verification

The first installed-artifact test failed because `corpus` was an unknown command.
After implementation it passed using the actual console entry point from both
an independently installed wheel and sdist in an isolated environment and foreign
working directory. A second red/green cycle added text output; six failing
negative cases established sanitized errors for missing sources and malformed
fingerprints. Mandatory-argument cases verify exit 2 without loading a package.

The installed test builds a synthetic package through the installed pipeline,
checks JSON and text validation output, exact source-byte preservation and empty
private cache, then alters the JSONL artifact and checks exit 1 plus rejection
without modifying the tampered input. This is synthetic evidence, not a real
vendor corpus test.

Coordinator full-suite results: 248 passed on CPython 3.12.10 and 248 passed on
CPython 3.13.12 under the shared build lock, including both installed-artifact
cases. Repository-wide Ruff check/format and configured mypy passed.
Independent review and native Windows CI remain required for this CLI delta.
