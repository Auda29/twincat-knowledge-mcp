from __future__ import annotations

import json
from zipfile import ZipFile

from twincat_knowledge.cli import main


def test_inspect_reports_scoped_metadata_without_content(tmp_path, capsys):
    source = tmp_path / "synthetic.mshc"
    with ZipFile(source, "w") as archive:
        archive.writestr(
            "sample/1033/1.html",
            "<html><head><title>Example</title></head><body><article><p>PRIVATE_BODY</p><pre>PRIVATE_CODE</pre></article></body></html>",
        )
    before = source.read_bytes()
    assert (
        main(
            [
                "inspect-infosys",
                "--source",
                str(source),
                "--library",
                "sample",
                "--language",
                "en",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["status"] == "ok"
    assert result["total"] == 1
    assert result["topics"][0]["title"] == "Example"
    assert result["topics"][0]["locator"] == "sample/1033/1.html"
    assert len(result["topics"][0]["content_hash"]) == 64
    assert str(tmp_path) not in output.out
    assert "PRIVATE_" not in output.out
    assert output.err == ""
    assert source.read_bytes() == before


def test_inspect_filters_title_and_reports_missing(tmp_path, capsys):
    source = tmp_path / "synthetic.mshc"
    with ZipFile(source, "w") as archive:
        for i in range(22):
            archive.writestr(
                f"sample/1033/{i}.html",
                f"<html><head><title>Topic {i}</title></head>"
                "<body><article><p>Text</p></article></body></html>",
            )
    args = [
        "inspect-infosys",
        "--source",
        str(source),
        "--library",
        "sample",
        "--language",
        "en",
    ]
    assert main(args + ["--title", "topic 21"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total"] == 1
    assert report["topics"][0]["title"] == "Topic 21"
    assert main(args + ["--title", "missing"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "not_found"
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total"] == 22
    assert len(report["topics"]) == 20
    assert report["truncated"] is True


def test_inspect_failure_does_not_expose_paths(tmp_path, capsys):
    assert (
        main(
            [
                "inspect-infosys",
                "--source",
                str(tmp_path / "private-user.mshc"),
                "--library",
                "sample",
                "--language",
                "en",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert not output.out
    assert "private-user" not in output.err
    assert "Traceback" not in output.err
