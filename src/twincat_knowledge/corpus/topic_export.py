"""Bounded, transparent JSONL export and reload for normalized topics."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from twincat_knowledge.domain.topics import Topic

MAX_TOPICS: Final = 100_000
MAX_TOTAL_BYTES: Final = 64 * 1024 * 1024
MAX_RECORD_BYTES: Final = 1024 * 1024
_UTF8_BOM: Final = b"\xef\xbb\xbf"


class TopicExportError(RuntimeError):
    """Base class for controlled topic-export failures."""


class TopicExportPathError(TopicExportError):
    """The export path is unavailable or cannot be published safely."""


class TopicExportValidationError(TopicExportError, ValueError):
    """A topic record or export option is invalid."""


class TopicExportBoundsError(TopicExportValidationError):
    """An export option, record, file, or row count exceeds its bound."""


class TopicExportIOError(TopicExportError):
    """The export could not be read or written."""


@dataclass(frozen=True, slots=True)
class ExportSummary:
    """Facts about the exact bytes published by an export."""

    count: int
    bytes: int
    sha256: str


def _check_limit(value: object, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TopicExportValidationError(f"{name} must be an integer")
    if value < 1 or value > maximum:
        raise TopicExportBoundsError(f"{name} is outside its supported bound")
    return value


def _limits(
    max_topics: object, max_total_bytes: object, max_record_bytes: object
) -> tuple[int, int, int]:
    return (
        _check_limit(max_topics, "max_topics", MAX_TOPICS),
        _check_limit(max_total_bytes, "max_total_bytes", MAX_TOTAL_BYTES),
        _check_limit(max_record_bytes, "max_record_bytes", MAX_RECORD_BYTES),
    )


def _absolute_path(path: Path) -> Path:
    try:
        return Path(path).absolute()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise TopicExportPathError("topic export path is invalid") from exc


def _new_output(path: Path) -> Path:
    output = _absolute_path(path)
    try:
        if not output.parent.is_dir():
            raise TopicExportPathError("topic export parent directory is unavailable")
        if output.exists() or output.is_symlink():
            raise TopicExportPathError("topic export output must be new")
    except TopicExportError:
        raise
    except (OSError, RuntimeError) as exc:
        raise TopicExportPathError("topic export path is unavailable") from exc
    return output


def _record_bytes(topic: Topic) -> bytes:
    try:
        # Do not dump through an intermediate model or normalize its text: the
        # model's own JSON representation is the package record.
        return (topic.model_dump_json() + "\n").encode("utf-8")
    except (UnicodeError, TypeError, ValueError) as exc:
        raise TopicExportValidationError("topic serialization failed") from exc
    except Exception as exc:
        raise TopicExportValidationError("topic serialization failed") from exc


def _write_records(
    staging: Path,
    topics: Iterable[Topic],
    max_topics: int,
    max_total_bytes: int,
    max_record_bytes: int,
) -> ExportSummary:
    digest = hashlib.sha256()
    count = 0
    total = 0
    seen_ids: set[str] = set()
    try:
        with staging.open("xb") as stream:
            for topic in topics:
                count += 1
                if count > max_topics:
                    raise TopicExportBoundsError("topic count exceeds its supported bound")
                if not isinstance(topic, Topic):
                    raise TopicExportValidationError(
                        "topics must contain only Topic models"
                    )
                if topic.id in seen_ids:
                    raise TopicExportValidationError("duplicate topic id")
                seen_ids.add(topic.id)
                record = _record_bytes(topic)
                record_bytes = len(record) - 1
                if record_bytes > max_record_bytes:
                    raise TopicExportBoundsError(
                        "topic record exceeds its supported byte bound"
                    )
                total += len(record)
                if total > max_total_bytes:
                    raise TopicExportBoundsError(
                        "export exceeds its supported byte bound"
                    )
                stream.write(record)
                digest.update(record)
            stream.flush()
            os.fsync(stream.fileno())
    except TopicExportError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise TopicExportIOError("topic export could not be written") from exc
    except Exception as exc:
        raise TopicExportError("topic iterator failed") from exc
    return ExportSummary(count=count, bytes=total, sha256=digest.hexdigest())


def write_topic_export(
    path: Path,
    topics: Iterable[Topic],
    *,
    max_topics: int = MAX_TOPICS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_record_bytes: int = MAX_RECORD_BYTES,
) -> ExportSummary:
    """Build a new JSONL export privately and publish it without replacement.

    Each record is exactly ``Topic.model_dump_json()`` encoded as UTF-8 and
    followed by one LF.  The SHA-256 covers those published bytes only; it is
    a corruption check, not a trust or source-authenticity assertion.
    """
    limits = _limits(max_topics, max_total_bytes, max_record_bytes)
    output = _new_output(path)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".topic-export-", dir=output.parent
        ) as private_dir:
            staging = Path(private_dir) / "topics.jsonl"
            summary = _write_records(staging, topics, *limits)
            try:
                # Hard-link publication refuses an existing target. There is no
                # rename/replace fallback, including on filesystems without links.
                os.link(staging, output)
            except FileExistsError as exc:
                raise TopicExportPathError("topic export output must be new") from exc
            except OSError as exc:
                raise TopicExportPathError(
                    "topic export publication requires same-filesystem hard links"
                ) from exc
            return summary
    except TopicExportError:
        raise
    except OSError as exc:
        raise TopicExportIOError("topic export could not be written") from exc
    except Exception as exc:
        raise TopicExportError("topic export could not be written") from exc


def _read_record(line: bytes) -> Topic:
    if _UTF8_BOM in line:
        raise TopicExportValidationError("UTF-8 BOM is not allowed")
    payload = line[:-1] if line.endswith(b"\n") else line
    if not payload.strip():
        raise TopicExportValidationError("blank JSONL records are not allowed")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TopicExportValidationError("topic export is not valid UTF-8") from exc
    try:
        return Topic.model_validate_json(text)
    except (TypeError, ValueError) as exc:
        raise TopicExportValidationError("topic export contains invalid topic JSON") from exc
    except Exception as exc:
        raise TopicExportValidationError("topic export contains invalid topic JSON") from exc


def read_topic_export(
    path: Path,
    *,
    max_topics: int = MAX_TOPICS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_record_bytes: int = MAX_RECORD_BYTES,
) -> tuple[Topic, ...]:
    """Read a bounded JSONL export without changing the file.

    The final record may omit its LF.  Every non-empty line must still contain
    exactly one valid UTF-8 JSON ``Topic`` object; records retain file order.
    """
    max_topic_count, total_limit, record_limit = _limits(
        max_topics, max_total_bytes, max_record_bytes
    )
    input_path = _absolute_path(path)
    try:
        # This preflight is only an early rejection. Incremental accounting
        # below remains authoritative if a file grows after stat().
        if input_path.stat().st_size > total_limit:
            raise TopicExportBoundsError("export exceeds its supported byte bound")
        with input_path.open("rb") as stream:
            topics: list[Topic] = []
            seen_ids: set[str] = set()
            total = 0
            while True:
                # max+2 distinguishes an overlong line from a permitted line
                # with its one-byte LF, without allocating an unbounded buffer.
                line = stream.readline(record_limit + 2)
                if not line:
                    break
                total += len(line)
                if total > total_limit:
                    raise TopicExportBoundsError("export exceeds its supported byte bound")
                if len(line) > record_limit + 1 or (
                    len(line) == record_limit + 1 and not line.endswith(b"\n")
                ):
                    raise TopicExportBoundsError(
                        "topic record exceeds its supported byte bound"
                    )
                topic = _read_record(line)
                if topic.id in seen_ids:
                    raise TopicExportValidationError("duplicate topic id")
                seen_ids.add(topic.id)
                topics.append(topic)
                if len(topics) > max_topic_count:
                    raise TopicExportBoundsError("topic count exceeds its supported bound")
            return tuple(topics)
    except TopicExportError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise TopicExportIOError("topic export could not be read") from exc
    except Exception as exc:
        raise TopicExportError("topic export could not be read") from exc


__all__ = [
    "ExportSummary",
    "MAX_RECORD_BYTES",
    "MAX_TOPICS",
    "MAX_TOTAL_BYTES",
    "TopicExportBoundsError",
    "TopicExportError",
    "TopicExportIOError",
    "TopicExportPathError",
    "TopicExportValidationError",
    "read_topic_export",
    "write_topic_export",
]
