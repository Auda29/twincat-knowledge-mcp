"""Regression tests for safe and complete InfoSys XML section extraction."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from twincat_knowledge.ingest.infosys import InfoSysReader


def _archive(html: str) -> BytesIO:
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("synthetic/1033/topic.html", html.encode("utf-8"))
    payload.seek(0)
    return payload


def _read(html: str):
    return InfoSysReader(
        _archive(html), source_id="synthetic", snapshot_id="fixture-1"
    ).read()[0]


def test_xml_selection_skips_active_ancestors_but_keeps_safe_tails() -> None:
    html = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<script><title>ACTIVE-TITLE</title>'
        '<meta name="evil" content="ACTIVE-META" />'
        '<article><p>ACTIVE-TEXT</p><img src="active.png" />'
        '<a href="ms-xhelp:///?Id=active" /></article></script>'
        '<style><title>ACTIVE-STYLE-TITLE</title></style>'
        '<title>SAFE-TITLE</title><meta name="safe" content="SAFE-META" />'
        '</head><body><article><p>SAFE<script>DROP</script>SAFE-TAIL</p>'
        '<img src="safe.png" /><a href="ms-xhelp:///?Id=safe" />'
        '</article></body></html>'
    )

    topic = _read(html)

    assert topic.title == "SAFE-TITLE"
    assert [(item.name, item.content) for item in topic.metadata] == [
        ("safe", "SAFE-META")
    ]
    assert [(section.kind, section.content) for section in topic.sections] == [
        ("paragraph", "SAFESAFE-TAIL")
    ]
    assert topic.image_refs == ("safe.png",)
    assert topic.help_ids == ("safe",)


def test_xml_sections_preserve_wrapper_text_once_and_keep_structured_types() -> None:
    html = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><article>'
        'article-before<div>div-before<span>span-text</span>span-tail'
        '<div>nested-block</div>div-after</div><blockquote>quoted</blockquote>'
        '<dl><dt>term</dt><dd>description</dd></dl>article-after'
        '<p>typed-paragraph</p><pre class="language-st">CODE'
        '<span>INNER-CODE</span></pre><table><tr><td><p>cell-text</p>'
        '</td></tr></table><div class="warning"><p>warning-text</p>'
        '</div></article></body></html>'
    )

    topic = _read(html)

    assert [(section.kind, section.content) for section in topic.sections] == [
        ("paragraph", "article-before"),
        ("paragraph", "div-beforespan-textspan-tail"),
        ("paragraph", "nested-block"),
        ("paragraph", "div-after"),
        ("paragraph", "quoted"),
        ("paragraph", "term"),
        ("paragraph", "description"),
        ("paragraph", "article-after"),
        ("paragraph", "typed-paragraph"),
        ("code", "CODEINNER-CODE"),
        ("table", (("cell-text",),)),
        ("warning", "warning-text"),
    ]

    combined = "".join(
        section.content
        for section in topic.sections
        if section.kind != "table"
        and isinstance(section.content, str)
    )
    for text in (
        "div-before",
        "span-text",
        "span-tail",
        "nested-block",
        "typed-paragraph",
        "INNER-CODE",
        "warning-text",
    ):
        assert combined.count(text) == 1
    assert [section.kind for section in topic.sections[-3:]] == [
        "code",
        "table",
        "warning",
    ]
