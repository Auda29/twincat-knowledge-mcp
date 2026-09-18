"""Bounded operator pipeline from a local InfoSys archive to a topic package.

The pipeline composes the existing bounded components: source resolution via
:mod:`infosys_discovery` or an explicit path, the :mod:`infosys` reader,
:mod:`normalize`, and :func:`build_topic_package`. It reads only the selected
archive and writes only the new package directory. Rights remain an operator
statement: ``rights_reference`` records the operator's decision and is not a
vendor approval established by this code.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_package import build_topic_package
from twincat_knowledge.domain.models import EntityCounts, Language, SourceSnapshot

from .infosys import InfoSysLimits, read_infosys
from .infosys_discovery import InfoSysDiscoveryError, select_infosys_archive
from .normalize import normalize_infosys

PARSER_VERSION: Final = "infosys-mshc-reader-1"
NORMALIZER_VERSION: Final = "infosys-topic-normalizer-1"
_HASH_CHUNK_BYTES: Final = 1024 * 1024
# A full locally installed InfoSys locale holds several hundred MiB of
# selected XHTML; keep every other reader bound at its default.
_INGEST_AGGREGATE_BYTES: Final = 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InfoSysIngestResult:
    """Facts about one completed ingest run, safe to report to the operator."""

    package_path: Path
    manifest_sha256: str
    source_path: Path
    snapshot_id: str
    topic_count: int
    section_count: int
    language_counts: Mapping[str, int]
    library_counts: Mapping[str, int]
    inventory: InventoryBalance


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_source(
    source: Path | None, catalog_root: Path | None, language: Language
) -> Path:
    if source is not None:
        if not source.is_file():
            raise InfoSysDiscoveryError(
                "explicit source archive path is not a readable file"
            )
        return source
    return select_infosys_archive(catalog_root, language=language).path


def ingest_infosys_package(
    output: Path,
    *,
    source: Path | None,
    catalog_root: Path | None = None,
    language: Language,
    libraries: Sequence[str] | None,
    rights_reference: str,
    source_id: str = "infosys-local",
    snapshot_id: str | None = None,
    now: datetime | None = None,
) -> InfoSysIngestResult:
    """Build a new validated topic package from one local InfoSys archive.

    ``libraries=None`` selects every library of the chosen language. The
    inventory balance covers exactly that selected scope, not the whole
    archive or "all of Beckhoff".
    """

    archive = _resolved_source(source, catalog_root, language)
    selected_snapshot_id = snapshot_id if snapshot_id is not None else archive.stem
    imported_at = now if now is not None else datetime.now(UTC)
    content_hash = _archive_sha256(archive)
    raw_topics = read_infosys(
        archive,
        libraries=libraries,
        language=language,
        source_id=source_id,
        snapshot_id=selected_snapshot_id,
        limits=InfoSysLimits(max_selected_aggregate_bytes=_INGEST_AGGREGATE_BYTES),
    )
    snapshot = SourceSnapshot(
        source_id=source_id,
        snapshot_id=selected_snapshot_id,
        imported_at=imported_at,
        language=language,
        content_hash=content_hash,
        rights_reference=rights_reference,
        parser_version=PARSER_VERSION,
    )
    topics = normalize_infosys(raw_topics, (snapshot,))
    inventory = InventoryBalance(
        documents_total=len(topics),
        documents_imported=len(topics),
        documents_skipped=0,
        documents_failed=0,
    )
    manifest = CorpusManifest(
        package_schema_version="1.0",
        snapshot_id=selected_snapshot_id,
        created_at=imported_at,
        sources=(snapshot,),
        inventory=inventory,
        parser_version=PARSER_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        entity_counts=EntityCounts(
            topics=len(topics),
            sections=sum(len(topic.sections) for topic in topics),
        ),
        rights_reference=rights_reference,
    )
    result = build_topic_package(output, manifest, topics)
    return InfoSysIngestResult(
        package_path=result.path,
        manifest_sha256=result.manifest_sha256,
        source_path=archive,
        snapshot_id=selected_snapshot_id,
        topic_count=len(topics),
        section_count=sum(len(topic.sections) for topic in topics),
        language_counts=dict(result.manifest.language_counts),
        library_counts=dict(
            Counter(topic.library for topic in topics if topic.library is not None)
        ),
        inventory=inventory,
    )
