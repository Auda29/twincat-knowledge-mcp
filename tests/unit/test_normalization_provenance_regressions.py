"""Public-boundary regressions from independent normalization review."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic
from twincat_knowledge.ingest.infosys import InfoSysSection, InfoSysTopic
from twincat_knowledge.ingest.normalize import normalize_infosys


def reader_topic() -> InfoSysTopic:
    return InfoSysTopic(
        title="Fixture",
        topic_id="help.fixture",
        library="sample",
        language="en",
        source=SourceReference(
            source_id="synthetic",
            snapshot_id="snapshot-1",
            language="en",
            title="Fixture",
            topic_id="help.fixture",
            locator="sample/1033/1.html",
            content_hash="a" * 64,
        ),
        sections=(InfoSysSection(kind="paragraph", text=" original text "),),
    )


def snapshot() -> SourceSnapshot:
    return SourceSnapshot(
        source_id="synthetic",
        snapshot_id="snapshot-1",
        language="en",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash="b" * 64,
        rights_reference="original synthetic fixture",
        parser_version="fixture",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("language", "de"),
        ("original_topic_id", "another-topic"),
    ],
)
def test_topic_json_rejects_inconsistent_source(field, value):
    topic = normalize_infosys((reader_topic(),), (snapshot(),))[0]
    payload = topic.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        Topic.model_validate_json(json.dumps(payload))


def test_section_json_rejects_inconsistent_section_id():
    section = normalize_infosys((reader_topic(),), (snapshot(),))[0].sections[0]
    payload = section.model_dump(mode="json")
    payload["source"]["section_id"] = "different-section"
    with pytest.raises(ValidationError):
        Section.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "another-source"),
        ("snapshot_id", "another-snapshot"),
        ("language", "de"),
        ("topic_id", "another-topic"),
        ("locator", "sample/1033/other.html"),
        ("content_hash", "c" * 64),
        ("canonical_url", "https://example.invalid/other"),
        ("title", "Other"),
    ],
)
def test_topic_json_rejects_foreign_section_provenance(field, value):
    topic = normalize_infosys((reader_topic(),), (snapshot(),))[0]
    payload = topic.model_dump(mode="json")
    payload["sections"][0]["source"][field] = value
    with pytest.raises(ValidationError):
        Topic.model_validate_json(json.dumps(payload))


def test_topic_json_rejects_section_scoped_article_reference():
    topic = normalize_infosys((reader_topic(),), (snapshot(),))[0]
    payload = topic.model_dump(mode="json")
    payload["source"]["section_id"] = "not-an-article-reference"
    with pytest.raises(ValidationError):
        Topic.model_validate_json(json.dumps(payload))


def test_topic_json_rejects_duplicate_section_ids():
    topic = normalize_infosys((reader_topic(),), (snapshot(),))[0]
    payload = topic.model_dump(mode="json")
    payload["sections"].append(payload["sections"][0])
    with pytest.raises(ValidationError):
        Topic.model_validate_json(json.dumps(payload))


def test_raw_metadata_survives_reader_normalizer_json_without_claim_inference():
    from io import BytesIO
    from zipfile import ZipFile

    from twincat_knowledge.ingest.infosys import read_infosys

    archive = BytesIO()
    with ZipFile(archive, "w") as handle:
        handle.writestr(
            "sample/1033/1.html",
            (
                "<html><head><title>Fixture</title>"
                '<meta name="Microsoft.Help.Version" content="unverified version A"/>'
                '<meta name="Microsoft.Help.Version" content=" conflicting B " '
                'data-original="  keep  "/>'
                "</head><body><article><p>original</p></article></body></html>"
            ),
        )
    raw = read_infosys(
        archive.getvalue(), source_id="synthetic", snapshot_id="snapshot-1"
    )
    source_snapshot = snapshot()
    normalized = normalize_infosys(raw, (source_snapshot,))[0]
    assert "metadata" in normalized.model_dump()
    assert [x.model_dump() for x in normalized.metadata] == [
        x.model_dump() for x in raw[0].metadata
    ]
    restored = Topic.model_validate_json(normalized.model_dump_json())
    assert restored.metadata == normalized.metadata
    assert len(restored.metadata) == 2
    assert source_snapshot.applicability == "unknown"
    assert source_snapshot.documented_version is None
    with pytest.raises(ValidationError):
        restored.metadata[0].content = "modified"


def test_normalizer_rejects_source_title_disagreement():
    from twincat_knowledge.ingest.normalize import TopicNormalizationError

    payload = reader_topic().model_dump(mode="json")
    payload["source"]["title"] = "unrelated source title"
    raw = InfoSysTopic.model_validate_json(json.dumps(payload))
    with pytest.raises(TopicNormalizationError, match="title"):
        normalize_infosys((raw,), (snapshot(),))


def test_topic_json_rejects_source_title_disagreement():
    topic = normalize_infosys((reader_topic(),), (snapshot(),))[0]
    payload = topic.model_dump(mode="json")
    payload["title"] = "unrelated title"
    with pytest.raises(ValidationError, match="title"):
        Topic.model_validate_json(json.dumps(payload))


def test_absent_source_title_remains_unknown():
    payload = reader_topic().model_dump(mode="json")
    payload["source"]["title"] = None
    raw = InfoSysTopic.model_validate_json(json.dumps(payload))
    normalized = normalize_infosys((raw,), (snapshot(),))[0]
    assert normalized.title == "Fixture"
    assert normalized.source.title is None
    assert normalized.sections[0].source.title is None
    assert Topic.model_validate_json(normalized.model_dump_json()) == normalized
