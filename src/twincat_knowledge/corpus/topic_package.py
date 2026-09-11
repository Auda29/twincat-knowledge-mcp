"""Bounded construction and final-marker publication of topic packages."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, cast

from pydantic import Field, StrictStr, model_validator

from twincat_knowledge.domain.models import StrictModel, VersionText
from twincat_knowledge.domain.topics import Topic

from .manifest import CorpusManifest
from .topic_export import (
    MAX_RECORD_BYTES,
    MAX_TOPICS,
    MAX_TOTAL_BYTES,
    ExportSummary,
    TopicExportBoundsError,
    TopicExportError,
    TopicExportIOError,
    TopicExportPathError,
    TopicExportValidationError,
    read_topic_export,
    write_topic_export,
)
from .topic_index import (
    SCHEMA_VERSION,
    TopicIndex,
    TopicIndexBoundsError,
    TopicIndexError,
    TopicIndexOpenError,
    TopicIndexPathError,
    TopicIndexSchemaError,
    TopicIndexUnavailableError,
    TopicIndexValidationError,
    create_topic_index,
)
from .topic_validation import (
    TopicCorpusBoundsError,
    TopicCorpusValidationError,
    validate_topic_corpus,
)

FORMAT_VERSION: Final = "1.0"
INDEX_FORMAT: Final = "sqlite-fts5"
INDEX_VERSION: Final = SCHEMA_VERSION
_SHA256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
_NONNEGATIVE = Annotated[int, Field(strict=True, ge=0)]


class TopicPackageError(RuntimeError):
    """Base class for controlled topic-package build failures."""


class TopicPackagePathError(TopicPackageError):
    """The package directory or an artifact cannot be published safely."""


class TopicPackageValidationError(TopicPackageError, ValueError):
    """The supplied corpus or generated artifacts are invalid."""


class TopicPackageBoundsError(TopicPackageValidationError):
    """A package bound or generated artifact exceeds a supported limit."""


class TopicPackageIOError(TopicPackageError):
    """A package artifact could not be written, read, or synchronized."""


class TopicPackageFile(StrictModel):
    """Hash and byte facts for one of the two fixed package artifacts."""

    filename: Literal["topics.jsonl", "topics.sqlite"]
    sha256: _SHA256
    bytes: _NONNEGATIVE

    @property
    def name(self) -> str:
        """Compatibility alias for callers using a file-name vocabulary."""
        return self.filename


class _ImmutableCounts(dict[str, int]):
    """A JSON-serializable mapping whose contents cannot be changed."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("language_counts is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable  # type: ignore[assignment]
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable  # type: ignore[assignment]
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]


class TopicPackageManifest(StrictModel):
    """Strict descriptor for a build, excluding a self-referential hash."""

    format_version: VersionText
    corpus_manifest: CorpusManifest
    files: tuple[TopicPackageFile, ...] = Field(min_length=2, max_length=2)
    language_counts: dict[str, _NONNEGATIVE]
    index_format: StrictStr
    index_version: VersionText

    @model_validator(mode="after")
    def validate_fixed_descriptor(self) -> TopicPackageManifest:
        names = tuple(file.filename for file in self.files)
        if names != ("topics.jsonl", "topics.sqlite"):
            raise ValueError("package files must be topics.jsonl and topics.sqlite")
        if any(name not in {"de", "en"} for name in self.language_counts):
            raise ValueError("language_counts contains an unsupported language")
        object.__setattr__(
            self,
            "language_counts",
            _ImmutableCounts(self.language_counts),
        )
        return self


@dataclass(frozen=True, slots=True)
class TopicPackageBuildResult:
    """Immutable facts returned only after the manifest final marker is linked."""

    path: Path
    manifest: TopicPackageManifest
    manifest_sha256: str
    manifest_bytes: int

    @property
    def output_path(self) -> Path:
        """Alias for callers that name the package directory explicitly."""
        return self.path

    @property
    def manifest_path(self) -> Path:
        """Path of the final validity marker."""
        return self.path / "manifest.json"


def _limit(value: object, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TopicPackageBoundsError(f"{name} is outside its supported bound")
    if value < 1 or value > maximum:
        raise TopicPackageBoundsError(f"{name} is outside its supported bound")
    return value


def _limits(
    max_topics: object, max_total_bytes: object, max_record_bytes: object
) -> tuple[int, int, int]:
    return (
        _limit(max_topics, "max_topics", MAX_TOPICS),
        _limit(max_total_bytes, "max_total_bytes", MAX_TOTAL_BYTES),
        _limit(max_record_bytes, "max_record_bytes", MAX_RECORD_BYTES),
    )


def _absolute(path: Path) -> Path:
    try:
        return Path(path).absolute()
    except (OSError, RuntimeError, TypeError, ValueError):
        raise TopicPackagePathError("topic package path is invalid") from None


def _new_directory(path: Path) -> Path:
    output = _absolute(path)
    try:
        if not output.parent.is_dir():
            raise TopicPackagePathError("topic package parent directory is unavailable")
        output.mkdir(mode=0o700, exist_ok=False)
    except TopicPackageError:
        raise
    except (OSError, RuntimeError):
        raise TopicPackagePathError(
            "topic package output directory must be new"
        ) from None
    return output


def _check_manifest(manifest: CorpusManifest) -> None:
    try:
        if not isinstance(manifest, CorpusManifest):
            raise ValueError
        CorpusManifest.model_validate(manifest.model_dump(mode="python"))
    except Exception:
        raise TopicPackageValidationError(
            "supplied corpus manifest is invalid"
        ) from None


def _artifact_facts(path: Path) -> tuple[int, str]:
    descriptor: int | None = None
    try:
        if path.is_symlink():
            raise TopicPackagePathError("package artifact must not be a symlink")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise TopicPackagePathError("package artifact must be a regular file")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        return total, digest.hexdigest()
    except TopicPackageError:
        raise
    except (OSError, ValueError):
        raise TopicPackageIOError("package artifact could not be read") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _publish_manifest(output: Path, payload: bytes) -> None:
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=".topic-package-manifest-", dir=output
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output / "manifest.json")
        except FileExistsError:
            raise TopicPackagePathError("package manifest must be new") from None
        except OSError:
            raise TopicPackagePathError(
                "package manifest publication requires same-filesystem hard links"
            ) from None
    except TopicPackageError:
        raise
    except OSError:
        raise TopicPackageIOError("package manifest could not be written") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _translate(error: Exception) -> TopicPackageError:
    if isinstance(
        error,
        (
            TopicPackageBoundsError,
            TopicPackageValidationError,
            TopicPackagePathError,
            TopicPackageIOError,
        ),
    ):
        return error
    if isinstance(
        error, (TopicExportBoundsError, TopicIndexBoundsError, TopicCorpusBoundsError)
    ):
        return TopicPackageBoundsError("topic package bound exceeded")
    if isinstance(error, TopicIndexPathError):
        return TopicPackagePathError(
            "topic package publication requires same-filesystem hard links"
        )
    if isinstance(
        error, (TopicExportPathError, TopicIndexOpenError, TopicIndexSchemaError)
    ):
        return TopicPackagePathError("topic package path or index is unavailable")
    if isinstance(error, (TopicExportIOError, TopicIndexUnavailableError)):
        return TopicPackageIOError("topic package I/O failed")
    if isinstance(
        error,
        (
            TopicExportValidationError,
            TopicIndexValidationError,
            TopicCorpusValidationError,
        ),
    ):
        return TopicPackageValidationError("topic package contains invalid data")
    if isinstance(error, (TopicExportError, TopicIndexError)):
        return TopicPackageError("topic package build failed")
    return TopicPackageError("topic package build failed")


def build_topic_package(
    path: Path,
    manifest: CorpusManifest,
    topics: Iterable[Topic],
    *,
    max_topics: int = MAX_TOPICS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_record_bytes: int = MAX_RECORD_BYTES,
) -> TopicPackageBuildResult:
    """Build fixed artifacts from one bounded JSONL generation and publish last.

    ``manifest.json`` is a final validity marker, not a directory transaction or
    crash-durability claim. Failure leaves a new incomplete directory for an
    operator to clean up; only private staging files owned here are removed.
    """
    limits = _limits(max_topics, max_total_bytes, max_record_bytes)
    _check_manifest(manifest)
    output = _new_directory(path)
    try:
        jsonl_path = output / "topics.jsonl"
        sqlite_path = output / "topics.sqlite"
        exported: ExportSummary = write_topic_export(
            jsonl_path,
            topics,
            max_topics=limits[0],
            max_total_bytes=limits[1],
            max_record_bytes=limits[2],
        )
        reloaded = read_topic_export(
            jsonl_path,
            max_topics=limits[0],
            max_total_bytes=limits[1],
            max_record_bytes=limits[2],
        )
        summary = validate_topic_corpus(
            manifest,
            reloaded,
            max_topics=limits[0],
            max_total_bytes=limits[1],
            max_record_bytes=limits[2],
        )
        indexed_count = create_topic_index(
            sqlite_path,
            reloaded,
            max_topics=limits[0],
            max_topic_json_bytes=limits[2],
        )
        if indexed_count != len(reloaded):
            raise TopicPackageValidationError("topic index does not match JSONL")
        with TopicIndex(sqlite_path) as index:
            if any(index.get_topic(topic.id) != topic for topic in reloaded):
                raise TopicPackageValidationError("topic index does not match JSONL")

        jsonl_bytes, jsonl_sha = _artifact_facts(jsonl_path)
        sqlite_bytes, sqlite_sha = _artifact_facts(sqlite_path)
        if jsonl_bytes != exported.bytes:
            raise TopicPackageValidationError("JSONL changed during package build")
        package_manifest = TopicPackageManifest(
            format_version=FORMAT_VERSION,
            corpus_manifest=manifest,
            files=(
                TopicPackageFile(
                    filename="topics.jsonl", sha256=jsonl_sha, bytes=jsonl_bytes
                ),
                TopicPackageFile(
                    filename="topics.sqlite", sha256=sqlite_sha, bytes=sqlite_bytes
                ),
            ),
            language_counts=cast(
                dict[str, int],
                {
                    language: summary.language_counts[language]
                    for language in ("de", "en")
                    if language in summary.language_counts
                },
            ),
            index_format=INDEX_FORMAT,
            index_version=str(INDEX_VERSION),
        )
        descriptor = (package_manifest.model_dump_json() + "\n").encode("utf-8")
        manifest_sha = hashlib.sha256(descriptor).hexdigest()
        _publish_manifest(output, descriptor)
        return TopicPackageBuildResult(
            output, package_manifest, manifest_sha, len(descriptor)
        )
    except TopicPackageError:
        raise
    except Exception as error:
        raise _translate(error) from None


__all__ = [
    "FORMAT_VERSION",
    "INDEX_FORMAT",
    "INDEX_VERSION",
    "TopicPackageBuildResult",
    "TopicPackageBoundsError",
    "TopicPackageError",
    "TopicPackageFile",
    "TopicPackageIOError",
    "TopicPackageManifest",
    "TopicPackagePathError",
    "TopicPackageValidationError",
    "build_topic_package",
]
