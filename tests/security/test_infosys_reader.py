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
            _archive([("lib/1033/x.bin", b"12345", None)]),
            limits=InfoSysLimits(max_entry_bytes=10, max_aggregate_bytes=4),
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
