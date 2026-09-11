"""Bounded operator-side selection, activation, and rollback of topic snapshots.

This module owns only the small operator pointer in ``active.json``.  Packages
remain immutable and are verified by :func:`load_topic_package` before a
pointer is published.  The pointer is not an MCP resource and its paths never
belong in model-visible output.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Annotated, Final, NoReturn

from pydantic import Field, StrictStr, model_validator

from twincat_knowledge.domain.models import StrictModel

from .topic_package_load import LoadedTopicPackage, load_topic_package

STATE_FORMAT_VERSION: Final = "1.0"
MAX_STATE_BYTES: Final = 64 * 1024
_STATE_FILENAME: Final = "active.json"
_LOCK_FILENAME: Final = ".active.lock"
_SHA256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
_SNAPSHOT_ID = Annotated[StrictStr, Field(min_length=1, max_length=256)]
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class SnapshotError(RuntimeError):
    """Base class for fail-closed snapshot-operation failures."""


class SnapshotNotFound(SnapshotError):
    """No active pointer exists; this is the typed empty-startup result."""


class SnapshotBusy(SnapshotError):
    """Another operator update owns the fixed update lock."""


class SnapshotReference(StrictModel):
    """Strict immutable operator reference to one verified package generation."""

    package_path: Path
    manifest_sha256: _SHA256
    snapshot_id: _SNAPSHOT_ID

    @model_validator(mode="after")
    def validate_local_resolved_path(self) -> SnapshotReference:
        try:
            path_text = os.fspath(self.package_path)
            if (
                "\x00" in path_text
                or not self.package_path.is_absolute()
                or not self.snapshot_id.strip()
            ):
                raise ValueError
            if self.package_path != self.package_path.resolve(strict=False):
                raise ValueError
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ValueError("package reference path is invalid") from None
        return self


class SnapshotState(StrictModel):
    """The single atomic active/previous pointer state."""

    format_version: StrictStr
    active: SnapshotReference
    previous: SnapshotReference | None = None

    @model_validator(mode="after")
    def validate_supported_version(self) -> SnapshotState:
        if self.format_version != STATE_FORMAT_VERSION:
            raise ValueError("unsupported snapshot state version")
        if self.previous is not None and self.previous == self.active:
            raise ValueError("active and previous snapshots must differ")
        return self


def _fail(message: str = "snapshot operation failed") -> NoReturn:
    raise SnapshotError(message) from None


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    del value
    _fail()


def _path(value: object) -> Path:
    if not isinstance(value, Path):
        _fail()
    try:
        return value
    except (OSError, RuntimeError, TypeError, ValueError):
        _fail()


def _regular_directory(path: Path) -> Path:
    """Return a physical directory, rejecting a symlink at the leaf."""
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            _fail()
        resolved = path.resolve(strict=True)
        resolved_metadata = resolved.lstat()
        if stat.S_ISLNK(resolved_metadata.st_mode) or not stat.S_ISDIR(
            resolved_metadata.st_mode
        ):
            _fail()
        return resolved
    except SnapshotError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        _fail()


def _disjoint(left: Path, right: Path) -> None:
    try:
        if left == right or left.is_relative_to(right) or right.is_relative_to(left):
            _fail()
    except (RuntimeError, ValueError):
        _fail()


def _operator_layout(
    state_dir: Path, *, package_dir: Path | None, cache_dir: Path
) -> tuple[Path, Path | None, Path]:
    state = _regular_directory(_path(state_dir))
    cache = _regular_directory(_path(cache_dir))
    package = _regular_directory(package_dir) if package_dir is not None else None
    _disjoint(state, cache)
    if package is not None:
        _disjoint(state, package)
        _disjoint(cache, package)
    return state, package, cache


def _pin(value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail()
    return value


def _state_target(state_dir: Path) -> Path:
    target = state_dir / _STATE_FILENAME
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return target
    except (OSError, RuntimeError, ValueError):
        _fail()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        _fail()
    return target


def _open_state_bytes(state_dir: Path) -> bytes:
    target = _state_target(state_dir)
    try:
        expected_size = target.lstat().st_size
        if expected_size > MAX_STATE_BYTES:
            _fail()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
    except SnapshotError:
        raise
    except FileNotFoundError:
        raise SnapshotNotFound("no active snapshot") from None
    except (OSError, RuntimeError, ValueError):
        _fail()

    payload = bytearray()
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            _fail()
        while len(payload) <= MAX_STATE_BYTES:
            chunk = os.read(descriptor, MAX_STATE_BYTES - len(payload) + 1)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_STATE_BYTES:
                _fail()
        final_size = os.fstat(descriptor).st_size
        if final_size != expected_size or len(payload) != expected_size:
            _fail()
        return bytes(payload)
    except SnapshotError:
        raise
    except (OSError, ValueError):
        _fail()
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _revalidate_state(model: object) -> SnapshotState:
    try:
        if not isinstance(model, SnapshotState):
            raise ValueError
        payload = model.model_dump(mode="python")
        return SnapshotState.model_validate(payload)
    except Exception:
        _fail()


def _parse_state(payload: bytes) -> SnapshotState:
    try:
        text = payload.decode("utf-8")
        raw = json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(raw, dict):
            raise ValueError
        state = SnapshotState.model_validate_json(text)
        return _revalidate_state(state)
    except SnapshotError:
        raise
    except Exception:
        _fail()


def read_snapshot_state(state_dir: Path) -> SnapshotState:
    """Read and strictly validate one bounded immutable pointer snapshot."""
    state = _regular_directory(_path(state_dir))
    return _parse_state(_open_state_bytes(state))


def _read_optional_state(state_dir: Path) -> SnapshotState | None:
    target = _state_target(state_dir)
    try:
        target.lstat()
    except FileNotFoundError:
        return None
    return _parse_state(_open_state_bytes(state_dir))


def _reference_path(reference: SnapshotReference) -> Path:
    try:
        path = reference.package_path
        if path != path.resolve(strict=False):
            _fail()
        return path
    except SnapshotError:
        raise
    except (OSError, RuntimeError, ValueError):
        _fail()


def _load_reference(
    reference: SnapshotReference, *, state_dir: Path, cache_dir: Path
) -> LoadedTopicPackage:
    """Load a reference and compare its package snapshot identity."""
    package = _reference_path(reference)
    _operator_layout(state_dir, package_dir=package, cache_dir=cache_dir)
    try:
        loaded = load_topic_package(
            package,
            expected_manifest_sha256=reference.manifest_sha256,
            cache_dir=cache_dir,
        )
    except Exception:
        _fail()
    try:
        if loaded.manifest.corpus_manifest.snapshot_id != reference.snapshot_id:
            loaded.close()
            _fail()
        return loaded
    except SnapshotError:
        raise
    except Exception:
        try:
            loaded.close()
        except Exception:
            pass
        _fail()


def _reference_from_loaded(
    package: Path, pin: str, loaded: LoadedTopicPackage
) -> SnapshotReference:
    try:
        snapshot_id = loaded.manifest.corpus_manifest.snapshot_id
        return SnapshotReference(
            package_path=package,
            manifest_sha256=pin,
            snapshot_id=snapshot_id,
        )
    except Exception:
        _fail()


def _serialize_state(state: SnapshotState) -> bytes:
    checked = _revalidate_state(state)
    try:
        raw = checked.model_dump(mode="python")
        raw["active"]["package_path"] = str(raw["active"]["package_path"])
        if raw["previous"] is not None:
            raw["previous"]["package_path"] = str(raw["previous"]["package_path"])
        payload = (
            json.dumps(
                raw,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except Exception:
        _fail()
    if len(payload) > MAX_STATE_BYTES:
        _fail()
    return payload


def _write_state(state_dir: Path, state: SnapshotState) -> None:
    target = _state_target(state_dir)
    payload = _serialize_state(state)
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".active-", dir=state_dir)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            written = stream.write(payload)
            if written != len(payload):
                _fail()
            stream.flush()
            os.fsync(stream.fileno())
        # Do not allow a pre-existing foreign target to be replaced.
        _state_target(state_dir)
        os.replace(temporary, target)
        temporary = None
    except SnapshotError:
        raise
    except (OSError, RuntimeError, ValueError):
        _fail()
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _acquire_lock(state_dir: Path) -> tuple[Path, int]:
    lock = state_dir / _LOCK_FILENAME
    try:
        metadata = lock.lstat()
    except FileNotFoundError:
        metadata = None
    except (OSError, RuntimeError, ValueError):
        _fail()
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            _fail()
        raise SnapshotBusy("snapshot update is busy") from None

    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(lock, flags, 0o600)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            os.close(descriptor)
            _fail()
        return lock, descriptor
    except SnapshotBusy:
        raise
    except FileExistsError:
        try:
            metadata = lock.lstat()
            if stat.S_ISREG(metadata.st_mode):
                raise SnapshotBusy("snapshot update is busy") from None
        except SnapshotBusy:
            raise
        except (OSError, RuntimeError, ValueError):
            pass
        _fail()
    except (OSError, RuntimeError, ValueError):
        _fail()


def _release_lock(lock: Path, descriptor: int) -> None:
    closed = False
    try:
        os.close(descriptor)
        closed = True
    except OSError:
        pass
    if not closed:
        return
    try:
        lock.unlink()
    except OSError:
        pass


def _with_verified_candidate(package: Path, pin: str, cache: Path) -> SnapshotReference:
    loaded: LoadedTopicPackage | None = None
    try:
        try:
            loaded = load_topic_package(
                package,
                expected_manifest_sha256=pin,
                cache_dir=cache,
            )
        except Exception:
            _fail()
        return _reference_from_loaded(package, pin, loaded)
    finally:
        if loaded is not None:
            try:
                loaded.close()
            except SnapshotError:
                raise
            except Exception:
                _fail()


def activate_snapshot(
    state_dir: Path,
    package_path: Path,
    *,
    expected_manifest_sha256: str,
    cache_dir: Path,
) -> SnapshotState:
    """Verify a candidate, then atomically publish active and previous together."""
    pin = _pin(expected_manifest_sha256)
    state, package, cache = _operator_layout(
        state_dir, package_dir=_path(package_path), cache_dir=cache_dir
    )
    if package is None:
        _fail()
    lock, descriptor = _acquire_lock(state)
    try:
        current = _read_optional_state(state)
        candidate = _with_verified_candidate(package, pin, cache)
        if current is not None and candidate == current.active:
            return current
        next_state = SnapshotState(
            format_version=STATE_FORMAT_VERSION,
            active=candidate,
            previous=None if current is None else current.active,
        )
        _write_state(state, next_state)
        return next_state
    finally:
        _release_lock(lock, descriptor)


def rollback_snapshot(state_dir: Path, *, cache_dir: Path) -> SnapshotState:
    """Verify the previous package, then atomically swap active and previous."""
    state, _, cache = _operator_layout(state_dir, package_dir=None, cache_dir=cache_dir)
    lock, descriptor = _acquire_lock(state)
    try:
        current = _read_optional_state(state)
        if current is None:
            raise SnapshotNotFound("no active snapshot") from None
        if current.previous is None:
            _fail()
        loaded = _load_reference(current.previous, state_dir=state, cache_dir=cache)
        try:
            next_state = SnapshotState(
                format_version=STATE_FORMAT_VERSION,
                active=current.previous,
                previous=current.active,
            )
        finally:
            loaded.close()
        _write_state(state, next_state)
        return next_state
    finally:
        _release_lock(lock, descriptor)


def load_active_snapshot(state_dir: Path, *, cache_dir: Path) -> LoadedTopicPackage:
    """Load the active reference from one pointer-byte snapshot, without locking."""
    state = _regular_directory(_path(state_dir))
    current = _parse_state(_open_state_bytes(state))
    return _load_reference(current.active, state_dir=state, cache_dir=_path(cache_dir))


__all__ = [
    "MAX_STATE_BYTES",
    "STATE_FORMAT_VERSION",
    "SnapshotBusy",
    "SnapshotError",
    "SnapshotNotFound",
    "SnapshotReference",
    "SnapshotState",
    "activate_snapshot",
    "load_active_snapshot",
    "read_snapshot_state",
    "rollback_snapshot",
]
