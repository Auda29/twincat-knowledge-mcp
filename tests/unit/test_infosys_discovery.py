"""RED-GREEN tests for bounded local InfoSys installation discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from twincat_knowledge.ingest.infosys_discovery import (
    DiscoveredInfoSysArchive,
    InfoSysDiscoveryAmbiguityError,
    InfoSysDiscoveryError,
    default_catalog_root,
    discover_infosys_archives,
    select_infosys_archive,
)


def _archive(root: Path, catalog: str, locale: str, name: str) -> Path:
    directory = root / catalog / "ContentStore" / locale
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    return path


def _standard_tree(root: Path) -> tuple[Path, Path]:
    english = _archive(
        root, "VisualStudio15", "EN-US", "BKINFOSYS3_VS_100_EN-US.47.mshc"
    )
    german = _archive(
        root, "VisualStudio15", "DE-DE", "BKINFOSYS3_VS_100_DE-DE.47.mshc"
    )
    return english, german


def test_discovers_archives_per_locale_in_deterministic_order(
    tmp_path: Path,
) -> None:
    english, german = _standard_tree(tmp_path)

    found = discover_infosys_archives(tmp_path, language="any")

    assert found == (
        DiscoveredInfoSysArchive(
            path=german, catalog="VisualStudio15", locale="DE-DE", language="de"
        ),
        DiscoveredInfoSysArchive(
            path=english, catalog="VisualStudio15", locale="EN-US", language="en"
        ),
    )


def test_language_filter_restricts_to_matching_locale(tmp_path: Path) -> None:
    english, _ = _standard_tree(tmp_path)

    found = discover_infosys_archives(tmp_path, language="en")

    assert tuple(item.path for item in found) == (english,)
    assert found[0].language == "en"


def test_unrelated_files_and_layouts_are_ignored(tmp_path: Path) -> None:
    english, _ = _standard_tree(tmp_path)
    locale_dir = english.parent
    (locale_dir / "BKINFOSYS3_VS_100_EN-US.47.mshi").write_bytes(b"index")
    (locale_dir / "OTHERVENDOR_EN-US.1.mshc").write_bytes(b"other")
    (locale_dir / "installedBooks.94.xml").write_bytes(b"<books/>")
    stray = tmp_path / "VisualStudio15" / "ContentStore" / "stray.mshc"
    stray.write_bytes(b"stray")
    (tmp_path / "not-a-catalog.txt").write_bytes(b"file, not a catalog directory")

    found = discover_infosys_archives(tmp_path, language="en")

    assert tuple(item.path for item in found) == (english,)


def test_selection_requires_exactly_one_candidate(tmp_path: Path) -> None:
    english, _ = _standard_tree(tmp_path)

    selected = select_infosys_archive(tmp_path, language="en")

    assert selected.path == english
    assert selected.language == "en"


def test_multiple_candidates_fail_explicitly_without_auto_selection(
    tmp_path: Path,
) -> None:
    _standard_tree(tmp_path)
    _archive(tmp_path, "VisualStudio17", "EN-US", "BKINFOSYS3_VS_100_EN-US.48.mshc")

    with pytest.raises(InfoSysDiscoveryAmbiguityError) as error:
        select_infosys_archive(tmp_path, language="en")
    message = str(error.value)
    assert "BKINFOSYS3_VS_100_EN-US.47.mshc" in message
    assert "BKINFOSYS3_VS_100_EN-US.48.mshc" in message


def test_missing_root_and_empty_root_raise_typed_errors(tmp_path: Path) -> None:
    with pytest.raises(InfoSysDiscoveryError, match="catalog root"):
        discover_infosys_archives(tmp_path / "missing", language="any")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert discover_infosys_archives(empty, language="any") == ()
    with pytest.raises(InfoSysDiscoveryError, match="No matching"):
        select_infosys_archive(empty, language="en")


def test_invalid_language_is_rejected(tmp_path: Path) -> None:
    _standard_tree(tmp_path)
    with pytest.raises(ValueError, match="language"):
        discover_infosys_archives(tmp_path, language="fr")  # type: ignore[arg-type]


def test_default_root_uses_program_data_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ProgramData", str(tmp_path))
    assert default_catalog_root() == tmp_path / "Microsoft" / "HelpLibrary2" / (
        "Catalogs"
    )
    monkeypatch.delenv("ProgramData", raising=False)
    assert default_catalog_root() is None
    with pytest.raises(InfoSysDiscoveryError, match="catalog root"):
        discover_infosys_archives(None, language="any")


def test_excessive_catalog_directories_are_rejected_not_truncated(
    tmp_path: Path,
) -> None:
    for index in range(257):
        (tmp_path / f"catalog-{index:03d}").mkdir()

    with pytest.raises(InfoSysDiscoveryError, match="catalog directory count"):
        discover_infosys_archives(tmp_path, language="any")
