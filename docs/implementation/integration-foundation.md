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
- Extended the installation test to direct wheel builds and sdist-to-wheel builds.
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
- The parent packaging correction has not received a separate independent review.
