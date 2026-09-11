"""TDD coverage for bounded operator-side topic package builds."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import twincat_knowledge.corpus.topic_package as topic_package
from twincat_knowledge.corpus.manifest import CorpusManifest, InventoryBalance
from twincat_knowledge.corpus.topic_export import read_topic_export
from twincat_knowledge.corpus.topic_index import TopicIndex
from twincat_knowledge.domain.identity import canonical_section_id, canonical_topic_id
from twincat_knowledge.domain.models import EntityCounts, SourceSnapshot
from twincat_knowledge.domain.provenance import SourceReference
from twincat_knowledge.domain.topics import Section, Topic, TopicMetadata

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


def _topic(raw_locator: str = "motion/en/move.html", title: str = "Move") -> Topic:
    topic_id = canonical_topic_id("synthetic", "source-1", "en", raw_locator)
    source = SourceReference(
        source_id="synthetic",
        snapshot_id="source-1",
        topic_id="help.move",
        title=title,
        language="en",
        locator=raw_locator,
        content_hash=CONTENT_HASH,
    )
    section_id = canonical_section_id(topic_id, 0)
    section_source = source.model_copy(update={"section_id": section_id})
    return Topic(
        id=topic_id,
        title=title,
        original_topic_id="help.move",
        library="motion",
        language="en",
        source=source,
        metadata=(
            TopicMetadata(
                name="repeat", content="first", attributes=(("x", "1"), ("x", "2"))
            ),
            TopicMetadata(name="repeat", content="second"),
        ),
        sections=(
            Section(
                id=section_id,
                kind="code",
                code="IF x THEN\n    y := 'snowman ☃';\nEND_IF;",
                language="st",
                source=section_source,
            ),
        ),
        image_refs=("images/move.png",),
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
            topics=len(topics), sections=sum(len(topic.sections) for topic in topics)
        ),
    )


def test_build_writes_same_generation_and_readback_is_exact(tmp_path: Path) -> None:
    topics = (_topic(), _topic("motion/en/stop.html", "Stop"))
    result = topic_package.build_topic_package(
        tmp_path / "package", _manifest(topics), topics
    )

    assert result.path == tmp_path / "package"
    assert result.manifest.format_version == "1.0"
    assert result.manifest.files[0].filename == "topics.jsonl"
    assert {file.filename for file in result.manifest.files} == {
        "topics.jsonl",
        "topics.sqlite",
    }
    assert (
        result.manifest_bytes == (tmp_path / "package" / "manifest.json").stat().st_size
    )
    assert (
        result.manifest_sha256
        == hashlib.sha256(
            (tmp_path / "package" / "manifest.json").read_bytes()
        ).hexdigest()
    )
    assert "manifest" not in {file.filename for file in result.manifest.files}
    assert read_topic_export(tmp_path / "package" / "topics.jsonl") == topics
    with TopicIndex(tmp_path / "package" / "topics.sqlite") as index:
        assert tuple(index.get_topic(topic.id) for topic in topics) == topics

    descriptor = json.loads((tmp_path / "package" / "manifest.json").read_text())
    assert descriptor["language_counts"] == {"en": 2}
    assert descriptor["index_version"] == str(topic_package.INDEX_VERSION)
    for file in result.manifest.files:
        payload = (tmp_path / "package" / file.filename).read_bytes()
        assert file.bytes == len(payload)
        assert file.sha256 == hashlib.sha256(payload).hexdigest()


def test_empty_corpus_is_valid_and_language_counts_are_immutable(
    tmp_path: Path,
) -> None:
    result = topic_package.build_topic_package(tmp_path / "empty", _manifest(()), ())

    assert result.manifest.language_counts == {}
    with pytest.raises((TypeError, AttributeError)):
        result.manifest.language_counts["en"] = 1  # type: ignore[index]
    with pytest.raises((TypeError, ValidationError, AttributeError)):
        result.manifest.format_version = "2.0"  # type: ignore[misc]


def test_bounds_are_strict_and_checked_before_output_creation(tmp_path: Path) -> None:
    manifest = _manifest((_topic(),))
    for name, value in (
        ("max_topics", True),
        ("max_total_bytes", True),
        ("max_record_bytes", True),
    ):
        with pytest.raises(topic_package.TopicPackageBoundsError):
            topic_package.build_topic_package(
                tmp_path / name, manifest, (), **{name: value}
            )
        assert not (tmp_path / name).exists()


def test_invalid_topic_or_manifest_never_publishes_final_marker(tmp_path: Path) -> None:
    topic = _topic()
    forged = topic.model_construct(id="not-canonical")
    with pytest.raises(topic_package.TopicPackageError):
        topic_package.build_topic_package(
            tmp_path / "invalid-topic", _manifest((topic,)), (forged,)
        )
    assert not (tmp_path / "invalid-topic" / "manifest.json").exists()

    invalid_manifest = _manifest((topic,)).model_construct(entity_counts=None)
    with pytest.raises(topic_package.TopicPackageError):
        topic_package.build_topic_package(
            tmp_path / "invalid-manifest", invalid_manifest, (topic,)
        )
    assert not (tmp_path / "invalid-manifest" / "manifest.json").exists()


def test_failing_generator_is_sanitized_and_keeps_incomplete_directory(
    tmp_path: Path,
) -> None:
    topic = _topic()

    def topics() -> Iterator[Topic]:
        yield topic
        raise RuntimeError("secret source path and payload")

    with pytest.raises(topic_package.TopicPackageError) as error:
        topic_package.build_topic_package(
            tmp_path / "failed", _manifest((topic,)), topics()
        )
    assert "secret source path" not in str(error.value)
    assert not (tmp_path / "failed" / "manifest.json").exists()
    assert (tmp_path / "failed").is_dir()


@pytest.mark.parametrize("kind", ["file", "directory", "dangling"])
def test_existing_target_is_rejected_without_modification(
    tmp_path: Path, kind: str
) -> None:
    target = tmp_path / "target"
    if kind == "file":
        target.write_bytes(b"keep")
    elif kind == "directory":
        target.mkdir()
        (target / "keep").write_bytes(b"keep")
    else:
        target.symlink_to(tmp_path / "missing")

    with pytest.raises(topic_package.TopicPackagePathError):
        topic_package.build_topic_package(target, _manifest(()), ())
    if kind == "file":
        assert target.read_bytes() == b"keep"
    elif kind == "directory":
        assert (target / "keep").read_bytes() == b"keep"
    else:
        assert target.is_symlink()


def test_concurrent_target_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "concurrent"

    real_mkdir = Path.mkdir

    def race(self: Path, *args: object, **kwargs: object) -> None:
        if self == target:
            real_mkdir(self, *args, **kwargs)
            (target / "operator-file").write_bytes(b"keep")
            raise FileExistsError
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", race)

    with pytest.raises(topic_package.TopicPackagePathError):
        topic_package.build_topic_package(target, _manifest(()), ())
    assert (target / "operator-file").read_bytes() == b"keep"
    assert not (target / "manifest.json").exists()


def test_manifest_publication_has_no_unsafe_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "no-link"
    real_link = topic_package.os.link

    def no_link(*args: object, **kwargs: object) -> object:
        if len(args) > 1 and Path(args[1]).name == "manifest.json":
            raise OSError("hard links unavailable")
        return real_link(*args, **kwargs)

    monkeypatch.setattr(topic_package.os, "link", no_link)
    with pytest.raises(topic_package.TopicPackagePathError, match="hard links"):
        topic_package.build_topic_package(target, _manifest(()), ())
    assert target.is_dir()
    assert not (target / "manifest.json").exists()
    monkeypatch.setattr(topic_package.os, "link", real_link)


def test_manifest_fsync_failure_has_no_success_marker(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "fsync-fails"
    real_fsync = topic_package.os.fsync

    def fail_fsync(fd: int) -> None:
        raise OSError("sync failed")

    monkeypatch.setattr(topic_package.os, "fsync", fail_fsync)
    with pytest.raises(topic_package.TopicPackageIOError):
        topic_package.build_topic_package(target, _manifest(()), ())
    assert target.is_dir()
    assert not (target / "manifest.json").exists()
    monkeypatch.setattr(topic_package.os, "fsync", real_fsync)


def test_file_mutation_is_detectable_from_descriptor(tmp_path: Path) -> None:
    target = tmp_path / "package"
    topic_package.build_topic_package(target, _manifest(()), ())
    descriptor = json.loads((target / "manifest.json").read_text())
    (target / "topics.jsonl").write_bytes(b"changed")
    entry = next(
        file for file in descriptor["files"] if file["filename"] == "topics.jsonl"
    )
    assert (
        entry["sha256"]
        != hashlib.sha256((target / "topics.jsonl").read_bytes()).hexdigest()
    )


def test_same_inputs_have_same_jsonl_and_descriptor(tmp_path: Path) -> None:
    topics = (_topic(),)
    first = topic_package.build_topic_package(
        tmp_path / "one", _manifest(topics), topics
    )
    second = topic_package.build_topic_package(
        tmp_path / "two", _manifest(topics), topics
    )
    assert (first.path / "topics.jsonl").read_bytes() == (
        second.path / "topics.jsonl"
    ).read_bytes()
    assert (first.path / "manifest.json").read_bytes() == (
        second.path / "manifest.json"
    ).read_bytes()


def test_result_descriptor_can_validate_as_strict_model(tmp_path: Path) -> None:
    result = topic_package.build_topic_package(tmp_path / "package", _manifest(()), ())
    parsed = topic_package.TopicPackageManifest.model_validate_json(
        (result.path / "manifest.json").read_text()
    )
    assert parsed == result.manifest


def test_manifest_has_fixed_filenames_and_rejects_self_hash() -> None:
    with pytest.raises(ValidationError):
        topic_package.TopicPackageManifest(
            format_version="1.0",
            corpus_manifest=_manifest(()),
            files=(
                topic_package.TopicPackageFile(
                    filename="../manifest.json", sha256="a" * 64, bytes=0
                ),
                topic_package.TopicPackageFile(
                    filename="topics.sqlite", sha256="b" * 64, bytes=0
                ),
            ),
            language_counts={},
            index_format="sqlite-fts5",
            index_version="1",
        )


def test_cancel_like_base_exception_is_not_swallowed(tmp_path: Path) -> None:
    class Cancelled(BaseException):
        pass

    def topics() -> Iterator[Topic]:
        raise Cancelled()
        yield _topic()

    with pytest.raises(Cancelled):
        topic_package.build_topic_package(
            tmp_path / "cancelled", _manifest(()), topics()
        )


def test_topic_count_and_record_bytes_are_forwarded(tmp_path: Path) -> None:
    topic = _topic()
    record_bytes = len(topic.model_dump_json().encode())
    with pytest.raises(topic_package.TopicPackageBoundsError):
        topic_package.build_topic_package(
            tmp_path / "too-many", _manifest((topic,)), (topic, topic), max_topics=1
        )
    with pytest.raises(topic_package.TopicPackageBoundsError):
        topic_package.build_topic_package(
            tmp_path / "too-large",
            _manifest((topic,)),
            (topic,),
            max_record_bytes=record_bytes - 1,
        )
    assert not (tmp_path / "too-many" / "manifest.json").exists()
    assert not (tmp_path / "too-large" / "manifest.json").exists()


def test_artifact_symlink_is_rejected_before_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "symlink-artifact"
    original = topic_package.write_topic_export

    def write_symlink(path: Path, topics: object, **kwargs: object) -> object:
        path.symlink_to(tmp_path / "outside")
        return original(path, topics, **kwargs)  # pragma: no cover

    monkeypatch.setattr(topic_package, "write_topic_export", write_symlink)
    with pytest.raises(topic_package.TopicPackageError):
        topic_package.build_topic_package(target, _manifest(()), ())
    assert not (target / "manifest.json").exists()


def test_no_model_network_calls_are_needed(tmp_path: Path) -> None:
    result = topic_package.build_topic_package(tmp_path / "offline", _manifest(()), ())
    assert result.manifest.index_format == "sqlite-fts5"
    assert os.path.exists(result.path / "topics.sqlite")


def test_same_size_jsonl_change_prevents_manifest(tmp_path, monkeypatch):
    topics = (_topic(),)
    original_create = topic_package.create_topic_index

    def change_jsonl(path, records, **options):
        count = original_create(path, records, **options)
        jsonl = path.with_name("topics.jsonl")
        before = jsonl.read_bytes()
        after = before.replace(b"Move", b"Fake")
        assert after != before and len(after) == len(before)
        jsonl.write_bytes(after)
        return count

    monkeypatch.setattr(topic_package, "create_topic_index", change_jsonl)
    output = tmp_path / "package"
    with pytest.raises(topic_package.TopicPackageValidationError):
        topic_package.build_topic_package(output, _manifest(topics), topics)
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("swap_at_open", [False, True])
def test_public_build_rejects_fifo_without_blocking(tmp_path, swap_at_open):
    import subprocess
    import sys

    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO boundary")
    script = r"""
import os, runpy, sys
from pathlib import Path
ns = runpy.run_path(sys.argv[1])
m = ns['topic_package']
p = Path(sys.argv[2])
topics = (ns['_topic'](),)
original_create = m.create_topic_index
original_open = os.open
def create(path, records, **kwargs):
    count = original_create(path, records, **kwargs)
    jsonl = path.with_name('topics.jsonl')
    if sys.argv[3] == 'True':
        def swap(name, flags, *args, **kwargs):
            if Path(name) == jsonl:
                jsonl.unlink()
                os.mkfifo(jsonl)
            return original_open(name, flags, *args, **kwargs)
        os.open = swap
    else:
        jsonl.unlink()
        os.mkfifo(jsonl)
    return count
m.create_topic_index = create
try:
    m.build_topic_package(p, ns['_manifest'](topics), topics)
except m.TopicPackagePathError:
    assert not (p / 'manifest.json').exists()
    print('rejected')
else:
    raise AssertionError('FIFO accepted')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            __file__,
            str(tmp_path / "package"),
            str(swap_at_open),
        ],
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


def test_index_hashing_enforces_artifact_ceiling(tmp_path, monkeypatch):
    topics = (_topic(),)
    monkeypatch.setattr(topic_package, "MAX_INDEX_BYTES", 1, raising=False)
    output = tmp_path / "package"
    with pytest.raises(topic_package.TopicPackageBoundsError):
        topic_package.build_topic_package(output, _manifest(topics), topics)
    assert not (output / "manifest.json").exists()


def test_jsonl_growth_during_hashing_stops_at_original_size(tmp_path, monkeypatch):
    topics = (_topic(),)
    original_read = os.read
    original_create = topic_package.create_topic_index
    read_sizes = []
    original_size = []

    def create(path, records, **options):
        count = original_create(path, records, **options)
        jsonl = path.with_name("topics.jsonl")
        metadata = jsonl.stat()
        original_size.append(metadata.st_size)
        changed = False

        def grow(descriptor, size):
            nonlocal changed
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) == (metadata.st_dev, metadata.st_ino):
                read_sizes.append(size)
                if not changed:
                    changed = True
                    with jsonl.open("ab") as stream:
                        stream.write(b" ")
            return original_read(descriptor, size)

        monkeypatch.setattr(os, "read", grow)
        return count

    monkeypatch.setattr(topic_package, "create_topic_index", create)
    output = tmp_path / "package"
    with pytest.raises(topic_package.TopicPackageBoundsError):
        topic_package.build_topic_package(output, _manifest(topics), topics)
    assert read_sizes and max(read_sizes) <= original_size[0] + 1
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", "999"),
        ("index_format", "not-sqlite"),
        ("index_version", "999"),
    ],
)
def test_public_manifest_rejects_unsupported_formats(tmp_path, field, value):
    topics = (_topic(),)
    result = topic_package.build_topic_package(
        tmp_path / "package", _manifest(topics), topics
    )
    data = json.loads(result.manifest_path.read_bytes())
    data[field] = value
    with pytest.raises(ValidationError):
        topic_package.TopicPackageManifest.model_validate_json(json.dumps(data))
