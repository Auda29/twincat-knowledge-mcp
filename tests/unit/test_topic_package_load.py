"""Strict TDD coverage for the read-only topic-package loader."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_export import read_topic_export, write_topic_export
from twincat_knowledge.corpus.topic_package import (
    TopicPackageManifest,
    build_topic_package,
)
from twincat_knowledge.corpus.topic_package_load import (
    MAX_MANIFEST_BYTES,
    TopicPackageLoadError,
    load_topic_package,
)
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata
from twincat_knowledge.ingest.infosys import InfoSysReader
from twincat_knowledge.ingest.normalize import normalize_infosys

SOURCE_HASH = "b" * 64
CONTENT_HASH = "a" * 64


def _source() -> SourceSnapshot:
    return SourceSnapshot(
        source_id="synthetic",
        snapshot_id="source-1",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        language="en",
        content_hash=SOURCE_HASH,
        rights_reference="operator-approved-fixture",
        parser_version="reader-1",
    )


def _topic(locator: str = "motion/en/move.html", title: str = "Move") -> Topic:
    topic_id = canonical_topic_id("synthetic", "source-1", "en", locator)
    source = SourceReference(
        source_id="synthetic",
        snapshot_id="source-1",
        topic_id="help.move",
        title=title,
        language="en",
        locator=locator,
        content_hash=CONTENT_HASH,
    )
    section_id = canonical_section_id(topic_id, 0)
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id="help.move",
        library="motion",
        language="en",
        source=source,
        metadata=(TopicMetadata(name="repeat", content="first"),),
        sections=(
            Section(
                id=section_id,
                kind="code",
                code="x := 'snowman ☃';",
                language="st",
                source=source.model_copy(update={"section_id": section_id}),
            ),
        ),
        image_refs=(),
        help_ids=("help.move",),
    )


def _manifest(topics: tuple[Topic, ...]) -> CorpusManifest:
    return CorpusManifest(
        package_schema_version="1.0",
        snapshot_id="package-1",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        sources=(_source(),),
        inventory=InventoryBalance(
            documents_total=len(topics),
            documents_imported=len(topics),
            documents_skipped=0,
            documents_failed=0,
        ),
        entity_counts=EntityCounts(
            topics=len(topics),
            sections=sum(len(topic.sections) for topic in topics),
        ),
    )


def _package(
    tmp_path: Path, topics: tuple[Topic, ...] = (_topic(),)
) -> tuple[Path, str]:
    result = build_topic_package(tmp_path / "package", _manifest(topics), topics)
    return result.path, result.manifest_sha256


def test_load_roundtrips_exact_and_fts_and_closes_idempotently(tmp_path: Path) -> None:
    package, fingerprint = _package(
        tmp_path, (_topic(), _topic("motion/en/stop.html", "Stop"))
    )
    cache = tmp_path / "operator-cache"
    cache.mkdir()

    with load_topic_package(
        package, expected_manifest_sha256=fingerprint, cache_dir=cache
    ) as loaded:
        assert loaded.summary.topic_count == 2
        assert loaded.manifest == TopicPackageManifest.model_validate_json(
            (package / "manifest.json").read_bytes()
        )
        assert loaded.index.get_topic(_topic().id) == _topic()
        assert loaded.index.search("snowman ☃")[0].id == _topic().id
        loaded.close()
        loaded.close()
        with pytest.raises(TopicPackageLoadError, match="closed"):
            _ = loaded.index
    assert tuple(cache.iterdir()) == ()


def test_loader_requires_exact_lowercase_manifest_fingerprint(tmp_path: Path) -> None:
    package, fingerprint = _package(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    for pin in (
        None,
        fingerprint.upper(),
        fingerprint[:-1],
        fingerprint + "0",
        "not-a-hash",
    ):
        kwargs = {} if pin is None else {"expected_manifest_sha256": pin}
        with pytest.raises((TypeError, TopicPackageLoadError)):
            with load_topic_package(
                package,
                cache_dir=cache,
                **kwargs,
            ):
                pass


def test_manifest_hash_is_checked_before_model_parse_or_sqlite_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, fingerprint = _package(tmp_path)
    manifest = package / "manifest.json"
    manifest.write_bytes(manifest.read_bytes().replace(b'"1.0"', b'"bad"', 1))
    opened = False
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal opened
        opened = True
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package, expected_manifest_sha256=fingerprint, cache_dir=tmp_path / "cache"
        ):
            pass
    assert not opened
    assert not (tmp_path / "cache").exists()


def test_loader_uses_verified_copy_after_source_changes(tmp_path: Path) -> None:
    package, fingerprint = _package(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    with load_topic_package(
        package, expected_manifest_sha256=fingerprint, cache_dir=cache
    ) as loaded:
        (package / "topics.jsonl").write_bytes(b"tampered")
        assert loaded.index.get_topic(_topic().id) == _topic()


def test_descriptor_and_source_listing_are_not_modified(tmp_path: Path) -> None:
    package, fingerprint = _package(tmp_path)
    before = {
        child.name: (
            child.stat().st_size,
            hashlib.sha256(child.read_bytes()).hexdigest(),
        )
        for child in package.iterdir()
    }
    cache = tmp_path / "cache"
    cache.mkdir()
    with load_topic_package(
        package, expected_manifest_sha256=fingerprint, cache_dir=cache
    ):
        pass
    after = {
        child.name: (
            child.stat().st_size,
            hashlib.sha256(child.read_bytes()).hexdigest(),
        )
        for child in package.iterdir()
    }
    assert before == after


def test_missing_manifest_is_rejected_without_cache_side_effect(tmp_path: Path) -> None:
    package, _ = _package(tmp_path)
    (package / "manifest.json").unlink()
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package, expected_manifest_sha256="a" * 64, cache_dir=cache
        ):
            pass
    assert tuple(cache.iterdir()) == ()


def test_manifest_bound_is_shared_with_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_MANIFEST_BYTES == 16 * 1024 * 1024
    import twincat_knowledge.corpus.topic_package as topic_package

    monkeypatch.setattr(topic_package, "MAX_MANIFEST_BYTES", 1)
    with pytest.raises(topic_package.TopicPackageBoundsError):
        build_topic_package(tmp_path / "too-large-manifest", _manifest(()), ())
    assert not (tmp_path / "too-large-manifest" / "manifest.json").exists()


def test_invalid_descriptor_format_is_rejected(tmp_path: Path) -> None:
    package, fingerprint = _package(tmp_path)
    descriptor = json.loads((package / "manifest.json").read_text())
    descriptor["index_format"] = "unknown"
    payload = json.dumps(descriptor, separators=(",", ":")).encode() + b"\n"
    (package / "manifest.json").write_bytes(payload)
    pin = hashlib.sha256(payload).hexdigest()
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(package, expected_manifest_sha256=pin, cache_dir=cache):
            pass
    assert fingerprint != pin


def test_special_artifact_is_rejected_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX special-file boundary")
    package, fingerprint = _package(tmp_path)
    (package / "topics.jsonl").unlink()
    os.mkfifo(package / "topics.jsonl")
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package, expected_manifest_sha256=fingerprint, cache_dir=cache
        ):
            pass
    assert tuple(cache.iterdir()) == ()


def test_extra_index_row_is_rejected_after_hash_pin_rebuild(tmp_path: Path) -> None:
    topics = (_topic(),)
    package, _ = _package(tmp_path, topics)
    sqlite_path = package / "topics.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "INSERT INTO topics VALUES (?, ?, ?, ?, ?)",
            ("foreign", "en", "foreign", "source-1", topics[0].model_dump_json()),
        )
        connection.execute(
            "INSERT INTO search_text VALUES (?, ?)", ("foreign", "foreign")
        )
        connection.commit()
    descriptor = json.loads((package / "manifest.json").read_text())
    entry = next(
        item for item in descriptor["files"] if item["filename"] == "topics.sqlite"
    )
    payload = sqlite_path.read_bytes()
    entry["bytes"] = len(payload)
    entry["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_bytes = json.dumps(descriptor, separators=(",", ":")).encode() + b"\n"
    (package / "manifest.json").write_bytes(manifest_bytes)
    pin = hashlib.sha256(manifest_bytes).hexdigest()
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(package, expected_manifest_sha256=pin, cache_dir=cache):
            pass


def test_actual_reader_normalizer_build_and_loader_roundtrip(tmp_path: Path) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as handle:
        handle.writestr(
            "motion/1033/move.html",
            "<html><head><title>Move</title></head><body>"
            "<pre class='language-st'>x := 1;</pre></body></html>",
        )
    archive.seek(0)
    raw = InfoSysReader(archive, source_id="synthetic", snapshot_id="source-1").read()
    normalized = normalize_infosys(raw, (_source(),))
    export = tmp_path / "normalized.jsonl"
    write_topic_export(export, normalized)
    topics = read_topic_export(export)
    result = build_topic_package(tmp_path / "package", _manifest(topics), topics)
    cache = tmp_path / "cache"
    cache.mkdir()
    with load_topic_package(
        result.path, expected_manifest_sha256=result.manifest_sha256, cache_dir=cache
    ) as loaded:
        assert loaded.summary.topic_count == len(topics)
        assert loaded.index.get_topic(topics[0].id) == topics[0]
        assert loaded.index.search("x := 1")[0] == topics[0]


def test_cache_parent_inside_package_is_rejected_without_creation(
    tmp_path: Path,
) -> None:
    package, fingerprint = _package(tmp_path)
    cache = package / "cache"
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package, expected_manifest_sha256=fingerprint, cache_dir=cache
        ):
            pass
    assert not cache.exists()


def test_duplicate_manifest_fields_are_rejected_before_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, _ = _package(tmp_path)
    original = (package / "manifest.json").read_text()
    payload = (original[:-1] + ',"format_version":"1.0"}\n').encode()
    (package / "manifest.json").write_bytes(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    opened = False
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal opened
        opened = True
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package,
            expected_manifest_sha256=hashlib.sha256(payload).hexdigest(),
            cache_dir=cache,
        ):
            pass
    assert not opened
    assert tuple(cache.iterdir()) == ()


def test_jsonl_semantic_mismatch_is_rejected_before_sqlite_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, _ = _package(tmp_path)
    jsonl = package / "topics.jsonl"
    jsonl.write_bytes(b'{"not":"a topic"}\n')
    descriptor = json.loads((package / "manifest.json").read_text())
    entry = next(
        item for item in descriptor["files"] if item["filename"] == "topics.jsonl"
    )
    entry["bytes"] = jsonl.stat().st_size
    entry["sha256"] = hashlib.sha256(jsonl.read_bytes()).hexdigest()
    manifest = json.dumps(descriptor, separators=(",", ":")).encode() + b"\n"
    (package / "manifest.json").write_bytes(manifest)
    cache = tmp_path / "cache"
    cache.mkdir()
    opened = False
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal opened
        opened = True
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package,
            expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
            cache_dir=cache,
        ):
            pass
    assert not opened
    assert tuple(cache.iterdir()) == ()


def test_descriptor_size_bound_is_checked_before_copy(tmp_path: Path) -> None:
    package, _ = _package(tmp_path)
    descriptor = json.loads((package / "manifest.json").read_text())
    descriptor["files"][0]["bytes"] = 64 * 1024 * 1024 + 1
    manifest = json.dumps(descriptor, separators=(",", ":")).encode() + b"\n"
    (package / "manifest.json").write_bytes(manifest)
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package,
            expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
            cache_dir=cache,
        ):
            pass
    assert tuple(cache.iterdir()) == ()


def test_utf8_manifest_failure_is_generic_and_cache_is_clean(tmp_path: Path) -> None:
    package, _ = _package(tmp_path)
    payload = b"\xff\n"
    (package / "manifest.json").write_bytes(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(TopicPackageLoadError) as error:
        with load_topic_package(
            package,
            expected_manifest_sha256=hashlib.sha256(payload).hexdigest(),
            cache_dir=cache,
        ):
            pass
    assert str(error.value) == "topic package manifest is invalid"
    assert tuple(cache.iterdir()) == ()


def test_artifact_hash_mismatch_is_rejected_before_sqlite_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, fingerprint = _package(tmp_path)
    jsonl = package / "topics.jsonl"
    original = jsonl.read_bytes()
    jsonl.write_bytes(b"x" * len(original))
    cache = tmp_path / "cache"
    cache.mkdir()
    opened = False
    real_connect = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal opened
        opened = True
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(TopicPackageLoadError):
        with load_topic_package(
            package, expected_manifest_sha256=fingerprint, cache_dir=cache
        ):
            pass
    assert not opened
    assert tuple(cache.iterdir()) == ()


def test_load_returns_usable_resource_without_enter(tmp_path):
    from twincat_knowledge.corpus.topic_package_load import LoadedTopicPackage

    package, fingerprint = _package(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    loaded = load_topic_package(
        package, expected_manifest_sha256=fingerprint, cache_dir=cache
    )
    assert isinstance(loaded, LoadedTopicPackage)
    try:
        assert loaded.index.get_topic(_topic().id) == _topic()
        assert loaded.summary.topic_count == 1
    finally:
        loaded.close()
    loaded.close()
    assert list(cache.iterdir()) == []


def test_caller_exception_is_not_reclassified_as_load_error(tmp_path):
    package, fingerprint = _package(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    failure = ValueError("caller failure")
    with pytest.raises(ValueError) as caught:
        with load_topic_package(
            package, expected_manifest_sha256=fingerprint, cache_dir=cache
        ):
            raise failure
    assert caught.value is failure
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("alias_side", ["cache", "package"])
def test_cache_cannot_alias_a_directory_inside_source(tmp_path, alias_side):
    from twincat_knowledge.corpus.topic_package_load import TopicPackageLoadPathError

    package, fingerprint = _package(tmp_path)
    inside = package / "cache"
    inside.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(
            package if alias_side == "cache" else tmp_path, target_is_directory=True
        )
    except OSError:
        pytest.skip("directory symlinks unavailable on this test host")
    cache = alias / "cache" if alias_side == "cache" else inside
    source = package if alias_side == "cache" else alias / "package"
    with pytest.raises(TopicPackageLoadPathError):
        with load_topic_package(
            source, expected_manifest_sha256=fingerprint, cache_dir=cache
        ):
            pass
    assert list(inside.iterdir()) == []


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_id", "foreign_id", "body", "language", "library", "source_snapshot_id"],
)
def test_repinned_index_search_semantics_must_match_topics(tmp_path, mutation):
    from twincat_knowledge.corpus.topic_package_load import (
        TopicPackageLoadValidationError,
    )

    topics = (_topic(), _topic("motion/en/stop.html", "Stop"))
    package, _ = _package(tmp_path, topics)
    cache = tmp_path / "cache"
    cache.mkdir()
    database = package / "topics.sqlite"
    with sqlite3.connect(database) as connection:
        if mutation == "duplicate_id":
            connection.execute("UPDATE search_text SET id = ?", (topics[0].id,))
        elif mutation == "foreign_id":
            connection.execute("UPDATE search_text SET id = 'foreign'")
        elif mutation == "body":
            connection.execute("UPDATE search_text SET body = 'unrelated'")
        else:
            assert mutation in {"language", "library", "source_snapshot_id"}
            connection.execute(f"UPDATE topics SET {mutation} = ?", ("unrelated",))
    descriptor = json.loads((package / "manifest.json").read_bytes())
    data = database.read_bytes()
    descriptor["files"][1]["sha256"] = hashlib.sha256(data).hexdigest()
    descriptor["files"][1]["bytes"] = len(data)
    payload = json.dumps(descriptor).encode("utf-8")
    (package / "manifest.json").write_bytes(payload)
    pin = hashlib.sha256(payload).hexdigest()
    with pytest.raises(TopicPackageLoadValidationError):
        with load_topic_package(package, expected_manifest_sha256=pin, cache_dir=cache):
            pass
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("mutation", ["foreign_id", "body"])
def test_rejected_fts_scan_closes_cursor_before_connection(
    tmp_path, monkeypatch, mutation
):
    # Retain the live cursor, like an exception traceback does on early rejection.
    # This exposes the Windows close-before-unlink requirement on every platform.
    original_connect = sqlite3.connect
    events = []
    retained = []

    class TrackedCursor:
        def __init__(self, cursor):
            self.cursor = cursor
            retained.append(self)

        def __iter__(self):
            return iter(self.cursor)

        def close(self):
            self.cursor.close()
            events.append("cursor")

    class TrackedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            cursor = super().execute(sql, *args, **kwargs)
            if sql.startswith("SELECT CASE WHEN length(CAST(id AS BLOB))"):
                self.tracked_scan = True
                return TrackedCursor(cursor)
            return cursor

        def close(self):
            if getattr(self, "tracked_scan", False):
                events.append("connection")
            return super().close()

    def connect(*args, **kwargs):
        kwargs["factory"] = TrackedConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    test_repinned_index_search_semantics_must_match_topics(tmp_path, mutation)
    assert retained
    assert events == ["cursor", "connection"]
