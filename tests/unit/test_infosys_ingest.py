"""RED-GREEN tests for the InfoSys-to-topic-package ingest pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.ingest.infosys import InfoSysError
from twincat_knowledge.ingest.infosys_discovery import InfoSysDiscoveryError
from twincat_knowledge.ingest.infosys_ingest import (
    InfoSysIngestResult,
    ingest_infosys_package,
)

_NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _article(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"  <head><title>{title}</title></head>\n"
        f"  <body><p>{body}</p></body>\n"
        "</html>\n"
    )


def _write_archive(path: Path, entries: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content.encode("utf-8"))
    return path


def _standard_entries() -> dict[str, str]:
    return {
        "tcplclib_alpha/1033/move.html": _article("Move", "Move an axis."),
        "tcplclib_alpha/1033/stop.html": _article("Stop", "Stop an axis."),
        "tcplclib_beta/1033/index.html": _article("Beta", "Beta overview."),
    }


def test_ingest_builds_validatable_package_from_explicit_source(
    tmp_path: Path,
) -> None:
    source = _write_archive(tmp_path / "synthetic.mshc", _standard_entries())
    output = tmp_path / "package"

    result = ingest_infosys_package(
        output,
        source=source,
        language="en",
        libraries=None,
        rights_reference="local-synthetic-fixture",
        now=_NOW,
    )

    assert isinstance(result, InfoSysIngestResult)
    assert result.package_path == output
    assert result.snapshot_id == "synthetic"
    assert result.topic_count == 3
    assert result.section_count == 3
    assert dict(result.language_counts) == {"en": 3}
    assert result.library_counts == {"tcplclib_alpha": 2, "tcplclib_beta": 1}
    cache = tmp_path / "cache"
    cache.mkdir()
    with load_topic_package(
        output, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    ) as loaded:
        assert loaded.summary.topic_count == 3
        manifest = loaded.manifest.corpus_manifest
    assert manifest.snapshot_id == "synthetic"
    assert manifest.inventory.documents_total == 3
    assert manifest.inventory.documents_imported == 3
    assert manifest.inventory.documents_failed == 0
    assert manifest.sources[0].rights_reference == "local-synthetic-fixture"
    assert manifest.sources[0].language == "en"
    assert manifest.parser_version is not None
    assert manifest.normalizer_version is not None


def test_ingest_restricts_to_selected_libraries(tmp_path: Path) -> None:
    source = _write_archive(tmp_path / "synthetic.mshc", _standard_entries())

    result = ingest_infosys_package(
        tmp_path / "package",
        source=source,
        language="en",
        libraries=("tcplclib_alpha",),
        rights_reference="local-synthetic-fixture",
        now=_NOW,
    )

    assert result.topic_count == 2
    assert result.library_counts == {"tcplclib_alpha": 2}
    assert result.inventory.documents_total == 2


def test_ingest_discovers_source_when_omitted(tmp_path: Path) -> None:
    catalog_root = tmp_path / "Catalogs"
    archive = catalog_root / "VisualStudio15" / "ContentStore" / "EN-US"
    _write_archive(archive / "BKINFOSYS3_VS_100_EN-US.47.mshc", _standard_entries())

    result = ingest_infosys_package(
        tmp_path / "package",
        source=None,
        catalog_root=catalog_root,
        language="en",
        libraries=None,
        rights_reference="local-installed-infosys",
        now=_NOW,
    )

    assert result.snapshot_id == "BKINFOSYS3_VS_100_EN-US.47"
    assert result.source_path.name == "BKINFOSYS3_VS_100_EN-US.47.mshc"
    assert result.topic_count == 3


def test_ingest_source_hash_binds_to_archive_bytes(tmp_path: Path) -> None:
    import hashlib

    source = _write_archive(tmp_path / "synthetic.mshc", _standard_entries())
    expected = hashlib.sha256(source.read_bytes()).hexdigest()

    result = ingest_infosys_package(
        tmp_path / "package",
        source=source,
        language="en",
        libraries=None,
        rights_reference="local-synthetic-fixture",
        now=_NOW,
    )

    cache = tmp_path / "cache"
    cache.mkdir()
    with load_topic_package(
        result.package_path,
        expected_manifest_sha256=result.manifest_sha256,
        cache_dir=cache,
    ) as loaded:
        sources = loaded.manifest.corpus_manifest.sources
        assert sources[0].content_hash == expected


def test_ingest_fails_controlled_without_source_or_discovery(
    tmp_path: Path,
) -> None:
    empty_root = tmp_path / "Catalogs"
    empty_root.mkdir()
    with pytest.raises(InfoSysDiscoveryError):
        ingest_infosys_package(
            tmp_path / "package",
            source=None,
            catalog_root=empty_root,
            language="en",
            libraries=None,
            rights_reference="local-installed-infosys",
            now=_NOW,
        )
    assert not (tmp_path / "package").exists()


def test_ingest_rejects_unreadable_source_without_partial_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "broken.mshc"
    source.write_bytes(b"this is not a zip archive")
    with pytest.raises(InfoSysError):
        ingest_infosys_package(
            tmp_path / "package",
            source=source,
            language="en",
            libraries=None,
            rights_reference="local-synthetic-fixture",
            now=_NOW,
        )
    assert not (tmp_path / "package").exists()
