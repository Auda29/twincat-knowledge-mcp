# Set up published Knowledge 0.1.2

The current software release is [0.1.2](https://github.com/Auda29/twincat-knowledge-mcp/releases/tag/v0.1.2),
tag `v0.1.2`, source commit `84c437aea8e27da930a246e7bb3ae310e8e5d31d`.
Use its versioned GitHub Release assets. PyPI availability is not claimed.
Repository access may be required to download assets; a GitHub account or
repository visibility does not establish rights to Beckhoff documentation.

## Download and verify

Download the wheel, `requirements-candidate.txt`, `requirements-runtime.txt`,
`nine-tools.json`, `release-receipt.json` and `SHA256SUMS.txt` into one directory,
for example `release-assets`. The sdist is available for source inspection or
building. The release also includes `uv.lock` and `build-requirements.txt`.
No documentation corpus, operator configuration or database is bundled.

| Asset | SHA-256 |
| --- | --- |
| [Wheel](https://github.com/Auda29/twincat-knowledge-mcp/releases/download/v0.1.2/twincat_knowledge-0.1.2-py3-none-any.whl) | `7a657e559854bb85843aedbe0a1ac25a11994088ec39e1c7ff80cfcc2f509765` |
| [sdist](https://github.com/Auda29/twincat-knowledge-mcp/releases/download/v0.1.2/twincat_knowledge-0.1.2.tar.gz) | `4f1438aa6e1e1700c788864fdbf204a357edf493053d51f6161ee4af966f2dd2` |
| [Wheel and runtime pins](https://github.com/Auda29/twincat-knowledge-mcp/releases/download/v0.1.2/requirements-candidate.txt) | `0cc993ad490f2e0352ca615f4f3ee971ea3afaeb04d70320b9f52c702b251942` |
| [Runtime-only pins](https://github.com/Auda29/twincat-knowledge-mcp/releases/download/v0.1.2/requirements-runtime.txt) | `198a14ce273b1a9b6f70a2b9f09efa2c949654f1c0a7be4692ed19efdd6ee14d` |
| [Nine-tool schemas](https://github.com/Auda29/twincat-knowledge-mcp/releases/download/v0.1.2/nine-tools.json) | `6a2231f57a81c3ca2820bbae78c2f590fd5f6d259a37b19ae996fd8085f3c3ab` |
| [Release receipt](https://github.com/Auda29/twincat-knowledge-mcp/releases/download/v0.1.2/release-receipt.json) | `ce48bf76c22857272c99fcf3b8a8fb41e8cbea955b741d57b8b01cabd9830617` |

Compare the downloaded bytes to these pins before installation. For example,
PowerShell's `Get-FileHash -Algorithm SHA256 <file>` or POSIX `sha256sum <file>`
prints a file's SHA-256. `SHA256SUMS.txt` covers the release assets; the receipt
binds canonical source commit/tree and build inputs to the artifacts and actual
wheel-derived schemas. These are integrity records, not signed vendor
attestations. Repository-level GitHub release immutability is not asserted.
An asset replacement at the same URL fails an unchanged hash pin.

Despite its historical filename, `requirements-candidate.txt` in this release
pins ordinary `twincat-knowledge==0.1.2` and all runtime dependencies with hashes.
It contains no development-machine wheel URI. The private
`0.1.2.dev20261112` build is a [separate historical candidate](implementation/development-candidate.md)
and must not be substituted for the released wheel.

## Install in a separate environment

Requirements are uv, Python 3.12 or newer with SQLite FTS5, and access to runtime
dependency downloads or a separately prepared wheelhouse. CI covers Python
3.12.10 and 3.13.12 on Windows and Linux. No source checkout or TwinCAT
installation is needed to run the documentation server.

Windows PowerShell, from the directory containing `release-assets`:

```powershell
uv venv --python 3.12.10 .\knowledge-env
uv pip install --python .\knowledge-env\Scripts\python.exe --require-hashes --find-links .\release-assets -r .\release-assets\requirements-candidate.txt
.\knowledge-env\Scripts\twincat-knowledge.exe --version
```

On POSIX, replace the interpreter path with `./knowledge-env/bin/python` and
the console path with `./knowledge-env/bin/twincat-knowledge`. Expected version
output is `twincat-knowledge 0.1.2`. The sdist is an alternative source input;
the wheel hash above identifies the published wheel, not an arbitrary rebuild.

## Configure the client and authorized documentation

Use the absolute installed console entry point as the MCP command, with `serve`,
`--transport` and `stdio` as separate arguments. Add `--config` and an absolute
TOML path for a configured snapshot. The server is a JSON-RPC stdio process;
it is not an interactive command prompt or an HTTP service. See the
[client configuration printer](implementation/client-config-cli.md) and
[stdio serving contract](implementation/stdio-serving-cli.md).

Without a selected corpus, discovery lists all nine tools and knowledge calls
report `not_available`. No corpus is fetched automatically. To prepare one,
follow the [operator configuration and ingest walkthrough](../README.md#configure-and-select-a-topic-package)
and [snapshot commands](implementation/snapshot-cli.md). Those commands use the
source-checkout prefix in the README; substitute your installed console path.
Create state/cache directories outside the topic package, process only sources
you are entitled and explicitly authorized to use, record the rights reference,
then validate and activate the package with its trusted manifest hash.
Restart the client-owned server after activation or rollback.

Keep the previous software environment and operator configuration for rollback.
Updating the software does not require migrating an existing topic package.

## Coverage and acceptance

The release exposes four topic tools and five typed tools. Typed records retain
source/snapshot identity, exact normalized declarations or original error-code
spelling, missing fields and namespace/version/domain ambiguity. Documented
versions do not establish locally installed libraries or live/compiled state.
See [typed extraction formats and limits](implementation/typed-entities.md).

The typed index is constructed on the first typed query for each validated
service generation. This defers extraction, and does not establish a cold-start
or first-query latency target for large corpora. Real-document acceptance still
requires an approved source sample with fixed hashes, manually checked expected
records and negative cases, source/code and ambiguity review, coverage and
resource measurements, and explicit acceptance. Historical successful imports
or synthetic tests are not acceptance of this release's typed extraction.
