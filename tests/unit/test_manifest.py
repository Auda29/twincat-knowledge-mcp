"""Synthetic tests for corpus manifest invariants."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot


SHA256 = "b" * 64


def snapshot(snapshot_id: str = "snapshot-1") -> SourceSnapshot:
    return SourceSnapshot(
        source_id="source-1",
        snapshot_id=snapshot_id,
        imported_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        documented_version=None,
        applicability="unknown",
        language="en",
        content_hash=SHA256,
        rights_reference="synthetic-fixture-approval",
        parser_version="parser-synthetic-1",
    )


def test_inventory_balance_must_reconcile() -> None:
    balance = InventoryBalance(
        documents_total=7,
        documents_imported=5,
        documents_skipped=1,
        documents_failed=1,
    )

    assert balance.documents_total == 7

    with pytest.raises(ValidationError):
        InventoryBalance(
            documents_total=7,
            documents_imported=5,
            documents_skipped=0,
            documents_failed=1,
        )


def test_inventory_counts_cannot_be_negative_or_unbounded() -> None:
    with pytest.raises(ValidationError):
        InventoryBalance(
            documents_total=-1,
            documents_imported=0,
            documents_skipped=0,
            documents_failed=0,
        )

    with pytest.raises(ValidationError):
        InventoryBalance(
            documents_total=10_000_001,
            documents_imported=10_000_001,
            documents_skipped=0,
            documents_failed=0,
        )

    with pytest.raises(ValidationError):
        InventoryBalance(
            documents_total=1,
            documents_imported=True,
            documents_skipped=0,
            documents_failed=0,
        )


def test_corpus_manifest_requires_schema_version_and_rejects_extra_fields() -> None:
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id="corpus-snapshot-1",
        created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        sources=(snapshot(),),
        inventory=InventoryBalance(
            documents_total=1,
            documents_imported=1,
            documents_skipped=0,
            documents_failed=0,
        ),
    )

    assert manifest.package_schema_version == "1.0"
    assert manifest.snapshot_id == "corpus-snapshot-1"

    with pytest.raises(ValidationError):
        CorpusManifest(
            package_schema_version="1.0",
            snapshot_id="corpus-snapshot-1",
            created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            sources=(snapshot(),),
            inventory=InventoryBalance(
                documents_total=1,
                documents_imported=1,
                documents_skipped=0,
                documents_failed=0,
            ),
            undocumented_claim="not allowed",
        )


def test_corpus_manifest_rejects_duplicate_snapshot_ids() -> None:
    with pytest.raises(ValidationError):
        CorpusManifest(
            package_schema_version="1.0",
            snapshot_id="corpus-snapshot-1",
            created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            sources=(snapshot("duplicate"), snapshot("duplicate")),
            inventory=InventoryBalance(
                documents_total=2,
                documents_imported=2,
                documents_skipped=0,
                documents_failed=0,
            ),
        )


def test_corpus_manifest_rejects_empty_sources_and_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        CorpusManifest(
            package_schema_version="1.0",
            snapshot_id="corpus-snapshot-1",
            created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            sources=(),
            inventory=InventoryBalance(
                documents_total=0,
                documents_imported=0,
                documents_skipped=0,
                documents_failed=0,
            ),
        )

    with pytest.raises(ValidationError):
        CorpusManifest(
            package_schema_version="1.0",
            snapshot_id="corpus-snapshot-1",
            created_at=datetime(2026, 9, 10),
            sources=(snapshot(),),
            inventory=InventoryBalance(
                documents_total=1,
                documents_imported=1,
                documents_skipped=0,
                documents_failed=0,
            ),
        )


def test_corpus_manifest_rejects_non_strict_schema_version() -> None:
    with pytest.raises(ValidationError):
        CorpusManifest(
            package_schema_version=1.0,
            snapshot_id="corpus-snapshot-1",
            created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            sources=(snapshot(),),
            inventory=InventoryBalance(
                documents_total=1,
                documents_imported=1,
                documents_skipped=0,
                documents_failed=0,
            ),
        )


def test_entity_counts_are_strictly_bounded() -> None:
    assert EntityCounts(topics=0, symbols=10_000_000).symbols == 10_000_000

    with pytest.raises(ValidationError):
        EntityCounts(topics=-1)

    with pytest.raises(ValidationError):
        EntityCounts(symbols=10_000_001)

    with pytest.raises(ValidationError):
        EntityCounts(devices=True)
