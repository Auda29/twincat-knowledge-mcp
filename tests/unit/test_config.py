from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from twincat_knowledge.config import (
    ConfigFileExistsError,
    create_default_config,
    diagnose_config,
)


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_init_never_overwrites_existing_config(
    tmp_path: Path, existing_kind: str
) -> None:
    config_path = tmp_path / "config.toml"
    original = "[paths]\ncorpus = '/protected/corpus'\n"
    if existing_kind == "file":
        config_path.write_text(original, encoding="utf-8")
    else:
        target = tmp_path / "existing.toml"
        target.write_text(original, encoding="utf-8")
        config_path.symlink_to(target)

    with pytest.raises(ConfigFileExistsError):
        create_default_config(config_path)

    if existing_kind == "file":
        assert config_path.read_text(encoding="utf-8") == original
    else:
        assert config_path.is_symlink()
        assert config_path.read_text(encoding="utf-8") == original


def test_doctor_reports_missing_corpus_without_secrets(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    corpus_path = tmp_path / "not-present-corpus"
    secret = "do-not-print-this-token"
    config_path.write_text(
        f"[paths]\ncorpus = {str(corpus_path)!r}\n\n[auth]\ntoken = {secret!r}\n",
        encoding="utf-8",
    )

    report = diagnose_config(config_path)
    rendered = json.dumps(report, sort_keys=True)

    assert report["status"] == "not_ready"
    assert report["checks"]["corpus"]["status"] == "missing"
    assert report["checks"]["fts5"]["status"] == "ok"
    assert secret not in rendered
    assert str(corpus_path) not in rendered


def test_init_creates_valid_toml_atomically(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.toml"

    create_default_config(config_path)

    assert config_path.is_file()
    assert "[paths]" in config_path.read_text(encoding="utf-8")


def test_cli_doctor_json_has_no_secret_output(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    secret = "cli-secret-value"
    config_path.write_text(
        f"[paths]\ncorpus = '/missing'\n[auth]\ntoken = {secret!r}\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "twincat_knowledge",
            "doctor",
            "--config",
            str(config_path),
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert json.loads(result.stdout)["checks"]["corpus"]["status"] == "missing"
