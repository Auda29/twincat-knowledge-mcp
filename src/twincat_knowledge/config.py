"""Safe configuration creation and deterministic environment diagnostics."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sqlite3
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = """# Local operator configuration for twincat-knowledge.
[paths]
# Set this to an approved, local corpus directory before serving.
corpus = ""
"""


class ConfigError(ValueError):
    """Raised when the operator configuration cannot be read."""


class ConfigFileExistsError(FileExistsError):
    """Raised when init would have to replace an existing path."""


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
        configured_corpus = Path(corpus_value).expanduser()
        if not configured_corpus.is_absolute():
            configured_corpus = config_path.absolute().parent / configured_corpus
        if configured_corpus.is_dir():
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
