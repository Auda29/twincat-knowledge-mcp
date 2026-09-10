"""Bounded, read-only reader for synthetic and operator-supplied InfoSys .mshc files.

The reader intentionally only understands XHTML article entries in a ZIP
container.  It does not execute, extract, fetch, or infer package metadata.
"""

from __future__ import annotations

import hashlib
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Literal, cast
from urllib.parse import parse_qs, unquote, urlsplit
from xml.etree.ElementTree import Element, TreeBuilder
from zipfile import BadZipFile, ZipFile, ZipInfo

from defusedxml import ElementTree as DefusedET
from pydantic import Field, StrictStr, model_validator

from twincat_knowledge.domain.models import Language, StrictModel
from twincat_knowledge.domain.provenance import SourceReference


class InfoSysError(ValueError):
    """Base class for controlled InfoSys input errors."""


class InfoSysArchiveError(InfoSysError):
    """The source is not a safe, readable ZIP archive."""


class InfoSysLimitError(InfoSysArchiveError):
    """An archive, entry, XML document, or source exceeded a configured limit."""


class InfoSysXmlError(InfoSysError):
    """An article is not safe, well-formed XHTML."""


class XMLDepthLimitError(InfoSysLimitError):
    """An XML document exceeded the configured element nesting depth."""


class UnsafeArchiveError(InfoSysArchiveError):
    """An archive entry is unsafe to address or is a symlink."""


@dataclass(frozen=True, slots=True)
class InfoSysLimits:
    """Resource limits applied before and during every archive read."""

    max_source_bytes: int = 64 * 1024 * 1024
    max_archive_entries: int = 10_000
    max_entry_bytes: int = 8 * 1024 * 1024
    max_aggregate_bytes: int = 256 * 1024 * 1024
    max_xml_depth: int = 128

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_archive_entries",
            "max_entry_bytes",
            "max_aggregate_bytes",
            "max_xml_depth",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


class InfoSysMetadata(StrictModel):
    """One ``meta`` element, retained in source order, including repeats."""

    name: StrictStr = Field(max_length=512)
    content: StrictStr = Field(max_length=16_384)
    attributes: tuple[tuple[StrictStr, StrictStr], ...] = ()


SectionKind = Literal["paragraph", "code", "table", "warning"]


class InfoSysSection(StrictModel):
    """One ordered, typed article section.

    Exactly one payload shape is used according to ``kind``.  Tables retain
    every row and cell boundary, including empty and whitespace-only cells.
    """

    kind: SectionKind
    text: StrictStr | None = None
    code: StrictStr | None = None
    language: StrictStr | None = Field(default=None, max_length=128)
    rows: tuple[tuple[StrictStr, ...], ...] = ()

    @model_validator(mode="after")
    def validate_payload(self) -> InfoSysSection:
        if self.kind in {"paragraph", "warning"}:
            if self.text is None or self.code is not None or self.rows:
                raise ValueError(f"{self.kind} section requires text only")
        elif self.kind == "code":
            if self.code is None or self.text is not None or self.rows:
                raise ValueError("code section requires code only")
        elif self.kind == "table":
            if self.rows is None or self.text is not None or self.code is not None:
                raise ValueError("table section requires rows only")
        return self

    @property
    def content(self) -> str | tuple[tuple[str, ...], ...]:
        """Return the payload without making the model mutable."""
        if self.kind == "table":
            return self.rows
        payload = self.text if self.kind in {"paragraph", "warning"} else self.code
        return cast(str, payload)


class InfoSysTopic(StrictModel):
    """Immutable structured representation of one XHTML article entry."""

    title: StrictStr = Field(max_length=4_096)
    topic_id: StrictStr | None = Field(default=None, max_length=512)
    language: Language
    library: StrictStr = Field(min_length=1, max_length=256)
    source: SourceReference
    metadata: tuple[InfoSysMetadata, ...] = ()
    sections: tuple[InfoSysSection, ...] = ()
    image_refs: tuple[StrictStr, ...] = ()
    help_ids: tuple[StrictStr, ...] = ()


SourceInput = str | Path | bytes | bytearray | memoryview | BinaryIO
LanguageFilter = Literal["de", "en", "any"] | None

# InfoSys uses Windows locale IDs in real .mshc paths.  Text locale directory
# names are accepted too; the library itself remains entirely path-derived.
_LOCALE_TO_LANGUAGE: dict[str, Language] = {
    "1031": "de",
    "1033": "en",
    "de": "de",
    "de-de": "de",
    "en": "en",
    "en-us": "en",
}
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_WINDOWS_DEVICE_NAMES = {
    "aux",
    "con",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _class_tokens(element: Element) -> set[str]:
    return {
        token.casefold() for token in (element.attrib.get("class", "").split()) if token
    }


def _is_warning(element: Element) -> bool:
    tag = _local_name(element.tag)
    tokens = _class_tokens(element)
    return (
        tag in {"warning", "caution", "important"}
        or bool(tokens & {"warning", "caution", "important"})
        or element.attrib.get("role", "").casefold() == "alert"
    )


def _is_code(element: Element) -> bool:
    tag = _local_name(element.tag)
    tokens = _class_tokens(element)
    return tag == "pre" or tag == "code" or "code" in tokens


def _render_inline(element: Element, *, br_newline: bool = True) -> str:
    """Render text while retaining tails, whitespace, and ``br`` boundaries."""

    parts: list[str] = []
    if element.text is not None:
        parts.append(element.text)
    for child in list(element):
        if _local_name(child.tag) == "br" and br_newline:
            parts.append("\n")
        else:
            parts.append(_render_inline(child, br_newline=br_newline))
        if child.tail is not None:
            parts.append(child.tail)
    return "".join(parts)


def _element_depth_limited(data: bytes, maximum: int) -> Element:
    class DepthLimitedTreeBuilder(TreeBuilder):
        depth = 0

        def start(self, tag: str, attrs: dict[str, str]) -> Element:
            self.depth += 1
            if self.depth > maximum:
                raise XMLDepthLimitError(f"XML element depth exceeds limit {maximum}")
            return super().start(tag, attrs)

        def end(self, tag: str) -> Element:
            element = super().end(tag)
            self.depth -= 1
            return element

    builder = DepthLimitedTreeBuilder()
    parser = DefusedET.XMLParser(
        target=builder,
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
    try:
        parser.feed(data)
        root = parser.close()
    except XMLDepthLimitError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize parser implementation errors
        raise InfoSysXmlError("InfoSys XHTML is malformed or unsafe") from exc
    if not isinstance(root, Element):
        raise InfoSysXmlError("InfoSys XHTML has no document element")
    return root


def _safe_entry_name(name: str, *, is_directory: bool) -> str | None:
    if not name or "\x00" in name or "\\" in name:
        raise UnsafeArchiveError("archive entry has an unsafe path")
    candidate = name[:-1] if is_directory and name.endswith("/") else name
    if not candidate:
        return None
    if candidate.startswith("/") or candidate.startswith("//"):
        raise UnsafeArchiveError("archive entry must be relative")
    if _DRIVE_PATTERN.match(candidate) or _LANGUAGE_PATTERN.match(candidate):
        raise UnsafeArchiveError("archive entry must not be a drive path or URI")

    decoded = candidate
    for _ in range(8):
        unquoted = unquote(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    else:
        raise UnsafeArchiveError("archive entry percent-decoding is too deep")
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        raise UnsafeArchiveError("archive entry contains a control character")
    decoded_path = decoded.split("#", 1)[0]
    if (
        decoded_path.startswith("/")
        or "\\" in decoded_path
        or _DRIVE_PATTERN.match(decoded_path)
        or _LANGUAGE_PATTERN.match(decoded_path)
    ):
        raise UnsafeArchiveError("archive entry must be a safe relative path")
    segments = decoded_path.split("/")
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise UnsafeArchiveError("archive entry must not contain traversal segments")
    if any(":" in segment for segment in segments):
        raise UnsafeArchiveError("archive entry must not contain ADS separators")
    for segment in segments:
        if segment.rstrip(" .").split(".", 1)[0].casefold() in _WINDOWS_DEVICE_NAMES:
            raise UnsafeArchiveError("archive entry must not contain device names")
    return candidate


def _entry_is_symlink(info: ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _read_limited(stream: BinaryIO, maximum: int, *, what: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, maximum - total + 1))
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise InfoSysArchiveError(f"{what} did not return bytes")
        total += len(chunk)
        if total > maximum:
            raise InfoSysLimitError(f"{what} exceeds limit {maximum} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _entry_language(parts: list[str]) -> Language | None:
    if len(parts) < 3:
        return None
    return _LOCALE_TO_LANGUAGE.get(parts[1].casefold())


def _entry_library(parts: list[str]) -> str | None:
    if len(parts) < 3 or not parts[0]:
        return None
    return parts[0]


def _metadata(root: Element) -> tuple[InfoSysMetadata, ...]:
    values: list[InfoSysMetadata] = []
    for element in root.iter():
        if _local_name(element.tag) != "meta":
            continue
        attributes = tuple(
            (str(key), str(value)) for key, value in element.attrib.items()
        )
        name = element.attrib.get("name", element.attrib.get("http-equiv", ""))
        content = element.attrib.get("content", "")
        values.append(
            InfoSysMetadata(name=name, content=content, attributes=attributes)
        )
    return tuple(values)


def _metadata_value(metadata: tuple[InfoSysMetadata, ...], name: str) -> str | None:
    folded = name.casefold()
    for item in metadata:
        if item.name.casefold() == folded and item.content:
            return item.content
    return None


def _table_rows(table: Element) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in table.iter():
        if _local_name(row.tag) != "tr":
            continue
        cells = tuple(
            _render_inline(cell)
            for cell in list(row)
            if _local_name(cell.tag) in {"td", "th"}
        )
        rows.append(cells)
    return tuple(rows)


def _sections(root: Element) -> tuple[InfoSysSection, ...]:
    parent: dict[int, Element] = {}
    for node in root.iter():
        for child in list(node):
            parent[id(child)] = node

    candidates: list[tuple[Element, SectionKind]] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag == "table":
            candidates.append((element, "table"))
        elif _is_warning(element):
            candidates.append((element, "warning"))
        elif _is_code(element):
            candidates.append((element, "code"))
        elif tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            candidates.append((element, "paragraph"))

    selected: list[tuple[Element, SectionKind]] = []
    candidate_ids = {id(element) for element, _ in candidates}
    for element, kind in candidates:
        current: Element | None = parent.get(id(element))
        nested = False
        while current is not None:
            if id(current) in candidate_ids:
                nested = True
                break
            next_parent = parent.get(id(current))
            current = next_parent
        if not nested:
            selected.append((element, kind))

    sections: list[InfoSysSection] = []
    for element, kind in selected:
        if kind == "table":
            sections.append(InfoSysSection(kind=kind, rows=_table_rows(element)))
        elif kind == "code":
            language = element.attrib.get("data-language")
            if language is None:
                for token in _class_tokens(element):
                    if token.startswith("language-"):
                        language = token.removeprefix("language-")
                        break
            sections.append(
                InfoSysSection(
                    kind=kind,
                    code=_render_inline(element),
                    language=language,
                )
            )
        else:
            sections.append(InfoSysSection(kind=kind, text=_render_inline(element)))
    return tuple(sections)


def _help_ids(root: Element) -> tuple[str, ...]:
    result: list[str] = []
    for element in root.iter():
        href = element.attrib.get("href")
        if href is None:
            continue
        try:
            parsed = urlsplit(href)
        except ValueError:
            continue
        if parsed.scheme.casefold() != "ms-xhelp":
            continue
        query = parse_qs(parsed.query, keep_blank_values=True)
        for key, values in query.items():
            if key.casefold() == "id":
                result.extend(value for value in values if value)
    return tuple(result)


def _image_refs(root: Element) -> tuple[str, ...]:
    result: list[str] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag == "img" and element.attrib.get("src"):
            result.append(element.attrib["src"])
        elif tag in {"object", "embed"} and element.attrib.get("data"):
            result.append(element.attrib["data"])
    return tuple(result)


def _topic_from_entry(
    locator: str,
    data: bytes,
    library: str,
    language: Language,
    *,
    source_id: str,
    snapshot_id: str,
    max_xml_depth: int,
) -> InfoSysTopic:
    root = _element_depth_limited(data, max_xml_depth)
    metadata = _metadata(root)
    title_element = next(
        (element for element in root.iter() if _local_name(element.tag) == "title"),
        None,
    )
    title = _render_inline(title_element).strip() if title_element is not None else ""
    if not title:
        title = (
            _metadata_value(metadata, "Microsoft.Help.Title")
            or locator.rsplit("/", 1)[-1]
        )
    topic_id = _metadata_value(metadata, "Microsoft.Help.Id")
    digest = hashlib.sha256(data).hexdigest()
    source = SourceReference(
        source_id=source_id,
        snapshot_id=snapshot_id,
        topic_id=topic_id,
        title=title,
        language=language,
        locator=locator,
        content_hash=digest,
    )
    return InfoSysTopic(
        title=title,
        topic_id=topic_id,
        language=language,
        library=library,
        source=source,
        metadata=metadata,
        sections=_sections(root),
        image_refs=_image_refs(root),
        help_ids=_help_ids(root),
    )


class InfoSysReader:
    """Read selected XHTML topics from a bounded .mshc ZIP source."""

    def __init__(
        self,
        source: SourceInput,
        *,
        source_id: str = "infosys",
        snapshot_id: str = "infosys-read",
        limits: InfoSysLimits | None = None,
    ) -> None:
        self._source = source
        self._source_id = source_id
        self._snapshot_id = snapshot_id
        self._limits = limits or InfoSysLimits()
        self._source_bytes: bytes | None = None

    def _source_payload(self) -> bytes:
        if self._source_bytes is not None:
            return self._source_bytes
        source = self._source
        try:
            if isinstance(source, (bytes, bytearray, memoryview)):
                data = bytes(source)
            elif isinstance(source, (str, Path)):
                with Path(source).open("rb") as handle:
                    data = _read_limited(
                        cast(BinaryIO, handle),
                        self._limits.max_source_bytes,
                        what="source",
                    )
            else:
                data = _read_limited(
                    source,
                    self._limits.max_source_bytes,
                    what="source",
                )
        except InfoSysError:
            raise
        except (OSError, TypeError) as exc:
            raise InfoSysArchiveError("unable to read InfoSys source") from exc
        if len(data) > self._limits.max_source_bytes:
            raise InfoSysLimitError("source exceeds configured byte limit")
        self._source_bytes = data
        return data

    def read(
        self,
        *,
        libraries: Iterable[str] | None = None,
        language: LanguageFilter = "any",
    ) -> tuple[InfoSysTopic, ...]:
        """Return topics in deterministic archive order, filtered by path."""

        if language not in {None, "de", "en", "any"}:
            raise ValueError("language must be 'de', 'en', 'any', or None")
        selected_libraries: frozenset[str] | None
        if isinstance(libraries, str):
            selected_libraries = frozenset({libraries})
        else:
            selected_libraries = None if libraries is None else frozenset(libraries)
        if selected_libraries is not None and any(
            not isinstance(item, str) or not item for item in selected_libraries
        ):
            raise ValueError("libraries must contain non-empty strings")

        payload = self._source_payload()
        try:
            archive = ZipFile(BytesIO(payload), "r")
        except (BadZipFile, OSError) as exc:
            raise InfoSysArchiveError("source is not a valid ZIP archive") from exc

        with archive:
            infos = archive.infolist()
            if len(infos) > self._limits.max_archive_entries:
                raise InfoSysLimitError("archive entry count exceeds configured limit")
            declared_total = sum(info.file_size for info in infos if not info.is_dir())
            if declared_total > self._limits.max_aggregate_bytes:
                raise InfoSysLimitError(
                    "declared archive bytes exceed configured limit"
                )

            seen: set[str] = set()
            canonical_seen: set[str] = set()
            validated: list[tuple[ZipInfo, str]] = []
            for info in infos:
                locator = _safe_entry_name(info.filename, is_directory=info.is_dir())
                if locator is None:
                    continue
                if locator in seen:
                    raise UnsafeArchiveError("archive contains duplicate entry names")
                seen.add(locator)
                if _entry_is_symlink(info):
                    raise UnsafeArchiveError("archive symlink entries are forbidden")
                canonical = unquote(locator).casefold()
                if canonical in canonical_seen:
                    raise UnsafeArchiveError("archive contains colliding entry names")
                canonical_seen.add(canonical)
                if info.file_size > self._limits.max_entry_bytes:
                    raise InfoSysLimitError(
                        f"entry {locator!r} exceeds configured byte limit"
                    )
                if info.is_dir():
                    continue
                validated.append((info, locator))

            topics: list[InfoSysTopic] = []
            actual_total = 0
            for info, locator in validated:
                try:
                    with archive.open(info, "r") as entry:
                        data = _read_limited(
                            cast(BinaryIO, entry),
                            self._limits.max_entry_bytes,
                            what=f"entry {locator!r}",
                        )
                except InfoSysError:
                    raise
                except (BadZipFile, OSError, RuntimeError) as exc:
                    raise InfoSysArchiveError(
                        f"unable to read archive entry {locator!r}"
                    ) from exc
                actual_total += len(data)
                if actual_total > self._limits.max_aggregate_bytes:
                    raise InfoSysLimitError(
                        "actual archive bytes exceed configured limit"
                    )

                if not locator.casefold().endswith((".html", ".htm", ".xhtml")):
                    continue
                parts = locator.split("/")
                entry_library = _entry_library(parts)
                entry_language = _entry_language(parts)
                if entry_library is None or entry_language is None:
                    continue
                if (
                    selected_libraries is not None
                    and entry_library not in selected_libraries
                ):
                    continue
                if language not in {None, "any", entry_language}:
                    continue
                topics.append(
                    _topic_from_entry(
                        locator,
                        data,
                        entry_library,
                        entry_language,
                        source_id=self._source_id,
                        snapshot_id=self._snapshot_id,
                        max_xml_depth=self._limits.max_xml_depth,
                    )
                )
            return tuple(topics)


def read_infosys(
    source: SourceInput,
    *,
    libraries: Iterable[str] | None = None,
    language: LanguageFilter = "any",
    source_id: str = "infosys",
    snapshot_id: str = "infosys-read",
    limits: InfoSysLimits | None = None,
) -> tuple[InfoSysTopic, ...]:
    """Convenience wrapper around :class:`InfoSysReader`."""

    return InfoSysReader(
        source,
        source_id=source_id,
        snapshot_id=snapshot_id,
        limits=limits,
    ).read(libraries=libraries, language=language)
