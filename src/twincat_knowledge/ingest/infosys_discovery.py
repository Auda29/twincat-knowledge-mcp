"""Bounded, read-only discovery of locally installed InfoSys ``.mshc`` archives.

Discovery mirrors the PowerShell diagnostic ``tools/Test-InfoSys.ps1``: scan
``<catalog root>/<catalog>/ContentStore/<locale>`` for Beckhoff InfoSys
archives named ``BKINFOSYS3*_<locale>*.mshc``. Candidate files are discovered,
not manifest-verified active packages; ``installedBooks.*.xml`` and registry
custom locations are not parsed. Ambiguity fails explicitly instead of
silently selecting a revision.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final, Literal

from .infosys import LanguageFilter

Language = Literal["de", "en"]

_LOCALE_TO_LANGUAGE: Final[dict[str, Language]] = {"DE-DE": "de", "EN-US": "en"}
MAX_CATALOG_DIRECTORIES: Final = 256


class InfoSysDiscoveryError(ValueError):
    """Local InfoSys discovery failed in a controlled way."""


class InfoSysDiscoveryAmbiguityError(InfoSysDiscoveryError):
    """More than one candidate archive matched; none was selected."""


@dataclass(frozen=True, slots=True)
class DiscoveredInfoSysArchive:
    """One candidate ``.mshc`` file found in a local Help Library catalog."""

    path: Path
    catalog: str
    locale: str
    language: Language


def default_catalog_root() -> Path | None:
    """Return the standard Help Library catalog root, if resolvable."""

    program_data = os.environ.get("ProgramData")
    if not program_data:
        return None
    return Path(program_data) / "Microsoft" / "HelpLibrary2" / "Catalogs"


def _checked_language(language: LanguageFilter) -> LanguageFilter:
    if language not in {None, "de", "en", "any"}:
        raise ValueError("language must be 'de', 'en', 'any', or None")
    return language


def _resolved_root(catalog_root: Path | None) -> Path:
    root = catalog_root if catalog_root is not None else default_catalog_root()
    if root is None or not root.is_dir():
        raise InfoSysDiscoveryError(
            "InfoSys catalog root not found; pass an explicit catalog root "
            "or source archive path"
        )
    return root


def _locale_candidates(
    locale_dir: Path, catalog: str, locale: str, language: Language
) -> list[DiscoveredInfoSysArchive]:
    pattern = f"bkinfosys3*_{locale.casefold()}*.mshc"
    candidates: list[DiscoveredInfoSysArchive] = []
    for entry in sorted(locale_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_file():
            continue
        if not fnmatchcase(entry.name.casefold(), pattern):
            continue
        candidates.append(
            DiscoveredInfoSysArchive(
                path=entry, catalog=catalog, locale=locale, language=language
            )
        )
    return candidates


def discover_infosys_archives(
    catalog_root: Path | None = None,
    *,
    language: LanguageFilter = "any",
) -> tuple[DiscoveredInfoSysArchive, ...]:
    """Return matching archives in deterministic catalog/locale/name order."""

    selected_language = _checked_language(language)
    root = _resolved_root(catalog_root)
    catalogs = sorted(
        (entry for entry in root.iterdir() if entry.is_dir()),
        key=lambda item: item.name,
    )
    if len(catalogs) > MAX_CATALOG_DIRECTORIES:
        raise InfoSysDiscoveryError(
            "catalog directory count exceeds the discovery limit"
        )
    found: list[DiscoveredInfoSysArchive] = []
    for catalog in catalogs:
        for locale, locale_language in sorted(_LOCALE_TO_LANGUAGE.items()):
            if selected_language not in {None, "any", locale_language}:
                continue
            locale_dir = catalog / "ContentStore" / locale
            if not locale_dir.is_dir():
                continue
            found.extend(
                _locale_candidates(locale_dir, catalog.name, locale, locale_language)
            )
    return tuple(found)


def select_infosys_archive(
    catalog_root: Path | None = None,
    *,
    language: LanguageFilter,
) -> DiscoveredInfoSysArchive:
    """Return the unique matching archive or fail without auto-selection."""

    found = discover_infosys_archives(catalog_root, language=language)
    if not found:
        raise InfoSysDiscoveryError(
            "No matching Beckhoff InfoSys archive found; pass an explicit "
            "source archive path"
        )
    if len(found) > 1:
        names = ", ".join(candidate.path.name for candidate in found)
        raise InfoSysDiscoveryAmbiguityError(
            "Multiple candidate archives found; pass an explicit source "
            f"archive path. No revision was selected automatically: {names}"
        )
    return found[0]
