"""Safe configuration creation and deterministic environment diagnostics."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sqlite3
import stat
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = """# Local operator configuration for twincat-knowledge.
[paths]
# Set this to an approved, local corpus directory before serving.
corpus = ""
# Optional operator snapshot selection and private loader cache.
state = ""
cache = ""
"""


class ConfigError(ValueError):
    """Raised when the operator configuration cannot be read."""


class ConfigFileExistsError(FileExistsError):
    """Raised when init would have to replace an existing path."""


@dataclass(frozen=True, slots=True)
class SnapshotSettings:
    """Resolved operator paths for snapshot commands.

    ``cache_dir`` is optional only for read-only state listing.  Activation,
    rollback, and package loading require an existing cache directory.
    """

    state_dir: Path
    cache_dir: Path | None


@dataclass(frozen=True, slots=True)
class OptionalSnapshotSettings:
    """Resolved optional paths used by the first-run serving command."""

    state_dir: Path | None
    cache_dir: Path | None


_MAX_SNAPSHOT_CONFIG_BYTES = 64 * 1024
_SNAPSHOT_STATE_ENV = "TCK_STATE_DIR"
_SNAPSHOT_CACHE_ENV = "TCK_CACHE_DIR"


def _snapshot_config_bytes(path: Path) -> bytes:
    """Read a bounded regular TOML file without blocking on special files."""
    descriptor: int | None = None
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size > _MAX_SNAPSHOT_CONFIG_BYTES:
            raise OSError
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size > _MAX_SNAPSHOT_CONFIG_BYTES
        ):
            raise OSError
        expected_size = opened.st_size
        payload = bytearray()
        while len(payload) <= _MAX_SNAPSHOT_CONFIG_BYTES:
            chunk = os.read(descriptor, _MAX_SNAPSHOT_CONFIG_BYTES - len(payload) + 1)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > _MAX_SNAPSHOT_CONFIG_BYTES:
                raise OSError
        if (
            os.fstat(descriptor).st_size != expected_size
            or len(payload) != expected_size
        ):
            raise OSError
        return bytes(payload)
    except (OSError, RuntimeError, ValueError):
        raise ConfigError("snapshot configuration could not be read") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _load_snapshot_config(path: Path) -> dict[str, Any]:
    try:
        loaded = tomllib.loads(_snapshot_config_bytes(path).decode("utf-8"))
    except ConfigError:
        raise
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ConfigError("snapshot configuration could not be read") from None
    if not isinstance(loaded, dict):
        raise ConfigError("snapshot configuration could not be read")
    return loaded


def _nonempty_setting(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ConfigError("snapshot configuration contains an invalid path")
    return value


def _resolve_snapshot_path(value: str, *, base: Path) -> Path:
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        return path.absolute()
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ConfigError("snapshot configuration contains an invalid path") from None


def load_snapshot_settings(
    config_path: str | os.PathLike[str] | None = None,
    *,
    state_dir: str | os.PathLike[str] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    require_cache: bool = True,
) -> SnapshotSettings:
    """Resolve snapshot paths: flags, ``TCK_*``, then TOML.

    The optional config is still parsed whenever supplied, even when flags or
    environment values provide both paths.  Relative TOML paths are anchored
    at the config directory; flag and environment paths use the current
    working directory.  No legacy ``MCP_*`` variables or corpus fallback are
    consulted.
    """
    environment = os.environ if environ is None else environ
    config: dict[str, Any] = {}
    config_base = Path.cwd()
    if config_path is not None:
        try:
            config_file = Path(config_path).expanduser().absolute()
            config_base = config_file.parent
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ConfigError("snapshot configuration could not be read") from None
        config = _load_snapshot_config(config_file)
        paths = config.get("paths")
        if paths is not None and not isinstance(paths, dict):
            raise ConfigError("snapshot configuration paths must be a TOML table")
        if isinstance(paths, dict):
            # Empty TOML strings are the unset placeholders emitted by init.
            state_value = paths.get("state")
            cache_value = paths.get("cache")
            config_state = _nonempty_setting(None if state_value == "" else state_value)
            config_cache = (
                _nonempty_setting(None if cache_value == "" else cache_value)
                if require_cache
                else None
            )
        else:
            config_state = None
            config_cache = None
    else:
        config_state = None
        config_cache = None

    explicit_state = _nonempty_setting(
        os.fspath(state_dir) if state_dir is not None else None
    )
    explicit_cache = (
        _nonempty_setting(os.fspath(cache_dir) if cache_dir is not None else None)
        if require_cache
        else None
    )
    environment_state = (
        None
        if explicit_state is not None
        else _nonempty_setting(environment.get(_SNAPSHOT_STATE_ENV))
    )
    environment_cache = (
        None
        if not require_cache or explicit_cache is not None
        else _nonempty_setting(environment.get(_SNAPSHOT_CACHE_ENV))
    )
    selected_state = explicit_state or environment_state or config_state
    selected_cache = explicit_cache or environment_cache or config_cache

    if selected_state is None or (require_cache and selected_cache is None):
        raise ConfigError("snapshot paths are not configured")
    state_base = Path.cwd() if explicit_state or environment_state else config_base
    cache_base = Path.cwd() if explicit_cache or environment_cache else config_base
    return SnapshotSettings(
        state_dir=_resolve_snapshot_path(selected_state, base=state_base),
        cache_dir=(
            _resolve_snapshot_path(selected_cache, base=cache_base)
            if selected_cache is not None
            else None
        ),
    )


def load_optional_snapshot_settings(
    config_path: str | os.PathLike[str] | None = None,
    *,
    state_dir: str | os.PathLike[str] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> OptionalSnapshotSettings:
    """Resolve optional serving paths with flag/env/TOML priority."""
    environment = os.environ if environ is None else environ
    config: dict[str, Any] = {}
    config_base = Path.cwd()
    if config_path is not None:
        raw_config_path = _nonempty_setting(os.fspath(config_path))
        assert raw_config_path is not None
        try:
            config_file = Path(raw_config_path).expanduser().absolute()
            config_base = config_file.parent
            config = _load_snapshot_config(config_file)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ConfigError("snapshot configuration could not be read") from None
        paths = config.get("paths")
        if paths is not None and not isinstance(paths, dict):
            raise ConfigError("snapshot configuration paths must be a TOML table")
        if isinstance(paths, dict):
            state_value = paths.get("state")
            cache_value = paths.get("cache")
            config_state = _nonempty_setting(None if state_value == "" else state_value)
            config_cache = _nonempty_setting(None if cache_value == "" else cache_value)
        else:
            config_state = None
            config_cache = None
    else:
        config_state = None
        config_cache = None

    explicit_state = _nonempty_setting(
        os.fspath(state_dir) if state_dir is not None else None
    )
    explicit_cache = _nonempty_setting(
        os.fspath(cache_dir) if cache_dir is not None else None
    )
    environment_state = (
        None
        if explicit_state is not None
        else _nonempty_setting(environment.get(_SNAPSHOT_STATE_ENV))
    )
    environment_cache = (
        None
        if explicit_cache is not None
        else _nonempty_setting(environment.get(_SNAPSHOT_CACHE_ENV))
    )
    selected_state = explicit_state or environment_state or config_state
    selected_cache = explicit_cache or environment_cache or config_cache
    state_base = Path.cwd() if explicit_state or environment_state else config_base
    cache_base = Path.cwd() if explicit_cache or environment_cache else config_base
    return OptionalSnapshotSettings(
        state_dir=(
            _resolve_snapshot_path(selected_state, base=state_base)
            if selected_state is not None
            else None
        ),
        cache_dir=(
            _resolve_snapshot_path(selected_cache, base=cache_base)
            if selected_cache is not None
            else None
        ),
    )


def create_default_config(path: str | os.PathLike[str]) -> Path:
    """Create a default TOML file without replacing an existing path.

    The temporary file is fsynced and linked into place.  Linking, rather than
    replacing, makes the final name creation atomic while refusing existing
    regular files, directories, and symlinks.
    """
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise ConfigFileExistsError(str(destination))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(DEFAULT_CONFIG)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_name, destination)
        except FileExistsError as exc:
            raise ConfigFileExistsError(str(destination)) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return destination


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load TOML without exposing configuration values to diagnostics."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as config_file:
            loaded = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("configuration could not be read") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("configuration root must be a TOML table")
    return loaded


_INVALID_CORPUS_CONFIG = object()


def _corpus_config_value(config: dict[str, Any]) -> object:
    paths = config.get("paths")
    if isinstance(paths, dict):
        corpus = paths.get("corpus", "")
    elif paths is None:
        corpus = config.get("corpus", "")
    else:
        return _INVALID_CORPUS_CONFIG
    return corpus


def _check_fts5() -> dict[str, str]:
    try:
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE VIRTUAL TABLE _doctor_fts USING fts5(value)")
    except sqlite3.Error:
        return {"status": "missing", "detail": "SQLite FTS5 is unavailable"}
    return {"status": "ok", "detail": "SQLite FTS5 is available"}


def _check_sdk() -> dict[str, str]:
    try:
        version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return {"status": "missing", "detail": "MCP SDK is not installed"}
    if version != "2.2.0":
        return {"status": "error", "detail": "MCP SDK version is not the required pin"}
    return {"status": "ok", "detail": "MCP SDK pin is installed"}


def diagnose_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Return a secret-free readiness report for an operator config."""
    try:
        config = load_config(path)
    except ConfigError as exc:
        return {
            "status": "error",
            "checks": {"config": {"status": "error", "detail": str(exc)}},
        }

    config_path = Path(path).expanduser()
    corpus_value = _corpus_config_value(config)
    corpus_check: dict[str, str]
    if corpus_value is _INVALID_CORPUS_CONFIG:
        corpus_check = {
            "status": "error",
            "detail": "paths must be a TOML table",
        }
    elif not isinstance(corpus_value, str):
        corpus_check = {
            "status": "error",
            "detail": "paths.corpus must be a string",
        }
    elif not corpus_value:
        corpus_check = {
            "status": "missing",
            "detail": "Corpus is not configured or missing",
        }
    else:
        try:
            configured_corpus = Path(corpus_value).expanduser()
            if not configured_corpus.is_absolute():
                configured_corpus = config_path.absolute().parent / configured_corpus
            exists = configured_corpus.is_dir()
        except (RuntimeError, OSError, ValueError):
            corpus_check = {
                "status": "error",
                "detail": "Configured corpus path could not be resolved or inspected",
            }
        else:
            if exists:
                corpus_check = {
                    "status": "unverified",
                    "detail": "Corpus directory exists but has not been validated",
                }
            else:
                corpus_check = {
                    "status": "missing",
                    "detail": "Configured corpus directory is missing",
                }
    checks: dict[str, dict[str, str]] = {
        "python": {
            "status": "ok" if sys.version_info >= (3, 12) else "error",
            "detail": "Python version is supported"
            if sys.version_info >= (3, 12)
            else "Python 3.12 or newer is required",
        },
        "sdk": _check_sdk(),
        "fts5": _check_fts5(),
        "corpus": corpus_check,
    }
    status = (
        "ok"
        if all(check["status"] == "ok" for check in checks.values())
        else "not_ready"
    )
    return {"status": status, "checks": checks}


def render_diagnosis(report: dict[str, Any]) -> str:
    """Serialize a report deterministically for the JSON CLI mode."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"
