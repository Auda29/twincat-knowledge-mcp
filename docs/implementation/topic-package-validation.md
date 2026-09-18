# Topic package validation

This slice adds a pure, no-I/O validation boundary for normalized topic records
before a future JSONL/SQLite package index is published:

```python
from twincat_knowledge.corpus.topic_validation import validate_topic_corpus

summary = validate_topic_corpus(manifest, topics)
```

`topics` is consumed incrementally. The validator never calls `list()` on the
iterable, opens a locator, reads a source archive, performs a network request,
or authenticates source bytes. A caller failure from `iter()` or `next()` is
reported as the fixed generic `TopicCorpusValidationError` message
`topic corpus iterator failed`; caller exception text is not chained into the
public error. A summary is constructed only after every supplied topic has
passed validation and all manifest counts reconcile.

## Bounds and result

The public limits are strict positive integers; `bool` is rejected. Values
above these fixed hard maxima are rejected:

| Limit | Default and hard maximum |
|---|---:|
| `max_topics` | 100,000 |
| `max_sections` | 1,000,000 |
| `max_total_bytes` | 536,870,912 |
| `max_record_bytes` | 1,048,576 |

Record and total byte limits count the UTF-8 bytes of each compact Pydantic
JSON record (without a JSONL newline). `TopicCorpusSummary` is a frozen,
slotted dataclass whose `language_counts` is a read-only mapping.

## Checks

The public `CorpusManifest` and each public `Topic` are serialized and parsed
again through their strict models. This catches invalid instances manufactured
with `model_construct()` or unsafe `model_copy()` updates, including unknown,
typed, and provenance-invalid JSON. Model/serializer failures are reduced to
the fixed generic message `topic corpus contains invalid data`; input values and
field paths are not exposed.

The manifest must use the explicitly supported package schema `1.0`. Source
snapshots must use explicitly supported source schema `1.0` and are mapped by
`(source_id, snapshot_id, language)`. Every topic must have a matching mapping.
The package `manifest.snapshot_id` is intentionally not compared with a source
snapshot ID: package-generation and source-generation identities are distinct.
Article `SourceReference.content_hash` is retained evidence and is never
compared with the source snapshot's archive/content hash.

`inventory.documents_imported` must equal the consumed topic count. The
manifest must provide `entity_counts`, and its `topics` and `sections` values
must equal the validated counts. Other entity-category counts are deliberately
not verified and are outside this summary's scope. No source-version, rights,
or source-byte-authenticity claim is inferred.

For every topic, the validator recomputes the canonical topic ID from exactly
`{source_id, snapshot_id, language, raw_locator}` and rejects duplicates or
aliases. For every ordered section, it recomputes the section ID from exactly
`{topic_id, section_index}`. This rejects reordered or swapped IDs even when a
forged public model has internally rebound its `source.section_id` value.
Metadata, order, repeated values, text, tables, code, titles, and unknown
source claims are not transformed.

## Canonical identity helper

`twincat_knowledge.domain.identity` is pure domain code and has no ingest or
corpus imports. It preserves the existing normalizer scheme: sorted compact
JSON, `ensure_ascii=False`, UTF-8, SHA-256, with `topic-` or `section-`
prefixes. `ingest.normalize` delegates to this helper, so existing normalized
IDs remain byte-for-byte stable.

## Verification

The new unit tests exercise a real synthetic
`InfoSysReader -> normalize_infosys -> write/read_topic_export -> validator`
path, stable IDs, public JSON ID forgery, source mismatches, count mismatches,
section reorder/swap, bypassed models, strict bounds, incremental consumption,
generic iterator failures, and late-failure behavior. Synthetic data validates
plumbing only; real InfoSys coverage, source permissions, source-byte
authentication, package activation, and SQLite publication remain later gates.
