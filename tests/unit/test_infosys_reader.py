"""Synthetic, vertical tests for the bounded InfoSys reader."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from twincat_knowledge.ingest.infosys import (
    InfoSysLimitError,
    InfoSysLimits,
    InfoSysReader,
)


def _archive(entries: dict[str, str | bytes]) -> BytesIO:
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(
                name,
                content.encode("utf-8") if isinstance(content, str) else content,
            )
    payload.seek(0)
    return payload


def test_reader_returns_topic_with_locator_library_language_and_hash() -> None:
    html = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Synthetic move</title>
    <meta name="Microsoft.Help.Id" content="help.synthetic.move" />
  </head>
  <body><p>Move an axis.</p></body>
</html>
"""

    topics = InfoSysReader(_archive({"tcplclib_alpha/1033/move.html": html})).read()

    assert len(topics) == 1
    topic = topics[0]
    assert topic.title == "Synthetic move"
    assert topic.library == "tcplclib_alpha"
    assert topic.language == "en"
    assert topic.source.locator == "tcplclib_alpha/1033/move.html"
    assert topic.source.content_hash == (
        "ed12deb5997f4b16455bc33485957d6ccfe50b7d4f97c97be855058d0a42bc46"
    )


def test_reader_preserves_metadata_sections_links_images_and_code_whitespace() -> None:
    html = """<html xmlns="http://www.w3.org/1999/xhtml"><head>
<meta name="repeat" content="one" data-extra="a" />
<meta name="repeat" content="two" data-extra="b" />
</head><body>
<p>Before</p>
<pre class="language-st"> first<br/>second
  </pre>
<table><tr><th>Input</th><th></th></tr><tr><td>Axis</td><td>  </td></tr></table>
<div class="warning"><p>Do not run.</p></div>
<img src="images/diagram.png" />
<a href="ms-xhelp:///?Id=first">one</a><a href="ms-xhelp:///?Id=second">two</a>
</body></html>"""

    topic = InfoSysReader(
        _archive({"tcplclib_alpha/1033/structured.html": html})
    ).read()[0]

    assert [(item.name, item.content) for item in topic.metadata] == [
        ("repeat", "one"),
        ("repeat", "two"),
    ]
    assert [section.kind for section in topic.sections] == [
        "paragraph",
        "code",
        "table",
        "warning",
    ]
    assert topic.sections[1].code == " first\nsecond\n  "
    assert topic.sections[1].language == "st"
    assert topic.sections[2].rows == (("Input", ""), ("Axis", "  "))
    assert topic.sections[3].text == "Do not run."
    assert topic.image_refs == ("images/diagram.png",)
    assert topic.help_ids == ("first", "second")


def test_reader_supports_library_and_language_selection_without_hardcoded_library() -> (
    None
):
    html = "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>x</p></body></html>"
    topics = InfoSysReader(
        _archive(
            {
                "tcplclib_alpha/1033/en.html": html,
                "tcplclib_alpha/1031/de.html": html,
                "tcplclib_beta/1033/en.html": html,
            }
        )
    ).read(libraries=["tcplclib_beta"], language="en")

    assert [(topic.library, topic.language) for topic in topics] == [
        ("tcplclib_beta", "en")
    ]


def test_reader_ignores_safe_directory_entries() -> None:
    html = "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>x</p></body></html>"

    topics = InfoSysReader(_archive({"lib/": b"", "lib/1033/x.html": html})).read()

    assert len(topics) == 1


def test_reader_json_roundtrip_and_repeat_read_are_deterministic() -> None:
    html = "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>x</p></body></html>"
    reader = InfoSysReader(_archive({"lib/1033/x.html": html}))

    first = reader.read()
    second = reader.read()

    assert first == second
    assert first[0] == type(first[0]).model_validate_json(first[0].model_dump_json())


def test_reader_enforces_actual_entry_and_aggregate_bytes() -> None:
    html = "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>x</p></body></html>"

    reader = InfoSysReader(
        _archive({"lib/1033/x.html": html}),
        limits=InfoSysLimits(max_entry_bytes=10, max_aggregate_bytes=20),
    )

    with pytest.raises(InfoSysLimitError):
        reader.read()


def test_path_source_uses_file_backed_archive_and_reads_only_selected_entries(
    tmp_path,
) -> None:
    html = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>selected</p></body></html>"
    )
    payload = _archive(
        {
            "lib/1033/selected.html": html,
            "assets/unrelated.bin": b"x" * (2 * 1024 * 1024),
        }
    ).getvalue()
    archive_path = tmp_path / "large.mshc"
    with archive_path.open("wb") as handle:
        handle.seek(70 * 1024 * 1024)
        handle.write(payload)

    topics = InfoSysReader(
        archive_path,
        limits=InfoSysLimits(
            max_memory_source_bytes=128,
            max_selected_entry_bytes=1024,
        ),
    ).read(libraries=["lib"], language="en")

    assert [topic.source.locator for topic in topics] == ["lib/1033/selected.html"]
