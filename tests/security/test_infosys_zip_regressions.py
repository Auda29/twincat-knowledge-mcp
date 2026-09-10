"""Synthetic archive regressions from the independent reader review."""

import struct
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from twincat_knowledge.ingest.infosys import (
    InfoSysArchiveError,
    InfoSysLimitError,
    InfoSysLimits,
    UnsafeArchiveError,
    read_infosys,
)


def archive_bytes(names=("lib/1033/a.html",)):
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b"<html><body><p>Safe text</p></body></html>")
    return stream.getvalue()


def test_corrupt_deflate_is_controlled_reader_error():
    data = bytearray(archive_bytes())
    name_size, extra_size = struct.unpack_from("<HH", data, 26)
    payload_start = 30 + name_size + extra_size
    # Invalid DEFLATE block type (BTYPE=3), not an incidental CRC failure.
    data[payload_start] = 0x07
    with pytest.raises(InfoSysArchiveError):
        read_infosys(bytes(data), source_id="synthetic", snapshot_id="fixture-1")


@pytest.mark.parametrize("encoded", ["%2561", "%252561", "%41"])
def test_repeated_decoding_collisions_are_rejected(encoded):
    data = archive_bytes(("lib/1033/a.html", f"lib/1033/{encoded}.html"))
    with pytest.raises(UnsafeArchiveError, match="colliding"):
        read_infosys(data, source_id="synthetic", snapshot_id="fixture-1")


@pytest.mark.parametrize("forged_count", [False, True])
def test_entry_cap_is_enforced_before_zipinfo_allocation(monkeypatch, forged_count):
    data = bytearray(archive_bytes(tuple(f"lib/1033/{i}.html" for i in range(3))))
    if forged_count:
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, end + 8, 1, 1)

    def forbidden_zipinfo(*args, **kwargs):
        pytest.fail("ZipInfo allocation happened before the configured entry cap")

    monkeypatch.setattr("zipfile.ZipInfo", forbidden_zipinfo)
    with pytest.raises(InfoSysLimitError, match="entry count"):
        read_infosys(
            bytes(data),
            source_id="synthetic",
            snapshot_id="fixture-1",
            limits=InfoSysLimits(max_archive_entries=1),
        )


@pytest.mark.parametrize("limit", [1, 2])
def test_zip64_directory_is_counted_before_allocation(monkeypatch, limit):
    # Force real ZIP64 end records in a small, original synthetic archive.
    monkeypatch.setattr("zipfile.ZIP_FILECOUNT_LIMIT", 1)
    data = archive_bytes(("lib/1033/a.html", "lib/1033/b.html"))
    assert b"PK\x06\x06" in data
    if limit == 1:

        def forbidden_zipinfo(*args, **kwargs):
            pytest.fail("ZIP64 entry cap checked after ZipInfo allocation")

        monkeypatch.setattr("zipfile.ZipInfo", forbidden_zipinfo)
        with pytest.raises(InfoSysLimitError, match="entry count"):
            read_infosys(
                data,
                source_id="synthetic",
                snapshot_id="fixture-1",
                limits=InfoSysLimits(max_archive_entries=limit),
            )
    else:
        topics = read_infosys(
            data,
            source_id="synthetic",
            snapshot_id="fixture-1",
            limits=InfoSysLimits(max_archive_entries=limit),
        )
        assert len(topics) == 2


def test_reader_requires_explicit_source_and_snapshot_identity():
    from twincat_knowledge.ingest.infosys import InfoSysReader

    for factory in (InfoSysReader, read_infosys):
        for kwargs in ({}, {"source_id": "synthetic"}, {"snapshot_id": "fixture-1"}):
            with pytest.raises(TypeError):
                factory(archive_bytes(), **kwargs)
