# Reader review remediation: ZIP boundaries and source identity

## Scope and status

This coordinator slice addresses four findings from the independent review at
`9e0830de61f3c88c1e6d122c69c06824583f9bf7`. The two XML extraction findings are
being handled separately. This report does not close the reader review or the
whole-product acceptance gate.

- Corrupt DEFLATE data now raises `InfoSysArchiveError`, preserving the exception
  cause rather than leaking `zlib.error` through the public API.
- Path validation and collision detection share a bounded percent-decoding
  fixpoint. Raw locators remain unchanged.
- Central-directory preflight walks fixed 46-byte headers and bounded variable
  fields before `ZipInfo` allocation. It counts real records, not the untrusted
  EOCD count. Tests include ZIP64, forged low counts, and exact-limit success.
- Both reader entry points require explicit `source_id` and `snapshot_id`.
  Existing synthetic tests now supply fixture identities. The metadata-only CLI
  supplies unique, internal inspection IDs per invocation; these are not approved
  persistent snapshots and are not returned as such.

## Actual RED -> GREEN evidence

`uv run --frozen --python 3.12 pytest tests/security/test_infosys_zip_regressions.py -q`
was run after each added behavior:

1. Invalid DEFLATE BTYPE=3: one failure with raw `zlib.error`; after normalization,
   one passed.
2. Repeated percent-encoding collision: two failures (did not raise), two passed;
   after shared decoding, the combined new/existing security tests were 12 passed.
3. Entry cap before allocation: two failures at the `ZipInfo` allocation sentinel,
   including forged EOCD count; after streaming preflight, 21 reader tests passed.
4. Required source/snapshot IDs: one failure (did not raise); after removing the
   defaults, nine archive regressions passed. The CLI then failed because it did
   not supply the newly required IDs; the explicit inspection identity fixed it.

All prior assertions were retained. No limit or check was removed.

## Full local verification

- CPython 3.12.13: normal full suite **69 passed in 4.12s**.
- CPython 3.13.12: normal full suite **69 passed in 4.31s**.
- Ruff check and format: passed; mypy: no issues in 12 source files.
- Installed wheel and source-archive CLI tests are included in the full suite.
- Separate sparse path probe: **2,147,483,963-byte** archive, **128-byte** memory
  source limit, one selected topic. An unrelated malformed XHTML member was not
  parsed. No full archive copy was made; the temporary synthetic archive was
  removed by its temporary-directory context.
- Builds/tests used the shared flock and a TMPDIR outside `/tmp`.

## CI diagnosis: external storage gate remains

The existing head `32f489a240b91c96379fd54529fcb1cfc5876182` failed in the
`Upload private CI build (not a release)` step on all four Foundation jobs.
The upload log in job `102896893292`, run `34484989466`, says:

> Failed to CreateArtifact: Artifact storage quota has been hit. Unable to upload
> any new artifacts. Usage is recalculated every 6-12 hours.

The repository artifact API returned `total_count: 0`; there are no project-owned
artifacts here to reclaim. No artifacts in other repositories were deleted,
no spending settings were changed, and no CI check was disabled or made optional.
Test/build success is separate from failed artifact delivery. The final head still
needs native CI and independent review; real Python/vendor corpus acceptance is
also open.


## Native CI follow-up: Python patch-release ZIP64 compatibility

Run 34497239566 at df8588d exposed two real test failures on Windows Python
3.12.10, in addition to the separately failing artifact uploads on other jobs.
The failing ZIP64 cases were reproduced unchanged on Linux CPython 3.12.10:
2 failed, 7 passed. Inspection of the actual stdlib implementations showed that
3.12.10 leaves `_ECD_LOCATION` at the classic EOCD and subtracts the fixed ZIP64
records later in `ZipFile`; 3.12.13/3.13.12 normalize the end-record location
inside `_EndRecData64`. The preflight had assumed only the newer convention.

The fix distinguishes the actual record signature at the returned location,
adjusts classic-location ZIP64 records, validates the resulting signature, and
then runs the same bounded directory walk. No OS/version guess, parser limit
removal or test exclusion was used. After the fix: the same 9 archive tests pass
on 3.12.10 and 3.13.12; full suite 74 passed on 3.12.10 (4.41s). Ruff and mypy
passed. Native Windows rerun and review of this follow-up remain required.


## Second independent ZIP review: raw names and UTF-8

The review at 34cb581 confirmed the four requested fixes on the newer Python
patch versions, but found two additional boundary defects. Both were reproduced
before correction:

- Invalid UTF-8 with general-purpose flag bit 11 leaked `UnicodeDecodeError`:
  one RED failure, then 10 archive tests passed after normalizing `UnicodeError`
  to `InfoSysArchiveError` at the outer archive context boundary.
- Raw NUL/backslash filenames reached `ZipInfo`, which truncates NULs and
  normalizes backslashes on Windows. Two new tests failed at a pre-sanitization
  allocation sentinel. Preflight now reads one bounded raw filename at a time,
  decodes it under the ZIP flag and validates its original spelling before any
  `ZipInfo` construction. Extra/comment fields remain seek-skipped and bounds
  remain enforced. Afterward all 12 ZIP regression tests passed.

Final local full suite: 77 passed on CPython 3.13.12 (4.26s) and CPython 3.12.10
(4.49s), including installed artifacts. Ruff and mypy passed. This supersedes
neither native CI nor the required independent follow-up review.
