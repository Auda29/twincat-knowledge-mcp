# Foundation integration verification

## Scope and state

Local branch: `swarm/integration-foundation`. No push, main merge or release.
Integrated package, CLI and provenance/model slices, including package correction
`6070b3e` and provenance correction `16876b4`. This is not a working knowledge
server and does not satisfy the full PLAN definition of done.

## Parent verification

On integration commit `bd3f691`, Linux CPython 3.12.13 and 3.13.12 each passed
41 tests, Ruff check/format, strict mypy and `uv pip check` after
`uv sync --frozen --python VERSION --dev` in separate external environments.
However, these tests only exercised installed CLI behavior. An additional
isolated import from the final installed wheel exposed a packaging defect:
`ModuleNotFoundError: No module named 'twincat_knowledge.corpus'`.
Both the wheel and sdist omitted that source package. The broad `.gitignore`
pattern `corpus/` matched it, confirmed using `git check-ignore --no-index -v`.
The old artifacts in `.hermes/experiments/twincat-integration-dist/bd3f691`
are failed evidence, not deliverable artifacts.

## Packaging regression and fix

- Added installed `CorpusManifest` and `SourceReference` imports and an explicit
  null-URL JSON roundtrip under `python -I` from a foreign CWD, without PYTHONPATH.
- Observed expected RED at the import assertion: missing corpus package.
- Added a narrow ignore exception for `src/twincat_knowledge/corpus/`;
  operator corpus directories remain ignored.
- Initially parametrized direct and default builds, but both cases handed a wheel
  to the installer. Independent review M-01 required explicit source-archive
  installation and provenance assertions; see the correction below.
- The first post-fix run reached the corpus import but failed loading Pydantic's
  native extension on the noexec `/tmp` mount. This was an environment failure,
  not a passing test. Use an executable workspace pytest `--basetemp` here.
- Final complete suite: **42 passed** under Python 3.12.13 and **42 passed** under
  Python 3.13.12; no skips. Ruff check and format passed (14 files); strict mypy
  passed (10 source files); `git diff --check` passed. Commands exited zero.

## Reproduction

From the integration worktree, run sequentially for VERSION=3.12 and 3.13:

```sh
export UV_PROJECT_ENVIRONMENT=/absolute/external/venv-VERSION
export UV_LINK_MODE=copy
export TMPDIR=/absolute/executable/build-temp
mkdir -p "$TMPDIR"
uv sync --frozen --python VERSION --dev
uv run --frozen --python VERSION python -m pytest -q tests --basetemp=/absolute/executable/test-temp-VERSION
uv run --frozen --python VERSION ruff check src tests
uv run --frozen --python VERSION ruff format --check src tests
uv run --frozen --python VERSION mypy
uv pip check --python "$UV_PROJECT_ENVIRONMENT/bin/python"
```

Use a dedicated disposable basetemp: pytest clears it. Coordinate concurrent
builds externally with a bounded shared lock, not a machine-specific test path.
Actual parent environments and disposable test directories are under
`/home/hermes/workspace/.hermes/experiments/twincat-integration-pyVERSION`
and `twincat-packaging-final-pyVERSION` respectively.

## Remaining gates

- No native Windows run or claimed Windows acceptance.
- No real authorized InfoSys/ESI corpus or import; usage rights remain unresolved.
- No production MCP server, 15 knowledge tools, reader, search, host integration,
  retrieval evaluation, remote CI or release acceptance in this slice.
- Installed model and CLI checks do not prove safe filesystem reads or networking.
- Independent review of `153d782` verified all four installed-artifact combinations
  but requested M-01 test-gate changes. The correction below awaits re-review.

## M-01: explicit sdist installation

The installed distribution's `direct_url.json` now asserts the artifact suffix.
Observed RED under Python 3.12: the sdist case recorded `.whl`, not `.tar.gz`
(one failed test, exit 1). The corrected case builds with `uv build --sdist`,
selects the sole `.tar.gz`, and installs it using `uv pip install --no-cache`.
The direct wheel case remains separate. Both retain isolated installed imports,
JSON-null roundtrip and real CLI checks from a foreign working directory.

The first uncached installation attempt ran out of space in the 512 MiB `/tmp`
mount (two failed E2E cases, 40 passed); it was not a product failure or GREEN.
After setting TMPDIR to a dedicated workspace directory, the complete suite
passed: CPython 3.12.13 **42 passed**, CPython 3.13.12 **42 passed**. Ruff check,
format and strict mypy passed in both environments; diff check passed. No skips.
Only test and report files changed; production source and package config did not.
