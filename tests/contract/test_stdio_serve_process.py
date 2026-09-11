from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

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
    def __init__(self) -> None:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        self.process = subprocess.Popen(
            [
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

    def close(self) -> tuple[int, str]:
        assert self.process.stdin is not None
        self.process.stdin.close()
        self.process.wait(timeout=30)
        assert self.process.stderr is not None
        return self.process.returncode, self.process.stderr.read()


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
