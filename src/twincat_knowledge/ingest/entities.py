"""Conservative, deterministic extraction from validated normalized topics.

Supported evidence in extractor v1:
* A code section labelled ST/iecst/Structured Text starts with FUNCTION_BLOCK,
  FUNCTION, PROGRAM, TYPE, METHOD, PROPERTY or INTERFACE plus an identifier.
  The complete topic title must equal that identifier, optionally preceded by
  the same declaration keyword. The entire code section is retained verbatim.
* Explicit Library, Namespace, LibraryVersion/DocumentedVersion and ErrorDomain
  metadata, or a Field/Value or Property/Value table containing those labels.
  A Version row is accepted only beside an explicit Library row in that table.
* A column table with a Library header documents one library per data row.
  Optional Namespace and Version columns apply only to their own row. These
  library rows never supply article-wide symbol or error context.
* An error table has Error code and Description/Meaning columns, optionally
  Error domain and Name. Decimal, 0x-prefixed and IEC 16# codes are supported.

Label spelling ignores case, spaces, underscores and hyphens. English labels
and the listed German equivalents are accepted. Arbitrary prose, source paths,
topic routing ``library`` and software/build version hints never supply facts.
Conflicting explicit context stays unknown and carries an ambiguity warning.
All limits fail closed; this module performs no I/O and executes no source code.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from twincat_knowledge.domain.entities import EntityKind, TypedEntity
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic
from twincat_knowledge.ingest.topic_hierarchy import _revalidate_topic

EXTRACTOR_VERSION = "typed-entities-1"
MAX_TOPIC_BYTES = 1_048_576
MAX_SECTIONS = 4096
MAX_METADATA = 4096
MAX_TABLE_CELLS = 32_768
MAX_ENTITIES_PER_TOPIC = 2048
MAX_CODE_CHARS = 262_144
_FIELDS = ("namespace", "library", "documented_version", "error_domain")
_LABELS = {
    "library": "library",
    "libraryname": "library",
    "bibliothek": "library",
    "bibliotheksname": "library",
    "namespace": "namespace",
    "namensraum": "namespace",
    "libraryversion": "documented_version",
    "documentedversion": "documented_version",
    "bibliotheksversion": "documented_version",
    "errordomain": "error_domain",
    "fehlerdomäne": "error_domain",
}
_DECLARATION = re.compile(
    r"\A\s*(FUNCTION_BLOCK|FUNCTION|PROGRAM|TYPE|METHOD|PROPERTY|INTERFACE)"
    r"[ \t]+(?:(?:PUBLIC|PRIVATE|PROTECTED|INTERNAL|FINAL|ABSTRACT)[ \t]+)*"
    r"([A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_ERROR_CODE = re.compile(
    r"(?:[+-]?[0-9]{1,20}|0[xX][0-9a-fA-F]{1,16}|16#[0-9a-fA-F]{1,16})\Z"
)


class EntityExtractionError(ValueError):
    """The topic is invalid or exceeds a documented extraction bound."""


def _label(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).casefold()


@dataclass
class _Context:
    values: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    sources: list[SourceReference] = field(default_factory=list)

    def add(self, key: str, value: str, source: SourceReference) -> None:
        value = value.strip()
        if not value:
            return
        maximum = 128 if key == "documented_version" else 512
        if len(value) > maximum:
            raise EntityExtractionError(f"explicit {key} exceeds its bound")
        if value not in self.values[key]:
            self.values[key].append(value)
        if source not in self.sources:
            self.sources.append(source)

    def merge(self, other: _Context) -> None:
        for key, values in other.values.items():
            for value in values:
                for source in other.sources:
                    self.add(key, value, source)

    def resolve(self) -> tuple[dict[str, str | None], tuple[str, ...]]:
        resolved: dict[str, str | None] = {}
        warnings: list[str] = []
        for key in _FIELDS:
            values = self.values.get(key, [])
            resolved[key] = values[0] if len(values) == 1 else None
            if len(values) > 1:
                warnings.append(f"ambiguous_{key}")
        return resolved, tuple(warnings)


def _checked_topic(topic: Topic) -> Topic:
    if not isinstance(topic, Topic):
        raise EntityExtractionError("input must be a Topic")
    try:
        if len(topic.sections) > MAX_SECTIONS or len(topic.metadata) > MAX_METADATA:
            raise EntityExtractionError("topic section or metadata count exceeds bound")
        payload_bytes = 0

        def charge(value: object) -> None:
            nonlocal payload_bytes
            if not isinstance(value, str) or len(value) > MAX_TOPIC_BYTES:
                raise EntityExtractionError("invalid or oversized topic text")
            payload_bytes += len(value.encode("utf-8"))
            if payload_bytes > MAX_TOPIC_BYTES:
                raise EntityExtractionError("topic text exceeds byte bound")

        attributes = 0
        for item in topic.metadata:
            charge(item.name)
            charge(item.content)
            if len(item.attributes) > MAX_METADATA:
                raise EntityExtractionError("metadata attributes exceed bound")
            for pair in item.attributes:
                attributes += 1
                if attributes > MAX_METADATA or len(pair) != 2:
                    raise EntityExtractionError("metadata attributes exceed bound")
                charge(pair[0])
                charge(pair[1])
        cells = 0
        for section in topic.sections:
            if not isinstance(section, Section):
                raise EntityExtractionError("invalid section")
            if section.kind == "code" and (
                not isinstance(section.code, str) or len(section.code) > MAX_CODE_CHARS
            ):
                raise EntityExtractionError("code exceeds its bound")
            if section.text is not None:
                charge(section.text)
            if section.code is not None:
                charge(section.code)
            if len(section.rows) > MAX_TABLE_CELLS:
                raise EntityExtractionError("table exceeds its bound")
            for row in section.rows:
                cells += len(row)
                if cells > MAX_TABLE_CELLS:
                    raise EntityExtractionError("table cell count exceeds bound")
                for cell in row:
                    charge(cell)
        checked = _revalidate_topic(topic)
        if len(checked.model_dump_json().encode("utf-8")) > MAX_TOPIC_BYTES:
            raise EntityExtractionError("topic exceeds its byte bound")
        return checked
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        if isinstance(exc, EntityExtractionError):
            raise
        raise EntityExtractionError("invalid normalized topic") from exc


def _contexts(topic: Topic) -> tuple[_Context, tuple[_Context, ...]]:
    groups: list[_Context] = []
    combined = _Context()
    metadata = _Context()
    for item in topic.metadata:
        key = _LABELS.get(_label(item.name))
        if key is not None:
            metadata.add(key, item.content, topic.source)
    groups.append(metadata)
    combined.merge(metadata)
    for section in topic.sections:
        if section.kind != "table" or not section.rows:
            continue
        header = tuple(_label(cell) for cell in section.rows[0])
        if header in (
            ("field", "value"),
            ("property", "value"),
            ("eigenschaft", "wert"),
        ):
            context = _Context()
            has_library = any(
                len(row) == 2
                and _LABELS.get(_label(row[0])) == "library"
                and bool(row[1].strip())
                for row in section.rows[1:]
            )
            for row in section.rows[1:]:
                if len(row) != 2:
                    continue
                key = _LABELS.get(_label(row[0]))
                if _label(row[0]) == "version" and has_library:
                    key = "documented_version"
                if key is not None:
                    context.add(key, row[1], section.source)
            groups.append(context)
            combined.merge(context)
        elif any(_LABELS.get(label) == "library" for label in header):
            keys = tuple(
                _LABELS.get(label)
                or ("documented_version" if label == "version" else None)
                for label in header
            )
            # Duplicate headers make row-to-field attribution ambiguous.
            recognized = [key for key in keys if key is not None]
            if len(set(recognized)) != len(recognized):
                continue
            for row in section.rows[1:]:
                if len(row) != len(header):
                    continue
                context = _Context()
                for key, value in zip(keys, row, strict=True):
                    if key is not None:
                        context.add(key, value, section.source)
                groups.append(context)
    return combined, tuple(groups)


def _make(
    topic: Topic,
    kind: EntityKind,
    name: str,
    context: _Context,
    sources: tuple[SourceReference, ...],
    **fields: Any,
) -> TypedEntity:
    resolved, warnings = context.resolve()
    if kind != "error":
        resolved.pop("error_domain")
        warnings = tuple(w for w in warnings if w != "ambiguous_error_domain")
    # Row-local explicit fields override the article context only when present.
    resolved.update(fields)
    warnings = tuple(
        warning
        for warning in warnings
        if not any(warning == f"ambiguous_{key}" for key in fields)
    )
    citations = tuple(dict.fromkeys((*sources, *context.sources)))
    if len(citations) > 64:
        raise EntityExtractionError("entity citation count exceeds bound")
    expected = ["namespace", "library", "documented_version"]
    if kind == "error":
        expected.append("error_domain")
    missing = tuple(key for key in expected if resolved.get(key) is None)
    if "documented_version" in missing:
        warnings += ("documented_version_unknown",)
    payload = {
        "kind": kind,
        "name": name,
        "topic_id": topic.id,
        "sources": citations,
        "missing_fields": missing,
        "warnings": warnings,
        **resolved,
    }
    identity = json.dumps(
        {"extractor_version": EXTRACTOR_VERSION, **payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda value: value.model_dump(mode="json"),
    )
    return TypedEntity.model_validate(
        {
            "id": "entity-" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            **payload,
        }
    )


def _errors(topic: Topic, context: _Context) -> list[TypedEntity]:
    entities: list[TypedEntity] = []
    for section in topic.sections:
        if section.kind != "table" or not section.rows:
            continue
        header = tuple(_label(cell) for cell in section.rows[0])
        aliases = {
            "errorcode": "error_code",
            "fehlercode": "error_code",
            "description": "description",
            "meaning": "description",
            "beschreibung": "description",
            "bedeutung": "description",
            "errordomain": "error_domain",
            "domain": "error_domain",
            "fehlerdomäne": "error_domain",
            "name": "name",
            "errorname": "name",
        }
        keys = tuple(aliases.get(cell) for cell in header)
        recognized = [key for key in keys if key is not None]
        if (
            "error_code" not in keys
            or "description" not in keys
            or len(set(recognized)) != len(recognized)
        ):
            continue
        for row in section.rows[1:]:
            if len(row) != len(keys):
                continue
            values = {
                key: value
                for key, value in zip(keys, row, strict=True)
                if key is not None
            }
            code = values["error_code"]
            description = values["description"]
            if (
                len(code) > 128
                or not _ERROR_CODE.fullmatch(code.strip())
                or not description.strip()
                or len(description) > 16_384
            ):
                continue
            fields: dict[str, str] = {"error_code": code, "description": description}
            domain = values.get("error_domain", "").strip()
            if domain:
                if len(domain) > 512:
                    raise EntityExtractionError("error domain exceeds bound")
                fields["error_domain"] = domain
            name = values.get("name", "").strip() or code.strip()
            if len(name) > 512:
                raise EntityExtractionError("error name exceeds bound")
            entities.append(
                _make(topic, "error", name, context, (section.source,), **fields)
            )
            if len(entities) > MAX_ENTITIES_PER_TOPIC:
                raise EntityExtractionError("entity count exceeds bound")
    return entities


def extract_entities(topic: Topic) -> tuple[TypedEntity, ...]:
    """Return facts from explicit evidence, or an empty tuple when unsupported."""
    topic = _checked_topic(topic)
    context, groups = _contexts(topic)
    entities: list[TypedEntity] = []
    for group in groups:
        resolved, _ = group.resolve()
        library = resolved["library"]
        if library is not None:
            entities.append(_make(topic, "library", library, group, ()))
    for section in topic.sections:
        if section.kind != "code" or _label(section.language or "") not in {
            "st",
            "iecst",
            "structuredtext",
        }:
            continue
        declaration = section.code or ""
        match = _DECLARATION.match(declaration)
        if match is None:
            continue
        keyword, name = match.groups()
        if topic.title.strip().casefold() not in {
            name.casefold(),
            f"{keyword} {name}".casefold(),
        }:
            continue
        entities.append(
            _make(
                topic,
                "symbol",
                name,
                context,
                (section.source,),
                declaration=declaration,
            )
        )
    entities.extend(_errors(topic, context))
    if len(entities) > MAX_ENTITIES_PER_TOPIC:
        raise EntityExtractionError("entity count exceeds bound")
    # Repeated identical table rows are one fact; different evidence is retained.
    unique = {entity.id: entity for entity in entities}
    return tuple(unique[key] for key in sorted(unique))


__all__ = ["EXTRACTOR_VERSION", "EntityExtractionError", "extract_entities"]
