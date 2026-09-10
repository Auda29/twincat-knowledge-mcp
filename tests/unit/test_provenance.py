"""Synthetic tests for strict provenance primitives."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from twincat_knowledge.domain.models import SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference

SHA256 = "a" * 64


def test_source_reference_preserves_opaque_ids_and_provenance_fields() -> None:
    reference = SourceReference(
        source_id="opaque/source-01",
        snapshot_id="opaque-snapshot-01",
        topic_id="topic-7",
        section_id="section-parameters",
        title="Synthetic topic",
        language="de",
        canonical_url="https://example.invalid/docs/topic-7",
        locator="topics/topic-7.html#parameters",
        content_hash=SHA256,
    )

    assert reference.source_id == "opaque/source-01"
    assert reference.language == "de"
    assert str(reference.canonical_url) == "https://example.invalid/docs/topic-7"
    assert reference.locator == "topics/topic-7.html#parameters"
    assert reference.content_hash == SHA256


def test_source_reference_allows_explicit_none_and_json_roundtrip() -> None:
    reference = SourceReference(
        source_id="source",
        snapshot_id="snapshot",
        language="en",
        canonical_url=None,
        locator="topic.html",
        content_hash=SHA256,
    )

    restored = SourceReference.model_validate_json(reference.model_dump_json())

    assert restored == reference
    assert restored.canonical_url is None


def test_source_reference_rejects_controls_after_percent_decoding() -> None:
    for locator in (
        "topic%00.html",
        "topic%0a.html",
        "topic%0d.html",
        "topic%2500.html",
        "topic%250a.html",
        "topic%25250a.html",
    ):
        with pytest.raises(ValidationError):
            SourceReference(
                source_id="source",
                snapshot_id="snapshot",
                language="en",
                locator=locator,
                content_hash=SHA256,
            )


def test_source_reference_rejects_fourfold_encoded_traversal() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            source_id="source",
            snapshot_id="snapshot",
            language="en",
            locator="topics/%2525252e%2525252e/secret.html",
            content_hash=SHA256,
        )


def test_source_reference_rejects_windows_ads_and_device_names() -> None:
    for locator in (
        "docs/topic.html:stream",
        "docs/topic.html%3Astream",
        "docs/CON",
        "docs/con.txt",
        "docs/NUL",
        "docs/NUL.txt",
        "docs/AUX.",
        "docs/PRN ",
        "docs/COM1.log",
        "docs/LPT1. ",
    ):
        with pytest.raises(ValidationError):
            SourceReference(
                source_id="source",
                snapshot_id="snapshot",
                language="en",
                locator=locator,
                content_hash=SHA256,
            )


def test_source_reference_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            source_id="source",
            snapshot_id="snapshot",
            language="en",
            locator="topic.html",
            content_hash=SHA256,
            invented_field="not allowed",
        )


@pytest.mark.parametrize(
    "locator",
    [
        "../outside.html",
        "topics/../../outside.html",
        "topics/%2e%2e/outside.html",
        "/absolute/topic.html",
        "//server/share/topic.html",
        r"\\server\share\topic.html",
        r"C:\\topic.html",
        "C:/topic.html",
    ],
)
def test_source_reference_rejects_unsafe_relative_locators(locator: str) -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            source_id="source",
            snapshot_id="snapshot",
            language="en",
            locator=locator,
            content_hash=SHA256,
        )


@pytest.mark.parametrize(
    "content_hash",
    ["", "a" * 63, "a" * 65, "g" * 64, "sha256:" + "a" * 64, 123],
)
def test_source_reference_rejects_invalid_sha256(content_hash: object) -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            source_id="source",
            snapshot_id="snapshot",
            language="en",
            locator="topic.html",
            content_hash=content_hash,
        )


def test_source_reference_rejects_invalid_language_and_url() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            source_id="source",
            snapshot_id="snapshot",
            language="fr",
            locator="topic.html",
            content_hash=SHA256,
        )

    with pytest.raises(ValidationError):
        SourceReference(
            source_id="source",
            snapshot_id="snapshot",
            language="en",
            canonical_url="file:///etc/passwd",
            locator="topic.html",
            content_hash=SHA256,
        )


def test_source_snapshot_keeps_unknown_documented_version_explicit() -> None:
    snapshot = SourceSnapshot(
        source_id="source",
        snapshot_id="snapshot",
        imported_at=datetime(2026, 9, 10, tzinfo=UTC),
        documented_version=None,
        applicability="unknown",
        language="en",
        content_hash=SHA256,
        rights_reference="synthetic-fixture-approval",
        parser_version="parser-synthetic-1",
    )

    assert snapshot.documented_version is None
    assert snapshot.applicability == "unknown"


def test_source_snapshot_rejects_claimed_validity_without_version() -> None:
    with pytest.raises(ValidationError):
        SourceSnapshot(
            source_id="source",
            snapshot_id="snapshot",
            imported_at=datetime(2026, 9, 10, tzinfo=UTC),
            documented_version=None,
            applicability="known",
            language="en",
            content_hash=SHA256,
            rights_reference="synthetic-fixture-approval",
            parser_version="parser-synthetic-1",
        )


def test_source_snapshot_rejects_naive_import_time() -> None:
    with pytest.raises(ValidationError):
        SourceSnapshot(
            source_id="source",
            snapshot_id="snapshot",
            imported_at=datetime(2026, 9, 10),
            language="en",
            content_hash=SHA256,
            rights_reference="synthetic-fixture-approval",
            parser_version="parser-synthetic-1",
        )
