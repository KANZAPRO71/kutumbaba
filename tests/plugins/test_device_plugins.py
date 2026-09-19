from __future__ import annotations

from unittest.mock import patch

from persona_ai.plugins.registry import invoke_tool, live_function_declarations
from persona_ai.plugins.live_dispatch import embedded_live_tools, function_responses_for_calls


def test_live_declarations_include_device_tools():
    names = {d["name"] for d in live_function_declarations()}
    assert "get_location_snapshot" in names
    assert "get_device_status" in names


def test_embedded_live_tools_builds_genai_tool():
    tools = embedded_live_tools()
    assert tools is not None
    assert len(tools) == 1
    decls = tools[0].function_declarations or []
    assert any(d.name == "get_location_snapshot" for d in decls)


@patch("persona_ai.plugins.device_context._read_android_json")
def test_location_tool_uses_bridge(mock_read):
    mock_read.return_value = {
        "ok": True,
        "latitude": -2.5,
        "longitude": 140.7,
        "accuracy_m": 12.0,
    }
    from persona_ai.plugins import device_context

    device_context._LOCATION_CACHE = None
    out = invoke_tool("get_location_snapshot", {}, {})
    assert out["ok"] is True
    assert out["latitude"] == -2.5


def test_function_responses_for_unknown_tool():
    class Call:
        name = "missing_tool"
        id = "c1"
        args = {}

    responses = function_responses_for_calls([Call()], {"embedded_app": True})
    assert len(responses) == 1
    assert responses[0].response.get("ok") is False
