"""Synthetic-only evidence and refusal cases for typed extraction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from twincat_knowledge.domain.entities import TypedEntity
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.ingest.entities import (
    MAX_CODE_CHARS,
    MAX_TABLE_CELLS,
    MAX_TOPIC_BYTES,
    EntityExtractionError,
    extract_entities,
)


def _topic(
    title: str = "FB_Demo",
    *,
    code: str | None = "FUNCTION_BLOCK FB_Demo\nEND_FUNCTION_BLOCK",
    language: str | None = "st",
    rows: tuple[tuple[str, ...], ...] = (),
    metadata: tuple[tuple[str, str], ...] = (),
    topic_id: str = "topic-demo",
    snapshot: str = "snapshot-synthetic",
    locator: str = "Tc3_Guessed/3.1.4026/demo.html",
) -> Topic:
    source = SourceReference(
        source_id="synthetic",
        snapshot_id=snapshot,
        topic_id="help.demo",
        title=title,
        language="en",
        locator=locator,
        content_hash="a" * 64,
    )
    sections: list[Section] = []
    if code is not None:
        section_id = topic_id + "-code"
        sections.append(
            Section(
                id=section_id,
                kind="code",
                code=code,
                language=language,
                source=source.model_copy(update={"section_id": section_id}),
            )
        )
    if rows:
        section_id = topic_id + "-table"
        sections.append(
            Section(
                id=section_id,
                kind="table",
                rows=rows,
                source=source.model_copy(update={"section_id": section_id}),
            )
        )
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id="help.demo",
        library="guessed-source-routing-name",
        language="en",
        source=source,
        sections=tuple(sections),
        metadata=tuple(
            TopicMetadata(name=name, content=value) for name, value in metadata
        ),
    )


def test_symbol_retains_exact_declaration_and_source_fields() -> None:
    declaration = (
        "  FUNCTION_BLOCK FB_Demo\r\nVAR_INPUT\r\n x : BOOL; // exact\r\nEND_VAR\r\n"
    )
    topic = _topic(
        code=declaration,
        metadata=(
            ("Library", "Tc2_Explicit"),
            ("Namespace", "Explicit"),
            ("LibraryVersion", "1.2.3"),
        ),
    )
    result = extract_entities(topic)
    symbol = next(entity for entity in result if entity.kind == "symbol")
    assert symbol.name == "FB_Demo"
    assert symbol.declaration == declaration
    assert symbol.topic_id == topic.id
    assert symbol.library == "Tc2_Explicit"
    assert symbol.namespace == "Explicit"
    assert symbol.documented_version == "1.2.3"
    assert symbol.missing_fields == symbol.warnings == ()
    assert symbol.sources == (topic.sections[0].source, topic.source)
    assert symbol.sources[0].topic_id == "help.demo"
    assert symbol.sources[0].content_hash == "a" * 64
    assert symbol == TypedEntity.model_validate_json(symbol.model_dump_json())
    with pytest.raises(ValidationError):
        symbol.name = "changed"  # type: ignore[misc]


def test_directory_and_routing_library_and_build_hints_never_become_facts() -> None:
    topic = _topic(metadata=(("ProductVersion", "3.1.4026"), ("Version", "9.9")))
    (symbol,) = extract_entities(topic)
    assert symbol.namespace is symbol.library is symbol.documented_version is None
    assert symbol.missing_fields == ("namespace", "library", "documented_version")
    assert "documented_version_unknown" in symbol.warnings


@pytest.mark.parametrize(
    ("title", "code", "language"),
    [
        ("How to call FB_Demo", "FUNCTION_BLOCK FB_Demo", "st"),
        ("FB_Other", "FUNCTION_BLOCK FB_Demo", "st"),
        ("FB_Demo", "call(FB_Demo);", "st"),
        ("FB_Demo", "x := 1;\nFUNCTION_BLOCK FB_Demo", "st"),
        ("FB_Demo", "// FUNCTION_BLOCK FB_Demo\nx := 1;", "st"),
        ("FB_Demo", "FUNCTION_BLOCK FB_Demo", "python"),
        ("FB_Demo", "FUNCTION_BLOCK FB_Demo", None),
    ],
)
def test_mentions_samples_and_other_languages_do_not_create_symbols(
    title: str,
    code: str,
    language: str | None,
) -> None:
    assert extract_entities(_topic(title, code=code, language=language)) == ()


def test_paragraph_keywords_are_not_entities() -> None:
    topic = _topic("Library Tc2_Foo error code 1792", code=None)
    section_id = topic.id + "-paragraph"
    paragraph = Section(
        id=section_id,
        kind="paragraph",
        text="FUNCTION_BLOCK FB_X Tc2_Foo 0x700 version 3.1",
        source=topic.source.model_copy(update={"section_id": section_id}),
    )
    assert extract_entities(topic.model_copy(update={"sections": (paragraph,)})) == ()


def test_conflicting_explicit_context_stays_unknown() -> None:
    topic = _topic(
        metadata=(
            ("Library", "LibA"),
            ("Library", "LibB"),
            ("Namespace", "A"),
            ("Namespace", "B"),
            ("LibraryVersion", "1.0"),
            ("LibraryVersion", "2.0"),
        )
    )
    (symbol,) = extract_entities(topic)
    assert symbol.namespace is symbol.library is symbol.documented_version is None
    assert set(symbol.warnings) == {
        "ambiguous_namespace",
        "ambiguous_library",
        "ambiguous_documented_version",
        "documented_version_unknown",
    }


def test_explicit_library_table_keeps_rows_and_versions_separate() -> None:
    topic = _topic(
        code=None,
        rows=(
            ("Library", "Namespace", "Version"),
            ("LibA", "A", "1.0"),
            ("LibB", "B", "2.0"),
        ),
    )
    libraries = extract_entities(topic)
    assert {(e.library, e.namespace, e.documented_version) for e in libraries} == {
        ("LibA", "A", "1.0"),
        ("LibB", "B", "2.0"),
    }
    assert all(
        e.kind == "library" and e.sources == (topic.sections[0].source,)
        for e in libraries
    )


def test_property_table_version_requires_explicit_library_in_same_table() -> None:
    topic = _topic(rows=(("Field", "Value"), ("Version", "3.1")))
    (symbol,) = extract_entities(topic)
    assert symbol.documented_version is None
    explicit = _topic(
        rows=(
            ("Property", "Value"),
            ("Library", "LibA"),
            ("Version", "7.1"),
        )
    )
    assert all(
        entity.documented_version == "7.1" for entity in extract_entities(explicit)
    )


def test_library_column_rows_never_supply_article_context_or_cross_row_facts() -> None:
    topic = _topic(
        rows=(
            ("Library", "Namespace", "Version"),
            ("LibA", "", "1.0"),
            ("", "NsB", ""),
        )
    )
    entities = extract_entities(topic)
    (symbol,) = (entity for entity in entities if entity.kind == "symbol")
    (library,) = (entity for entity in entities if entity.kind == "library")
    assert symbol.library is symbol.namespace is symbol.documented_version is None
    assert library.library == "LibA"
    assert library.namespace is None
    assert library.documented_version == "1.0"


def test_single_library_column_row_does_not_assert_symbol_membership() -> None:
    entities = extract_entities(
        _topic(
            rows=(
                ("Library", "Namespace", "Version"),
                ("LibA", "NsA", "1.0"),
            )
        )
    )
    (symbol,) = (entity for entity in entities if entity.kind == "symbol")
    assert symbol.library is symbol.namespace is symbol.documented_version is None


def test_exact_error_codes_and_equal_codes_across_domains_are_preserved() -> None:
    topic = _topic(
        "Error codes",
        code=None,
        rows=(
            ("Error code", "Error domain", "Description", "Name"),
            ("0x0001", "ADS", "Exact ADS text", "BadInput"),
            ("0x0001", "NC", "Exact NC text", "BadInput"),
            ("16#0001", "PLC", "IEC text", "IecError"),
            ("0001", "PLC", "Decimal text", "DecimalError"),
        ),
    )
    errors = extract_entities(topic)
    assert len({entity.id for entity in errors}) == 4
    assert {(e.error_code, e.error_domain) for e in errors} == {
        ("0x0001", "ADS"),
        ("0x0001", "NC"),
        ("16#0001", "PLC"),
        ("0001", "PLC"),
    }
    assert all(e.sources == (topic.sections[0].source,) for e in errors)


@pytest.mark.parametrize(
    "rows",
    [
        (("Code", "Description"), ("0x700", "A description")),
        (("Error code", "Example"), ("0x700", "x := 1")),
        (("Error code", "Description"), ("maybe 0x700", "Mention")),
        (("Error code", "Description"), ("0xGG", "Malformed")),
        (("Error code", "Description"), ("0x700", "")),
        (("Error code", "Error code", "Description"), ("1", "2", "Ambiguous")),
        (("Library", "Library", "Version"), ("A", "B", "3")),
    ],
)
def test_unstructured_malformed_or_ambiguous_tables_create_no_facts(
    rows: tuple[tuple[str, ...], ...],
) -> None:
    assert extract_entities(_topic(code=None, rows=rows)) == ()


def test_unknown_error_domain_is_explicit_and_never_guessed_from_title() -> None:
    (error,) = extract_entities(
        _topic(
            "ADS errors",
            code=None,
            rows=(
                ("Error code", "Description"),
                ("1792", "An explicit description"),
            ),
        )
    )
    assert error.error_domain is None
    assert "error_domain" in error.missing_fields


def test_ids_are_deterministic_and_include_snapshot_evidence_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = _topic()
    first = extract_entities(topic)
    assert first == extract_entities(topic)
    assert first[0].id != extract_entities(_topic(snapshot="snapshot-other"))[0].id
    assert (
        first[0].id
        != extract_entities(_topic(code="FUNCTION_BLOCK FB_Demo\n// changed"))[0].id
    )
    monkeypatch.setattr(
        "twincat_knowledge.ingest.entities.EXTRACTOR_VERSION", "test-version-2"
    )
    assert first[0].id != extract_entities(topic)[0].id


def test_extraction_revalidates_model_copy_and_fails_closed_on_bounds() -> None:
    topic = _topic()
    with pytest.raises(EntityExtractionError):
        extract_entities(topic.model_copy(update={"title": "different"}))
    with pytest.raises(EntityExtractionError):
        extract_entities(_topic(code="x" * (MAX_CODE_CHARS + 1)))
    with pytest.raises(EntityExtractionError):
        extract_entities(_topic(code=None, rows=(("x",) * (MAX_TABLE_CELLS + 1),)))
    with pytest.raises(EntityExtractionError):
        extract_entities(_topic(code=None, rows=(("x" * (MAX_TOPIC_BYTES + 1),),)))
