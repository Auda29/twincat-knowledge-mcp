from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "serve-contract", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _request(request_id: int, method: str, **params: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {"_meta": META, **params},
    }


class _InteractivePipe:
    def __init__(self, command: list[str] | None = None) -> None:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        self.process = subprocess.Popen(
            command
            or [
                sys.executable,
                "-m",
                "twincat_knowledge",
                "serve",
                "--transport",
                "stdio",
            ],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self._lines: queue.Queue[str | None] = queue.Queue(maxsize=16)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self._lines.get(timeout=30)
        assert line is not None
        return json.loads(line)

    def close(self, *, timeout: float = 30.0) -> tuple[int, str]:
        assert self.process.stdin is not None
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)
        self._reader.join(timeout=timeout)
        if self._reader.is_alive():
            raise RuntimeError("stdio reader did not reach EOF")
        assert self.process.stderr is not None
        return self.process.returncode, self.process.stderr.read()


def test_interactive_pipe_timeout_kills_child_and_joins_reader() -> None:
    pipe = _InteractivePipe(
        [
            sys.executable,
            "-c",
            "import time; print('ready', flush=True); time.sleep(60)",
        ]
    )
    try:
        assert pipe._lines.get(timeout=5) == "ready\n"
    finally:
        returncode, _ = pipe.close(timeout=0.01)

    assert returncode is not None
    assert pipe.process.poll() is not None
    assert not pipe._reader.is_alive()


def _serve_process(
    args: list[str], *, input_text: str = "", cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-m", "twincat_knowledge", "serve", *args],
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_configured_empty_state_starts_not_available_in_real_process(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    pipe = _InteractivePipe(
        [
            sys.executable,
            "-m",
            "twincat_knowledge",
            "serve",
            "--state-dir",
            str(state),
            "--cache-dir",
            str(cache),
        ]
    )
    try:
        responses = [
            pipe.send(_request(1, "server/discover")),
            pipe.send(
                _request(
                    2,
                    "tools/call",
                    name="tc_get_corpus_status",
                    arguments={},
                )
            ),
        ]
    finally:
        returncode, stderr = pipe.close()

    assert returncode == 0, stderr
    assert stderr == ""
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[1]["result"]["structuredContent"]["status"] == "not_available"
    assert list(cache.iterdir()) == []
    assert list(state.iterdir()) == []


def test_sigint_reaps_real_server_and_preserves_fixture_state(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("native Windows SIGINT behavior is not asserted until Windows CI")
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    pipe = _InteractivePipe(
        [
            sys.executable,
            "-m",
            "twincat_knowledge",
            "serve",
            "--state-dir",
            str(state),
            "--cache-dir",
            str(cache),
        ]
    )
    state_before = sorted(path.name for path in state.iterdir())
    try:
        response = pipe.send(_request(1, "server/discover"))
        assert response["id"] == 1
        os.kill(pipe.process.pid, signal.SIGINT)
    finally:
        returncode, stderr = pipe.close()

    assert returncode == 1
    assert stderr == "serve startup failed\n"
    assert sorted(path.name for path in state.iterdir()) == state_before
    assert list(cache.iterdir()) == []


def test_malformed_config_fails_before_protocol_in_real_process(tmp_path: Path) -> None:
    config = tmp_path / "malformed.toml"
    config.write_text("[paths\n", encoding="utf-8")

    result = _serve_process(["--config", str(config)], input_text="\n")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "serve startup failed\n"


def _assert_serve_invalid_startup_state_fails_closed(
    tmp_path: Path, scenario: str
) -> None:
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    cache.mkdir()
    if scenario != "missing-state":
        state.mkdir()
    if scenario == "corrupt-pointer":
        (state / "active.json").write_text("{", encoding="utf-8")
    elif scenario == "wrong-pin":
        package = tmp_path / "package"
        package.mkdir()
        (state / "active.json").write_text(
            json.dumps(
                {
                    "format_version": "1.0",
                    "active": {
                        "package_path": str(package.resolve()),
                        "manifest_sha256": "0" * 64,
                        "snapshot_id": "wrong-pin",
                    },
                    "previous": None,
                }
            ),
            encoding="utf-8",
        )
    elif scenario == "invalid-cache":
        cache.rmdir()

    state_before = (
        None
        if not state.exists()
        else {path.name: path.read_bytes() for path in state.iterdir()}
    )
    result = _serve_process(
        ["--state-dir", str(state), "--cache-dir", str(cache)], input_text="\n"
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "serve startup failed\n"
    assert not cache.exists() or list(cache.iterdir()) == []
    state_after = (
        None
        if not state.exists()
        else {path.name: path.read_bytes() for path in state.iterdir()}
    )
    assert state_after == state_before


@pytest.mark.parametrize(
    "scenario", ["missing-state", "corrupt-pointer", "wrong-pin", "invalid-cache"]
)
def test_serve_invalid_startup_state_scenarios(tmp_path: Path, scenario: str) -> None:
    _assert_serve_invalid_startup_state_fails_closed(tmp_path, scenario)


def test_missing_explicit_config_fails_before_protocol_in_real_process(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    state.mkdir()
    cache.mkdir()

    result = _serve_process(
        [
            "--config",
            str(tmp_path / "missing.toml"),
            "--state-dir",
            str(state),
            "--cache-dir",
            str(cache),
        ],
        input_text="\n",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "serve startup failed\n"


def test_installed_style_serve_stdio_handles_modern_wire_without_initialize() -> None:
    requests = [
        _request(1, "server/discover"),
        _request(2, "tools/list"),
        _request(
            3,
            "tools/call",
            name="tc_get_corpus_status",
            arguments={},
        ),
    ]
    with_pipe = _InteractivePipe()
    try:
        responses = [with_pipe.send(request) for request in requests]
    finally:
        returncode, stderr = with_pipe.close()

    assert returncode == 0, stderr
    assert stderr == ""
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[0]["result"]["supportedVersions"] == ["2026-07-28"]
    assert [tool["name"] for tool in responses[1]["result"]["tools"]] == [
        "tc_browse_topics",
        "tc_get_corpus_status",
        "tc_get_topic",
        "tc_search",
    ]
    assert responses[2]["result"]["structuredContent"]["status"] == "not_available"


def test_serve_bad_transport_fails_before_active_protocol() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    child = subprocess.run(
        [sys.executable, "-m", "twincat_knowledge", "serve", "--transport", "http"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert child.returncode == 2
    assert child.stdout == ""
    assert "invalid choice" in child.stderr
