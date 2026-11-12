# Private P1 development candidate

Historical development record, 12 November 2026. The successor `0.1.2` is now
[published](https://github.com/Auda29/twincat-knowledge-mcp/releases/tag/v0.1.2)
at source commit `84c437aea8e27da930a246e7bb3ae310e8e5d31d`; use
[published setup](../setup.md) for current installation and artifact pins.
The original private candidate and its recorded hashes remain unchanged; it is
not relabeled. References below to fixed prior artifacts do not assert a GitHub
repository-level immutability setting.

`0.1.2.dev20261112` identifies the private development build of the five P1
typed tools reviewed at `486be3cef2a29e7163d362bd5cb3a89ef01f421a`.
It is a PEP 440 development version, not a published release. A different
version prevents changed code from being mistaken for the previously recorded 0.1.1
release wheel. The functional tool implementation and nine-tool schemas remain
the reviewed implementation; the package version and MCP server version advance
together.

Existing topic package formats and four topic-tool contracts remain compatible.
The five additive tools retain the contract in [typed entities](typed-entities.md).
Real-document extraction acceptance remains open. No vendor documentation or
operator corpus is bundled. The source archive contains ordinary repository
software sources, tests, and README material.

## Historical build and receipt

The following invocation records the canonical private rebuild at source
checkpoint `d5b774941600f746b092b0672216471f35dca73b`. It is not a
current setup command: the default development-version guard rejects the
ordinary `0.1.2` version on the release/current branch. The canonical rebuild used
a new directory inside ignored `dist/`:

```powershell
uv run --no-sync python tools/build-development.py --out-dir dist/p1-development-canonical
```

The helper requires clean tracked inputs and builds a committed Git archive.
It records source commit/tree, reviewed implementation commit, build inputs and
hashes, build/runtime versions, wheel and sdist hashes, runtime dependency pins,
and actual wheel-derived tool schemas. The receipt is an integrity record for
parent review; generating it does not approve adoption or constitute a signed
vendor attestation. Build outputs remain private local files.

Build dependencies are pinned with hashes in `tools/build-requirements.txt`.
The helper exports runtime dependencies from `uv.lock` with hashes, then uses
an isolated temporary environment to inspect the candidate wheel. The generated
`requirements-candidate.txt` pins both the wheel and its runtime dependencies.
Supply the relocated artifact directory with `--find-links` when installing
that file with `--require-hashes`; no absolute machine-specific wheel URI is
embedded in the requirements.

Assistant must review the new artifact SHA-256 and source revision, then create
its own adoption receipt and deliberate allowlist/prompt/config migration for
the five new read-only tools. It must not relabel the old wheel or weaken the
existing exact-byte overlay hash guard.

## Overlay compatibility

`src/twincat_knowledge/domain/provenance.py` retains its original bytes. The
development receipt records that file's source and wheel hashes for comparison
with Assistant's approved original. The wheel's metadata directory changes to
`twincat_knowledge-0.1.2.dev20261112.dist-info/`; the corresponding `RECORD` path
must be selected from the candidate wheel metadata rather than hardcoded to
0.1.1. If Assistant applies its reviewed overlay, that produces a different
artifact whose hash and receipt Assistant must record separately.

No merge, release, publication, upload, global policy change, or real-corpus
acceptance follows from producing these development artifacts.
