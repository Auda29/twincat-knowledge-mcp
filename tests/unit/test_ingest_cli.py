"""RED-GREEN tests for the operator ingest CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from twincat_knowledge.cli import main

_ARTICLE = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml">\n'
    "  <head><title>Example</title></head>\n"
    "  <body><p>PRIVATE_BODY</p></body>\n"
    "</html>\n"
)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "synthetic.mshc"
    with ZipFile(source, "w") as archive:
        archive.writestr("sample/1033/1.html", _ARTICLE)
        archive.writestr("other/1033/2.html", _ARTICLE.replace("Example", "Other"))
    return source


def test_ingest_builds_package_and_reports_no_paths_or_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    output = tmp_path / "package"

    exit_code = main(
        [
            "ingest",
            "--source",
            str(source),
            "--format",
            "infosys-mshc",
            "--output",
            str(output),
            "--language",
            "en",
            "--rights-reference",
            "local-synthetic-fixture",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    report = json.loads(captured.out)
    assert report["schema_version"] == "infosys-ingest-1"
    assert report["status"] == "ok"
    assert report["snapshot_id"] == "synthetic"
    assert report["topic_count"] == 2
    assert report["library_counts"] == {"other": 1, "sample": 1}
    assert report["inventory"] == {
        "documents_total": 2,
        "documents_imported": 2,
        "documents_skipped": 0,
        "documents_failed": 0,
    }
    assert len(report["manifest_sha256"]) == 64
    assert report["limitations"]
    assert (output / "manifest.json").is_file()
    assert str(tmp_path) not in captured.out
    assert "PRIVATE_" not in captured.out
    assert captured.err == ""


def test_ingest_selects_libraries_and_prints_text_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)

    exit_code = main(
        [
            "ingest",
            "--source",
            str(source),
            "--format",
            "infosys-mshc",
            "--output",
            str(tmp_path / "package"),
            "--language",
            "en",
            "--library",
            "sample",
            "--rights-reference",
            "local-synthetic-fixture",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status: ok" in captured.out
    assert "topics: 1" in captured.out
    assert "manifest_sha256: " in captured.out


def test_ingest_requires_rights_reference(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "ingest",
                "--source",
                str(_source(tmp_path)),
                "--format",
                "infosys-mshc",
                "--output",
                str(tmp_path / "package"),
                "--language",
                "en",
            ]
        )
    assert error.value.code == 2


def test_ingest_failure_is_controlled_without_path_leak(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.mshc"
    source.write_bytes(b"not a zip archive")

    exit_code = main(
        [
            "ingest",
            "--source",
            str(source),
            "--format",
            "infosys-mshc",
            "--output",
            str(tmp_path / "package"),
            "--language",
            "en",
            "--rights-reference",
            "local-synthetic-fixture",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "ingest failed" in captured.err
    assert str(tmp_path) not in captured.err
    assert not (tmp_path / "package").exists()
