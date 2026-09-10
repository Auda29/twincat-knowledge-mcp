"""Strict corpus-manifest models; no readers, importers, or network access."""

from typing import Annotated

from pydantic import Field, StrictStr, model_validator

from twincat_knowledge.domain.errors import (
    DuplicateIdentifierError,
    InventoryBalanceError,
)
from twincat_knowledge.domain.models import (
    AwareDateTime,
    EntityCounts,
    MAX_COUNT,
    MAX_SNAPSHOTS,
    OpaqueId,
    ReferenceText,
    StrictModel,
    VersionText,
    SourceSnapshot,
)


BoundedCount = Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)]
BoundedText = Annotated[
    StrictStr,
    Field(min_length=1, max_length=512),
]


class InventoryBalance(StrictModel):
    """Reconciled document inventory for one corpus build."""

    documents_total: BoundedCount
    documents_imported: BoundedCount
    documents_skipped: BoundedCount
    documents_failed: BoundedCount

    @model_validator(mode="after")
    def reconcile(self) -> "InventoryBalance":
        accounted_for = (
            self.documents_imported
            + self.documents_skipped
            + self.documents_failed
        )
        if accounted_for != self.documents_total:
            raise InventoryBalanceError(
                "documents_total must equal imported + skipped + failed"
            )
        return self


class CorpusManifest(StrictModel):
    """Manifest for a validated corpus generation.

    A missing optional version field means that the corresponding toolchain
    version is not recorded here; it is never replaced with a guessed value.
    ``sources`` is metadata only: this model performs no file or network I/O.
    """

    package_schema_version: VersionText
    snapshot_id: OpaqueId
    created_at: AwareDateTime
    sources: tuple[SourceSnapshot, ...] = Field(
        min_length=1,
        max_length=MAX_SNAPSHOTS,
    )
    inventory: InventoryBalance
    parser_version: VersionText | None = None
    normalizer_version: VersionText | None = None
    indexer_version: VersionText | None = None
    entity_counts: EntityCounts | None = None
    unsupported_formats: tuple[BoundedText, ...] = Field(default=(), max_length=MAX_SNAPSHOTS)
    missing_contents: tuple[BoundedText, ...] = Field(default=(), max_length=MAX_SNAPSHOTS)
    rights_reference: ReferenceText | None = None

    @model_validator(mode="after")
    def reject_duplicate_snapshot_ids(self) -> "CorpusManifest":
        snapshot_ids = [source.snapshot_id for source in self.sources]
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise DuplicateIdentifierError(
                "sources must not contain duplicate snapshot_id values"
            )
        return self
