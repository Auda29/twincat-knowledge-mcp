# Typed documentation tools, P1

This development slice adds five read-only tools to the four existing topic
tools. It does not implement the full catalog in PLAN. Real-document extraction
acceptance is open. Tests use synthetic documentation and do not prove coverage
of the installed InfoSys corpus.

## Wire contract

Authoritative Pydantic schemas live in `services/entity_contracts.py` and
`domain/entities.py`. The stdio `tools/list` response publishes their JSON
schemas. Unknown input fields and coercion are rejected.

| Tool | Input |
| --- | --- |
| `tc_find_symbols` | `query`, optional `filters`, `limit`, `cursor` |
| `tc_get_symbol` | `symbol_id` |
| `tc_find_libraries` | `query`, optional `filters`, `limit`, `cursor` |
| `tc_get_library` | `library_id` |
| `tc_lookup_error` | original string `code`, optional `domain`, `filters`, `limit`, `cursor` |

Filters contain optional `namespace`, `library`, and `documented_version`.
The default limit is 5; the maximum is 20. Name matching is exact,
case-insensitive. Version and error-code spelling are exact. No semantic,
substring, or numeric-conversion fallback occurs. Equal codes in separate domains
remain separate evidence. Callers must inspect ambiguity and missing fields.

Principal argument names follow PLAN. This bounded slice deliberately omits
`match`, symbol `kind` filtering, section selection, and library symbol-index
expansion. Such arguments are rejected rather than silently ignored. Full
parameters, behavior, examples, dependencies and relations are not promised.

Responses retain the existing envelope: `schema_version`, `status`,
`snapshot_ids`, `data`, `sources`, `warnings`, `truncated`, and `next_cursor`.
Typed data contains `items`, `has_more`, and `coverage_available`.
Multiple matching records are ambiguous, including when pagination returns only
one of them. A missing package is `not_available`; a loaded package without a
typed match is `not_found`. `coverage_available` means that the extractor found
at least one entity of that kind, not complete coverage or vendor verification.

Entities retain an opaque ID, normalized topic ID, source references, nullable
namespace/library/documented version, and explicit missing fields and warnings.
Symbol declaration text is preserved as normalized source code, with no rewrite
or claim that it matches a live editor buffer. Source references retain source
and snapshot IDs, original topic/section IDs, locator, content hash and any
available canonical URL. A documented version is never an installed version.

The existing domain and complete JSON-RPC response byte budgets still apply.
An indivisible record exceeding the budget produces an explicit error rather
than a silently shortened declaration.

## Import and rollout

Existing topic packages remain valid without migration or reimport. Typed
extraction runs lazily over the validated, read-only topic index on the first
typed query and is retained for that service generation. Startup, manifest hash
verification, snapshot selection, and the four original topic tools retain their
existing behavior. No source material is fetched or redistributed. Import still
requires the operator's authorized local documents and rights reference.

The extractor accepts only narrowly recognized source structures. Unsupported
formats, prose mentions, and missing metadata do not become verified entities.
In particular, topic routing directories do not prove a library name, version,
or namespace. Review `ingest/entities.py` for the exact grammar and bounds.

- Symbols require a code section labeled ST, iecst, or Structured Text, an
  initial declaration keyword and identifier, and a topic title matching that
  identifier. The entire normalized code section is retained.
- Explicit Library, Namespace, LibraryVersion/DocumentedVersion and ErrorDomain
  metadata or Field/Value tables provide article context. Conflicts remain
  unknown. Generic Version rows require an explicit Library row in that table.
- Column-style library tables produce separate library records. Namespace and
  version cells stay within their own row. Even a single library row does not
  establish membership for a neighboring symbol or error.
- Error tables require Error code and Description/Meaning columns. Optional
  domain and name cells describe that same row. Supported code syntax is signed
  or unsigned decimal up to 20 digits, `0x` hexadecimal up to 16 digits, or IEC
  `16#` hexadecimal up to 16 digits. Original spelling, including surrounding
  whitespace, is retained and matched exactly.

Unlabeled code, declarations whose titles do not match, arbitrary prose,
nonrecognized labels, symbolic error names without numeric codes, dependencies,
parameter semantics and examples are not extracted. Exceeding extraction/index
bounds fails the typed request explicitly; it does not report a partial index as
complete. Topic queries remain available independently.

This change does not establish installed library versions, live editor contents,
dirty state, or compiled PLC state. Engineering observations require their own
session/context/source provenance; diagnostics belong to their build UUID.

The initial development slice did not authorize publication. Subsequent user
authorization permits the ordinary `0.1.2` software release; see its release
notes. Assistant integration must review the released commit and issue a new
hash receipt for changed release inputs. An old `provenance.py` overlay mismatch
must not be bypassed. Real-document extraction acceptance remains separate.
