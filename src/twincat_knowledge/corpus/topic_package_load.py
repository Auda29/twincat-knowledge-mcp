"""Fail-closed loading of verified, read-only topic packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, NoReturn, Self

from twincat_knowledge.domain.topics import Topic

from .manifest import CorpusManifest
from .topic_export import MAX_TOTAL_BYTES, read_topic_export
from .topic_index import MAX_TOPICS as INDEX_MAX_TOPICS
from .topic_index import TopicIndex
from .topic_package import (
    MAX_INDEX_BYTES,
    MAX_MANIFEST_BYTES,
    TopicPackageManifest,
)
from .topic_validation import TopicCorpusSummary, validate_topic_corpus

_CHUNK_BYTES: Final = 1024 * 1024
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_FIXED_MANIFEST: Final = "manifest.json"
_FIXED_JSONL: Final = "topics.jsonl"
_FIXED_INDEX: Final = "topics.sqlite"


class TopicPackageLoadError(RuntimeError):
    """Base class for controlled package-loader failures."""


class TopicPackageLoadPathError(TopicPackageLoadError):
    """A package, artifact, or operator cache path is unsafe or unavailable."""


class TopicPackageLoadValidationError(TopicPackageLoadError, ValueError):
    """A manifest or verified package does not describe supported content."""


class TopicPackageLoadBoundsError(TopicPackageLoadValidationError):
    """A manifest or artifact exceeds a loader bound."""


class TopicPackageLoadIntegrityError(TopicPackageLoadValidationError):
    """A package fingerprint, artifact size, or artifact hash is wrong."""


class TopicPackageLoadIOError(TopicPackageLoadError):
    """An artifact could not be read or copied safely."""


def _error(
    message: str, error_type: type[TopicPackageLoadError] = TopicPackageLoadError
) -> NoReturn:
    raise error_type(message) from None


def _absolute(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(Path(path))))
    except (OSError, RuntimeError, TypeError, ValueError):
        _error("topic package path is invalid", TopicPackageLoadPathError)


def _regular_directory(path: Path, message: str) -> None:
    try:
        metadata = path.lstat()
    except (OSError, RuntimeError, ValueError):
        _error(message, TopicPackageLoadPathError)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _error(message, TopicPackageLoadPathError)


def _check_paths(package: Path, cache_dir: Path) -> None:
    _regular_directory(package, "topic package directory is unavailable")
    _regular_directory(cache_dir, "operator cache directory is unavailable")
    try:
        if cache_dir.resolve(strict=True).is_relative_to(package.resolve(strict=True)):
            _error(
                "operator cache directory must be outside the topic package",
                TopicPackageLoadPathError,
            )
    except (OSError, RuntimeError, ValueError):
        _error("topic package paths are invalid", TopicPackageLoadPathError)


def _source_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_regular(path: Path, maximum: int) -> tuple[int, int]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            _error("package artifact must be a regular file", TopicPackageLoadPathError)
        if metadata.st_size > maximum:
            _error("package artifact byte bound exceeded", TopicPackageLoadBoundsError)
        descriptor = os.open(path, _source_flags())
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                _error(
                    "package artifact must be a regular file", TopicPackageLoadPathError
                )
            if opened.st_size > maximum:
                _error(
                    "package artifact byte bound exceeded", TopicPackageLoadBoundsError
                )
            return descriptor, opened.st_size
        except BaseException:
            os.close(descriptor)
            raise
    except TopicPackageLoadError:
        raise
    except (OSError, RuntimeError, ValueError):
        _error("package artifact could not be opened", TopicPackageLoadIOError)


def _read_bounded(path: Path, maximum: int) -> bytes:
    descriptor: int | None = None
    try:
        descriptor, expected_size = _open_regular(path, maximum)
        digest = bytearray()
        while len(digest) <= maximum:
            chunk = os.read(descriptor, min(_CHUNK_BYTES, maximum - len(digest) + 1))
            if not chunk:
                break
            digest.extend(chunk)
            if len(digest) > maximum:
                _error(
                    "package artifact byte bound exceeded", TopicPackageLoadBoundsError
                )
        final_size = os.fstat(descriptor).st_size
        if final_size != expected_size or len(digest) != expected_size:
            _error(
                "package artifact changed while reading", TopicPackageLoadIntegrityError
            )
        return bytes(digest)
    except TopicPackageLoadError:
        raise
    except (OSError, ValueError):
        _error("package artifact could not be read", TopicPackageLoadIOError)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            _error("package artifact could not be copied", TopicPackageLoadIOError)
        offset += written


def _copy_verified(
    source: Path,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    maximum: int,
) -> None:
    source_descriptor: int | None = None
    destination_descriptor: int | None = None
    try:
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            _error(
                "package descriptor has invalid size", TopicPackageLoadValidationError
            )
        if expected_size < 0 or expected_size > maximum:
            _error(
                "package descriptor byte bound exceeded", TopicPackageLoadBoundsError
            )
        source_descriptor, source_size = _open_regular(source, maximum)
        if source_size != expected_size:
            _error(
                "package artifact size does not match its descriptor",
                TopicPackageLoadIntegrityError,
            )
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        destination_descriptor = os.open(destination, flags, 0o600)
        opened = os.fstat(source_descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            _error(
                "package artifact changed before copying",
                TopicPackageLoadIntegrityError,
            )
        digest = hashlib.sha256()
        copied = 0
        while copied < expected_size:
            chunk = os.read(
                source_descriptor, min(_CHUNK_BYTES, expected_size - copied + 1)
            )
            if not chunk:
                _error(
                    "package artifact was truncated while copying",
                    TopicPackageLoadIntegrityError,
                )
            if copied + len(chunk) > expected_size:
                _error(
                    "package artifact grew while copying",
                    TopicPackageLoadIntegrityError,
                )
            _write_all(destination_descriptor, chunk)
            digest.update(chunk)
            copied += len(chunk)
        sentinel = os.read(source_descriptor, 1)
        if sentinel:
            _error(
                "package artifact grew while copying", TopicPackageLoadIntegrityError
            )
        if os.fstat(source_descriptor).st_size != expected_size:
            _error(
                "package artifact changed while copying", TopicPackageLoadIntegrityError
            )
        if os.fstat(destination_descriptor).st_size != expected_size:
            _error("package cache copy has the wrong size", TopicPackageLoadIOError)
        os.fsync(destination_descriptor)
        if digest.hexdigest() != expected_sha256 or copied != expected_size:
            _error(
                "package artifact checksum does not match its descriptor",
                TopicPackageLoadIntegrityError,
            )
    except TopicPackageLoadError:
        raise
    except (OSError, ValueError):
        _error("package artifact could not be copied", TopicPackageLoadIOError)
    finally:
        for descriptor in (source_descriptor, destination_descriptor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _reject_json_constant(value: str) -> object:
    del value
    raise ValueError("nonstandard JSON number")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _parse_manifest(payload: bytes) -> TopicPackageManifest:
    try:
        raw_text = payload.decode("utf-8")
        raw = json.loads(
            raw_text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(raw, dict):
            raise ValueError
        manifest = TopicPackageManifest.model_validate_json(raw_text)
        CorpusManifest.model_validate(
            manifest.corpus_manifest.model_dump(mode="python")
        )
        return manifest
    except TopicPackageLoadError:
        raise
    except Exception:
        _error("topic package manifest is invalid", TopicPackageLoadValidationError)


def _verify_index(index: TopicIndex, topics: tuple[Topic, ...]) -> None:
    try:
        index.validate_topic_contents(topics)
    except Exception:
        _error(
            "topic index contents do not match JSONL", TopicPackageLoadValidationError
        )


class LoadedTopicPackage:
    """A verified package view retaining only immutable metadata and its index."""

    def __init__(
        self,
        manifest: TopicPackageManifest,
        summary: TopicCorpusSummary,
        index: TopicIndex,
        cleanup: TemporaryDirectory[str],
    ) -> None:
        self._manifest = manifest
        self._summary = summary
        self._index: TopicIndex | None = index
        self._cleanup: TemporaryDirectory[str] | None = cleanup
        self._closed = False

    def _open(self) -> tuple[TopicPackageManifest, TopicCorpusSummary, TopicIndex]:
        index = self._index
        if self._closed or index is None:
            _error("topic package is closed")
        return self._manifest, self._summary, index

    @property
    def manifest(self) -> TopicPackageManifest:
        return self._open()[0]

    @property
    def summary(self) -> TopicCorpusSummary:
        return self._open()[1]

    @property
    def index(self) -> TopicIndex:
        return self._open()[2]

    def close(self) -> None:
        if self._closed:
            return
        index = self._index
        cleanup = self._cleanup
        self._closed = True
        self._index = None
        self._cleanup = None
        error: Exception | None = None
        if index is not None:
            try:
                index.__exit__(None, None, None)
            except Exception as exc:
                error = exc
        if cleanup is not None:
            try:
                cleanup.cleanup()
            except Exception as exc:
                error = error or exc
        if error is not None:
            _error("topic package cleanup failed", TopicPackageLoadIOError)

    def __enter__(self) -> Self:
        self._open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()


def _load_topic_package(
    path: Path,
    *,
    expected_manifest_sha256: str,
    cache_dir: Path,
) -> LoadedTopicPackage:
    """Verify fixed package artifacts into a private cache and serve them read-only.

    The caller-supplied manifest fingerprint is an exact lowercase hexadecimal
    pin. It detects byte changes; it is not a source-authenticity or rights claim.
    The source package is never modified, scanned, or opened by SQLite.
    """
    package = _absolute(path)
    cache = _absolute(cache_dir)
    _check_paths(package, cache)

    manifest_path = package / _FIXED_MANIFEST
    manifest_payload = _read_bounded(manifest_path, MAX_MANIFEST_BYTES)
    if hashlib.sha256(manifest_payload).hexdigest() != expected_manifest_sha256:
        _error("manifest fingerprint does not match", TopicPackageLoadIntegrityError)
    manifest = _parse_manifest(manifest_payload)
    descriptors = {entry.filename: entry for entry in manifest.files}
    if set(descriptors) != {_FIXED_JSONL, _FIXED_INDEX}:
        _error(
            "package artifact names are unsupported", TopicPackageLoadValidationError
        )
    json_descriptor = descriptors[_FIXED_JSONL]
    index_descriptor = descriptors[_FIXED_INDEX]

    cleanup: TemporaryDirectory[str] | None = None
    index: TopicIndex | None = None
    loaded: LoadedTopicPackage | None = None
    try:
        cleanup = TemporaryDirectory(prefix=".topic-package-load-", dir=cache)
        private = Path(cleanup.name)
        json_cache = private / _FIXED_JSONL
        index_cache = private / _FIXED_INDEX
        _copy_verified(
            package / _FIXED_JSONL,
            json_cache,
            expected_size=json_descriptor.bytes,
            expected_sha256=json_descriptor.sha256,
            maximum=MAX_TOTAL_BYTES,
        )
        topics = read_topic_export(
            json_cache,
            max_topics=INDEX_MAX_TOPICS,
            max_total_bytes=MAX_TOTAL_BYTES,
        )
        summary = validate_topic_corpus(
            manifest.corpus_manifest,
            topics,
            max_topics=INDEX_MAX_TOPICS,
            max_total_bytes=MAX_TOTAL_BYTES,
        )
        if dict(summary.language_counts) != dict(manifest.language_counts):
            _error(
                "language counts do not match manifest", TopicPackageLoadValidationError
            )
        _copy_verified(
            package / _FIXED_INDEX,
            index_cache,
            expected_size=index_descriptor.bytes,
            expected_sha256=index_descriptor.sha256,
            maximum=MAX_INDEX_BYTES,
        )
        index = TopicIndex(index_cache)
        _verify_index(index, topics)
        del topics
        loaded = LoadedTopicPackage(manifest, summary, index, cleanup)
        cleanup = None
        index = None
        return loaded
    except TopicPackageLoadError:
        raise
    except Exception:
        _error("topic package load failed")
    finally:
        if loaded is None:
            if index is not None:
                try:
                    index.__exit__(None, None, None)
                except Exception:
                    pass
            if cleanup is not None:
                try:
                    cleanup.cleanup()
                except Exception:
                    pass


def load_topic_package(
    path: Path,
    *,
    expected_manifest_sha256: str,
    cache_dir: Path,
) -> LoadedTopicPackage:
    """Load and verify a resource; close it explicitly or use it with ``with``."""
    if not isinstance(expected_manifest_sha256, str) or not _SHA256_RE.fullmatch(
        expected_manifest_sha256
    ):
        _error(
            "expected manifest fingerprint is required",
            TopicPackageLoadValidationError,
        )
    return _load_topic_package(
        path,
        expected_manifest_sha256=expected_manifest_sha256,
        cache_dir=cache_dir,
    )


__all__ = [
    "LoadedTopicPackage",
    "MAX_INDEX_BYTES",
    "MAX_MANIFEST_BYTES",
    "TopicPackageLoadBoundsError",
    "TopicPackageLoadError",
    "TopicPackageLoadIOError",
    "TopicPackageLoadIntegrityError",
    "TopicPackageLoadPathError",
    "TopicPackageLoadValidationError",
    "load_topic_package",
]
