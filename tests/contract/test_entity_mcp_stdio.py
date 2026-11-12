"""Exercise typed tools through the actual stdio transport."""

from jsonschema import validate
from test_topic_mcp_stdio import _request, _run_wire


def test_typed_tools_are_discovered_and_callable_over_stdio():
    replies = _run_wire(
        [
            _request(1, "tools/list"),
            _request(
                2,
                "tools/call",
                name="tc_get_symbol",
                arguments={"symbol_id": "missing"},
            ),
            _request(
                3,
                "tools/call",
                name="tc_lookup_error",
                arguments={"code": "0x10", "domain": "ADS"},
            ),
            _request(
                4,
                "tools/call",
                name="tc_find_libraries",
                arguments={"query": "missing", "limit": True},
            ),
        ]
    )
    tools = {tool["name"]: tool for tool in replies[0]["result"]["tools"]}
    assert {
        "tc_find_symbols",
        "tc_get_symbol",
        "tc_find_libraries",
        "tc_get_library",
        "tc_lookup_error",
    } <= tools.keys()
    for reply, name in zip(
        replies[1:3], ("tc_get_symbol", "tc_lookup_error"), strict=True
    ):
        result = reply["result"]
        validate(result["structuredContent"], tools[name]["outputSchema"])
        assert result["structuredContent"]["status"] == "not_found"
        assert result["isError"] is False
    assert replies[3]["error"]["code"] == -32602


def test_populated_wire_calls_and_disambiguation(monkeypatch):
    from pathlib import Path

    import test_topic_mcp_stdio as wire

    monkeypatch.setattr(
        wire, "LAUNCHER", Path(__file__).with_name("entity_mcp_launcher.py")
    )
    with wire._WireSession() as session:
        listed = session.send(_request(1, "tools/list"))["result"]["tools"]
        schemas = {tool["name"]: tool["outputSchema"] for tool in listed}

        def call(number, name, arguments):
            response = session.send(
                _request(number, "tools/call", name=name, arguments=arguments)
            )["result"]["structuredContent"]
            validate(response, schemas[name])
            return response

        symbols = call(2, "tc_find_symbols", {"query": "Run", "limit": 1})
        assert symbols["status"] == "ambiguous" and symbols["next_cursor"]
        symbol = symbols["data"]["items"][0]
        fetched = call(3, "tc_get_symbol", {"symbol_id": symbol["id"]})
        assert (
            fetched["data"]["items"][0]["declaration"]
            == "FUNCTION Run : BOOL\nEND_FUNCTION"
        )
        assert fetched["sources"][0]["section_id"]
        libraries = call(4, "tc_find_libraries", {"query": "Lib0"})
        assert libraries["status"] == "ok"
        library = libraries["data"]["items"][0]
        assert (
            call(5, "tc_get_library", {"library_id": library["id"]})["status"] == "ok"
        )
        errors = call(6, "tc_lookup_error", {"code": "0x10"})
        assert errors["status"] == "ambiguous"
        assert (
            call(7, "tc_lookup_error", {"code": "0x10", "domain": "Domain0"})["status"]
            == "ok"
        )
        assert call(8, "tc_lookup_error", {"code": "16"})["status"] == "not_found"
        malformed = session.send(
            _request(
                9, "tools/call", name="tc_lookup_error", arguments={"code": "0xGG"}
            )
        )
        assert malformed["error"]["code"] == -32602
