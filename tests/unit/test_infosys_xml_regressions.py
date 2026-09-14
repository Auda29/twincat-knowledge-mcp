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
        "<script><title>ACTIVE-TITLE</title>"
        '<meta name="evil" content="ACTIVE-META" />'
        '<article><p>ACTIVE-TEXT</p><img src="active.png" />'
        '<a href="ms-xhelp:///?Id=active" /></article></script>'
        "<style><title>ACTIVE-STYLE-TITLE</title></style>"
        '<title>SAFE-TITLE</title><meta name="safe" content="SAFE-META" />'
        "</head><body><article><p>SAFE<script>DROP</script>SAFE-TAIL</p>"
        '<img src="safe.png" /><a href="ms-xhelp:///?Id=safe" />'
        "</article></body></html>"
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
        "article-before<div>div-before<span>span-text</span>span-tail"
        "<div>nested-block</div>div-after</div><blockquote>quoted</blockquote>"
        "<dl><dt>term</dt><dd>description</dd></dl>article-after"
        '<p>typed-paragraph</p><pre class="language-st">CODE'
        "<span>INNER-CODE</span></pre><table><tr><td><p>cell-text</p>"
        '</td></tr></table><div class="warning"><p>warning-text</p>'
        "</div></article></body></html>"
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
        if section.kind != "table" and isinstance(section.content, str)
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


def test_active_document_root_never_becomes_fallback_text():
    topic = _read("<script>ACTIVE-ROOT<article>ACTIVE-ARTICLE</article></script>")
    assert topic.sections == ()
    assert topic.metadata == ()
    assert topic.image_refs == ()
    assert topic.help_ids == ()


def test_fallback_keeps_safe_inline_text_breaks_and_section_boundaries():
    topic = _read(
        "<article>before <strong>bold <em>em</em> strongtail</strong> after"
        '<br/>next<a href="ms-xhelp:///?Id=target">link</a>'
        "<section>section</section>tail</article>"
    )
    assert [section.content for section in topic.sections] == [
        "before bold em strongtail after\nnextlink",
        "section",
        "tail",
    ]
    assert topic.help_ids == ("target",)


def test_document_without_body_does_not_emit_head_as_article_text():
    topic = _read("<html><head><title>Safe title</title><p>HEAD-ONLY</p></head></html>")
    assert topic.title == "Safe title"
    assert topic.sections == ()


def test_article_selection_never_detaches_head_or_title_descendants():
    for container in ("head", "title"):
        for body in ("", "<body><article><p>BODY</p></article></body>"):
            topic = _read(
                f"<html><{container}><article>HEAD-ARTICLE</article>"
                f"</{container}>{body}</html>"
            )
            expected = ["BODY"] if body else []
            assert [section.content for section in topic.sections] == expected


def test_head_only_fallback_excludes_head_assets_and_help_links():
    topic = _read(
        '<html><head><a href="ms-xhelp:///?Id=HEAD">head link</a>'
        '<img src="head.png"/></head>'
        '<a href="ms-xhelp:///?Id=VISIBLE">visible link</a>'
        '<img src="visible.png"/></html>'
    )
    assert topic.help_ids == ("VISIBLE",)
    assert topic.image_refs == ("visible.png",)
    assert [section.content for section in topic.sections] == ["visible link"]


def test_nested_metadata_subtrees_are_excluded_from_structured_text():
    topic = _read(
        "<article><p>before<head><p>HIDDEN</p></head>tail"
        "<title>HIDDEN-TITLE</title>end</p>"
        "<table><head><tr><td>HIDDEN-ROW</td></tr></head>"
        "<tr><td>visible</td></tr></table></article>"
    )
    assert [(section.kind, section.content) for section in topic.sections] == [
        ("paragraph", "beforetailend"),
        ("table", (("visible",),)),
    ]
