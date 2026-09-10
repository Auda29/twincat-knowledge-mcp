"""Security regression tests for untrusted .mshc input."""

import stat
import warnings
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from twincat_knowledge.ingest.infosys import (
    InfoSysLimitError,
    InfoSysLimits,
    InfoSysReader,
    InfoSysXmlError,
    UnsafeArchiveError,
    XMLDepthLimitError,
)


def _archive(entries: list[tuple[str, bytes | str, int | None]]):
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        for name, content, mode in entries:
            info = ZipInfo(name)
            info.compress_type = ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(
                info,
                content.encode("utf-8") if isinstance(content, str) else content,
            )
    payload.seek(0)
    return payload


def test_reader_rejects_traversal_absolute_and_windows_entry_names() -> None:
    for name in (
        "../outside.html",
        "lib/../../outside.html",
        "/absolute.html",
        "C:/outside.html",
        r"lib\\outside.html",
        "lib/CON.html",
        "lib/topic.html:secret",
        "lib/%252e%252e/outside.html",
    ):
        with pytest.raises(UnsafeArchiveError):
            InfoSysReader(_archive([(name, b"x", None)])).read()


def test_reader_rejects_duplicate_and_case_colliding_entries() -> None:
    valid = b"<html xmlns='http://www.w3.org/1999/xhtml'><body/></html>"
    for entries in (
        [("lib/1033/a.html", valid, None), ("lib/1033/a.html", valid, None)],
        [("lib/1033/a.html", valid, None), ("LIB/1033/A.HTML", valid, None)],
    ):
        with warnings.catch_warnings(), pytest.raises(UnsafeArchiveError):
            warnings.simplefilter("ignore", UserWarning)
            InfoSysReader(_archive(entries)).read()


def test_reader_rejects_symlink_entries() -> None:
    symlink_mode = stat.S_IFLNK | 0o777

    with pytest.raises(UnsafeArchiveError):
        InfoSysReader(
            _archive([("lib/1033/link.html", b"target", symlink_mode)])
        ).read()


def test_reader_enforces_entry_count_and_declared_aggregate_limits() -> None:
    many = [(f"lib/1033/{index}.bin", b"x", None) for index in range(3)]
    with pytest.raises(InfoSysLimitError):
        InfoSysReader(
            _archive(many), limits=InfoSysLimits(max_archive_entries=2)
        ).read()

    with pytest.raises(InfoSysLimitError):
        InfoSysReader(
            _archive([("lib/1033/x.html", b"12345", None)]),
            limits=InfoSysLimits(
                max_selected_entry_bytes=10,
                max_selected_aggregate_bytes=4,
            ),
        ).read()


def test_reader_enforces_actual_source_bytes_even_when_stream_ignores_read_size() -> (
    None
):
    class UnboundedStream(BytesIO):
        def read(self, size: int = -1) -> bytes:
            return super().read()

    source = UnboundedStream(b"x" * 20)
    with pytest.raises(InfoSysLimitError):
        InfoSysReader(source, limits=InfoSysLimits(max_source_bytes=10)).read()


def test_reader_rejects_xxe_and_xml_depth_overflow() -> None:
    xxe = b"""<!DOCTYPE html [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>&xxe;</p></body></html>"""
    with pytest.raises(InfoSysXmlError):
        InfoSysReader(_archive([("lib/1033/x.html", xxe, None)])).read()

    nested = (
        b"<html xmlns='http://www.w3.org/1999/xhtml'>"
        + b"<a>" * 8
        + b"x"
        + b"</a>" * 8
        + b"</html>"
    )
    with pytest.raises(XMLDepthLimitError):
        InfoSysReader(
            _archive([("lib/1033/x.html", nested, None)]),
            limits=InfoSysLimits(max_xml_depth=4),
        ).read()


def test_reader_extracts_article_content_and_removes_active_content_with_tails() -> (
    None
):
    html = """<html xmlns="http://www.w3.org/1999/xhtml"><head>
<title>Safe title</title><p>head content must not become an article section</p>
</head><body><article>
<p>keep<script>drop</script>tail<style>also drop</style>end</p>
<ul><li>first</li><li>second</li></ul>
<table><tr><td><p>left</p><p>right</p><script>drop</script>tail</td></tr></table>
<aside role="alert">Important <script>drop</script>notice</aside>
<img src="javascript:alert(1)" />
</article></body></html>"""

    topic = InfoSysReader(_archive([("lib/1033/article.html", html, None)])).read()[0]

    assert [(section.kind, section.content) for section in topic.sections] == [
        ("paragraph", "keeptailend"),
        ("paragraph", "first\nsecond"),
        ("table", (("left\nrighttail",),)),
        ("warning", "Important notice"),
    ]
    assert topic.image_refs == ()


def test_reader_enforces_central_directory_bound_before_zipfile_reads_it() -> None:
    entries = [
        (f"lib/1033/topic-{index}.html", b"<p>x</p>", None) for index in range(4)
    ]

    with pytest.raises(InfoSysLimitError):
        InfoSysReader(
            _archive(entries),
            limits=InfoSysLimits(max_central_directory_bytes=64),
        ).read()
