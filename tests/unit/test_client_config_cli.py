"""RED-GREEN tests for the operator client-configuration printer."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from twincat_knowledge.cli import main


def _config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text('[paths]\nstate = "./state"\ncache = "./cache"\n')
    return config


def test_print_client_claude_emits_valid_mcp_server_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)

    exit_code = main(
        ["config", "print-client", "--client", "claude", "--config", str(config)]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    block = json.loads(captured.out)
    server = block["mcpServers"]["twincat-knowledge"]
    command = Path(server["command"])
    assert command.is_absolute()
    assert command.is_file()
    assert server["args"] == [
        "serve",
        "--transport",
        "stdio",
        "--config",
        str(config.resolve()),
    ]


def test_print_client_codex_emits_valid_toml_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)

    exit_code = main(
        ["config", "print-client", "--client", "codex", "--config", str(config)]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    block = tomllib.loads(captured.out)
    server = block["mcp_servers"]["twincat-knowledge"]
    assert Path(server["command"]).is_file()
    assert server["args"][:3] == ["serve", "--transport", "stdio"]


def test_print_client_without_config_omits_config_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["config", "print-client", "--client", "claude"])

    captured = capsys.readouterr()
    assert exit_code == 0
    server = json.loads(captured.out)["mcpServers"]["twincat-knowledge"]
    assert server["args"] == ["serve", "--transport", "stdio"]


def test_print_client_rejects_missing_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "config",
            "print-client",
            "--client",
            "claude",
            "--config",
            str(tmp_path / "missing.toml"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "configuration file" in captured.err


def test_print_client_hermes_is_an_explicit_open_item(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "config",
            "print-client",
            "--client",
            "hermes",
            "--config",
            str(_config(tmp_path)),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "not supported" in captured.err
