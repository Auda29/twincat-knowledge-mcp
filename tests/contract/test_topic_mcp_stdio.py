"""Contract tests for the bounded production topic MCP adapter."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import validate
from mcp import types

from twincat_knowledge.mcp_api.topic_server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    WIRE_RESPONSE_LIMIT,
    create_topic_server,
)
from twincat_knowledge.services.topic_queries import TopicQueryService

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = Path(__file__).with_name("topic_mcp_launcher.py")
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {
        "name": "topic-contract-test",
        "version": "1.0.0",
    },
    "io.modelcontextprotocol/clientCapabilities": {},
}
TOOL_NAMES = ["tc_get_corpus_status", "tc_get_topic", "tc_search"]


def _request(request_id: int, method: str, **params: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {"_meta": META, **params},
    }


class _WireSession:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        self.process = subprocess.Popen(
            [sys.executable, str(LAUNCHER)],
            cwd=ROOT,
            env=process_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._stdout_queue: queue.Queue[str | BaseException | None] = queue.Queue(
            maxsize=1
        )
        self._stdout_reader = threading.Thread(
            target=self._read_stdout,
            name="topic-mcp-stdout-reader",
            daemon=True,
        )
        self._stdout_reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            while line := self.process.stdout.readline():
                self._stdout_queue.put(line)
        except BaseException as exc:
            self._stdout_queue.put(exc)
        finally:
            self._stdout_queue.put(None)

    def __enter__(self) -> _WireSession:
        return self

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        process = self.process
        assert process.stdin is not None
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        try:
            item = self._stdout_queue.get(timeout=30)
        except queue.Empty:
            pytest.fail("stdio child did not answer within 30 seconds")
        if item is None:
            pytest.fail("stdio child reached EOF before answering")
        if isinstance(item, BaseException):
            raise AssertionError("stdio child stdout reader failed") from item
        return json.loads(item)

    def __exit__(self, *exc_info: object) -> None:
        process = self.process
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        wait_error: str | None = None
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            wait_error = "stdio child did not close within 30 seconds"
        stderr = process.stderr.read() if process.stderr is not None else ""
        self._stdout_reader.join(timeout=30)
        if self._stdout_reader.is_alive():
            pytest.fail("stdio child stdout reader did not close within 30 seconds")
        if wait_error is not None:
            pytest.fail(wait_error)
        assert process.returncode == 0, stderr
        assert stderr == ""


def _run_wire(
    requests: list[dict[str, Any]], *, env: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    with _WireSession(env) as session:
        return [session.send(request) for request in requests]


def test_topic_server_factory_exposes_exactly_three_tools() -> None:
    server = create_topic_server(TopicQueryService(None))
    tools = server._topic_tools  # type: ignore[attr-defined]

    assert [tool.name for tool in tools] == TOOL_NAMES
    assert len(tools) == 3
    assert all(tool.annotations is not None for tool in tools)
    for tool in tools:
        assert set(tool.annotations.model_dump(by_alias=True, exclude_none=True)) == {
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
        }
        assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }


def test_topic_server_has_no_legacy_extra_capabilities() -> None:
    server = create_topic_server(TopicQueryService(None))
    capabilities = server._lowlevel_server.get_capabilities(  # type: ignore[attr-defined]
        protocol_version=PROTOCOL_VERSION
    )

    dumped: dict[str, Any] = capabilities.model_dump(by_alias=True, exclude_none=True)
    assert set(dumped) == {"tools"}
    assert dumped["tools"] == {"listChanged": False}


def test_modern_discovery_list_and_direct_calls_are_real_wire_messages() -> None:
    responses = _run_wire(
        [
            _request(1, "server/discover"),
            _request(2, "tools/list"),
            _request(
                3,
                "tools/call",
                name="tc_search",
                arguments={"query": "Fixture", "limit": 2},
            ),
            _request(
                4,
                "tools/call",
                name="tc_get_corpus_status",
                arguments={},
            ),
        ]
    )
    discover = responses[0]["result"]
    assert discover["supportedVersions"] == [PROTOCOL_VERSION]
    assert discover["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
    }
    assert set(discover["capabilities"]) == {"tools"}
    assert discover["capabilities"]["tools"] == {"listChanged": False}
    assert len(discover["instructions"]) <= 512

    listed = responses[1]["result"]["tools"]
    assert [tool["name"] for tool in listed] == TOOL_NAMES
    schemas = {tool["name"]: tool for tool in listed}
    for tool in listed:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"].get("additionalProperties") is False
        assert tool["outputSchema"]["type"] == "object"
        assert tool["outputSchema"].get("additionalProperties") is False
        valid_args = {
            "tc_search": {"query": "x"},
            "tc_get_topic": {"topic_id": "x"},
            "tc_get_corpus_status": {},
        }[tool["name"]]
        validate(instance=valid_args, schema=tool["inputSchema"])

    search = responses[2]["result"]
    assert search["resultType"] == "complete"
    assert search["isError"] is False
    assert search["structuredContent"]["status"] == "ok"
    assert len(search["structuredContent"]["data"]["items"]) == 2
    assert "status=ok" in search["content"][0]["text"]
    assert "count=2" in search["content"][0]["text"]
    assert "truncated=true" in search["content"][0]["text"]
    assert search["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
    }
    validate(
        instance=search["structuredContent"],
        schema=schemas["tc_search"]["outputSchema"],
    )

    status = responses[3]["result"]
    assert status["structuredContent"]["status"] == "ok"
    assert status["structuredContent"]["data"]["topic_count"] == 9
    validate(
        instance=status["structuredContent"],
        schema=schemas["tc_get_corpus_status"]["outputSchema"],
    )


def test_direct_call_without_discovery_and_no_corpus_use_same_factory() -> None:
    responses = _run_wire(
        [
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "missing"},
            )
        ],
        env={"TOPIC_MCP_EMPTY": "1"},
    )
    result = responses[0]["result"]
    assert result["structuredContent"]["status"] == "not_available"
    assert result["isError"] is False
    assert "status=not_available" in result["content"][0]["text"]


def test_unknown_topic_and_unsupported_filter_are_explicit_non_successes() -> None:
    responses = _run_wire(
        [
            _request(
                1,
                "tools/call",
                name="tc_get_topic",
                arguments={"topic_id": "not-a-real-topic"},
            ),
            _request(
                2,
                "tools/call",
                name="tc_search",
                arguments={
                    "query": "Fixture",
                    "filters": {"library_id": "not-indexed"},
                },
            ),
        ]
    )
    assert responses[0]["result"]["structuredContent"]["status"] == "not_found"
    assert responses[0]["result"]["isError"] is False
    assert responses[1]["result"]["structuredContent"]["status"] == "error"
    assert responses[1]["result"]["isError"] is True
    assert responses[1]["result"]["structuredContent"]["data"] is None


def test_malformed_arguments_unknown_tool_and_protocol_errors_are_sanitized() -> None:
    responses = _run_wire(
        [
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "x", "limit": True},
            ),
            _request(
                2,
                "tools/call",
                name="tc_search",
                arguments={"query": "x", "unexpected": "no"},
            ),
            _request(
                3,
                "tools/call",
                name="tc_search",
                arguments={"query": "x", "kinds": ["symbols"]},
            ),
            _request(
                4,
                "tools/call",
                name="unknown",
                arguments={},
            ),
            _request(5, "unknown/method"),
        ]
    )
    for response in responses[:2]:
        assert response["error"]["code"] == -32602
        assert "True" not in json.dumps(response)
        assert "unexpected" not in json.dumps(response)
    assert responses[2]["result"]["structuredContent"]["status"] == "not_available"
    assert responses[2]["result"]["isError"] is False
    assert responses[3]["error"]["code"] == -32602
    assert responses[4]["error"]["code"] == -32601


def test_unsupported_version_and_missing_metadata_are_protocol_errors() -> None:
    bad_meta = dict(META)
    bad_meta["io.modelcontextprotocol/protocolVersion"] = "1900-01-01"
    unsupported = _run_wire(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {"_meta": bad_meta},
            }
        ]
    )[0]
    assert unsupported["error"]["code"] == -32022
    assert unsupported["error"]["data"] == {
        "requested": "1900-01-01",
        "supported": [PROTOCOL_VERSION],
    }

    missing = _run_wire(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
        ]
    )[0]
    assert missing["error"]["code"] == -32602
    assert "protocolVersion" not in json.dumps(missing["error"])


def test_oversized_sdk_protocol_error_and_request_id_are_budget_exceptions() -> None:
    oversized_version = "unsupported-" + ("v" * 40_000)
    bad_meta = dict(META)
    bad_meta["io.modelcontextprotocol/protocolVersion"] = oversized_version
    unsupported = _run_wire(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {"_meta": bad_meta},
            }
        ]
    )[0]
    assert unsupported["error"]["code"] == -32022
    assert unsupported["error"]["data"] == {
        "requested": oversized_version,
        "supported": [PROTOCOL_VERSION],
    }
    assert (
        len(json.dumps(unsupported, ensure_ascii=False, separators=(",", ":")).encode())
        > WIRE_RESPONSE_LIMIT
    )

    large_id = "request-" + ("i" * 40_000)
    large_id_request = _request(
        1,
        "tools/call",
        name="tc_get_corpus_status",
        arguments={},
    )
    large_id_request["id"] = large_id
    large_id_response = _run_wire([large_id_request])[0]
    assert large_id_response["id"] == large_id
    assert large_id_response["result"]["structuredContent"]["status"] == "error"
    assert large_id_response["result"]["isError"] is True
    assert (
        len(
            json.dumps(
                large_id_response, ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        > WIRE_RESPONSE_LIMIT
    )


def test_real_pagination_walks_search_and_topic_sections_without_duplicates() -> None:
    with _WireSession() as session:
        first = session.send(
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "Fixture topic 0", "limit": 1},
            )
        )["result"]["structuredContent"]
        topic_id = first["data"]["items"][0]["id"]
        seen_items = [item["id"] for item in first["data"]["items"]]
        cursor = first["next_cursor"]
        while cursor is not None:
            page = session.send(
                _request(
                    1,
                    "tools/call",
                    name="tc_search",
                    arguments={
                        "query": "Fixture topic 0",
                        "limit": 1,
                        "cursor": cursor,
                    },
                )
            )["result"]["structuredContent"]
            seen_items.extend(item["id"] for item in page["data"]["items"])
            cursor = page["next_cursor"]
        assert len(seen_items) == len(set(seen_items))

        cursor = None
        seen_sections: list[str] = []
        while True:
            args: dict[str, Any] = {"topic_id": topic_id, "limit": 1}
            if cursor is not None:
                args["cursor"] = cursor
            page = session.send(
                _request(1, "tools/call", name="tc_get_topic", arguments=args)
            )["result"]["structuredContent"]
            assert page["data"] is not None
            seen_sections.extend(section["id"] for section in page["data"]["sections"])
            cursor = page["next_cursor"]
            if cursor is None:
                assert page["data"]["complete"] is True
                break
    assert len(seen_sections) == 3
    assert len(seen_sections) == len(set(seen_sections))


def test_cursor_is_bound_to_service_and_query_and_responses_fit_wire_budget() -> None:
    with _WireSession() as session:
        first = session.send(
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "Fixture", "limit": 1},
            )
        )
        first_payload = first["result"]["structuredContent"]
        cursor = first_payload["next_cursor"]
        assert cursor is not None
        changed = session.send(
            _request(
                2,
                "tools/call",
                name="tc_search",
                arguments={"query": "different", "limit": 1, "cursor": cursor},
            )
        )["result"]
        assert changed["structuredContent"]["status"] == "error"
        assert changed["isError"] is True
        for response in (first, changed):
            assert (
                len(
                    json.dumps(
                        response, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                )
                <= WIRE_RESPONSE_LIMIT
            )

    stale = _run_wire(
        [
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "Fixture", "limit": 1, "cursor": cursor},
            )
        ]
    )[0]["result"]
    assert stale["structuredContent"]["status"] == "error"
    assert stale["isError"] is True


def test_runtime_service_error_is_fixed_and_never_leaks_exception_details() -> None:
    response = _run_wire(
        [
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "x"},
            )
        ],
        env={"TOPIC_MCP_FAIL": "1"},
    )[0]["result"]
    assert response["structuredContent"]["status"] == "error"
    assert response["isError"] is True
    assert "secret/path" not in json.dumps(response)
    assert response["content"][0]["text"] == (
        "tc_search: status=error; count=0; truncated=false."
    )


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("invalid", "Invalid request parameters"),
        ("unknown", "Unknown tool"),
    ],
)
def test_service_mcp_errors_matching_protocol_messages_are_sanitized(
    mode: str, message: str
) -> None:
    response = _run_wire(
        [
            _request(
                1,
                "tools/call",
                name="tc_search",
                arguments={"query": "x"},
            )
        ],
        env={"TOPIC_MCP_MCP_ERROR": mode},
    )[0]

    result = response["result"]
    assert result["structuredContent"]["status"] == "error"
    assert result["isError"] is True
    assert result["content"][0]["text"] == (
        "tc_search: status=error; count=0; truncated=false."
    )
    assert message not in json.dumps(response)
    assert "TOPSECRET" not in json.dumps(response)
    assert "/private/secret" not in json.dumps(response)


def test_service_cancellation_is_not_translated() -> None:
    class CancelledService(TopicQueryService):
        def search(self, request: object) -> object:
            del request
            raise asyncio.CancelledError

    server = create_topic_server(CancelledService(None))
    handler = server._lowlevel_server._request_handlers["tools/call"].handler  # type: ignore[attr-defined]

    async def invoke() -> None:
        await handler(
            SimpleNamespace(request_id=1),
            types.CallToolRequestParams(name="tc_search", arguments={"query": "x"}),
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(invoke())


def test_stdio_helper_reports_eof_without_hanging() -> None:
    with pytest.raises(BaseException, match="stdio child reached EOF before answering"):
        _run_wire(
            [
                _request(
                    1,
                    "tools/call",
                    name="tc_search",
                    arguments={"query": "x"},
                )
            ],
            env={"TOPIC_MCP_EOF": "1"},
        )
