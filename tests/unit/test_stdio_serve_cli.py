from __future__ import annotations

from pathlib import Path

import pytest

from twincat_knowledge import cli
from twincat_knowledge.config import ConfigError, load_optional_snapshot_settings


def test_serve_defaults_to_stdio_and_accepts_operator_paths() -> None:
    args = cli.build_parser().parse_args(
        [
            "serve",
            "--config",
            "config.toml",
            "--state-dir",
            "state",
            "--cache-dir",
            "cache",
        ]
    )

    assert args.command == "serve"
    assert args.transport == "stdio"
    assert args.config == Path("config.toml")
    assert args.state_dir == Path("state")
    assert args.cache_dir == Path("cache")


def test_unconfigured_serve_starts_empty_service(monkeypatch) -> None:
    seen = []

    def fake_run(service) -> None:
        seen.append(service)

    monkeypatch.setattr(
        "twincat_knowledge.mcp_api.topic_server.run_topic_stdio", fake_run
    )

    assert cli.main(["serve"]) == 0
    assert len(seen) == 1
    assert seen[0]._loaded is None


def test_serve_rejects_malformed_config_without_stdout(tmp_path: Path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[paths\n", encoding="utf-8")

    result = cli.main(["serve", "--config", str(config)])
    captured = capsys.readouterr()

    assert result == 1
    assert captured.out == ""
    assert captured.err == "serve startup failed\n"


def test_optional_paths_use_flags_then_environment_then_config(tmp_path: Path) -> None:
    config = tmp_path / "operator.toml"
    config.write_text(
        "[paths]\nstate = 'toml-state'\ncache = 'toml-cache'\n",
        encoding="utf-8",
    )

    settings = load_optional_snapshot_settings(
        config,
        state_dir="flag-state",
        environ={"TCK_STATE_DIR": "env-state", "TCK_CACHE_DIR": "env-cache"},
    )

    assert settings.state_dir == Path.cwd() / "flag-state"
    assert settings.cache_dir == Path.cwd() / "env-cache"


def test_optional_toml_paths_are_anchored_to_config(tmp_path: Path) -> None:
    config = tmp_path / "operator.toml"
    config.write_text(
        "[paths]\nstate = 'state'\ncache = 'cache'\n",
        encoding="utf-8",
    )

    settings = load_optional_snapshot_settings(config, environ={})

    assert settings.state_dir == tmp_path / "state"
    assert settings.cache_dir == tmp_path / "cache"


def test_cache_only_configuration_fails_closed(tmp_path: Path, capsys) -> None:
    result = cli.main(["serve", "--cache-dir", str(tmp_path / "cache")])
    captured = capsys.readouterr()

    assert result == 1
    assert captured.out == ""
    assert captured.err == "serve startup failed\n"


def test_empty_environment_path_is_not_treated_as_unconfigured() -> None:
    with pytest.raises(ConfigError):
        load_optional_snapshot_settings(environ={"TCK_STATE_DIR": ""})
