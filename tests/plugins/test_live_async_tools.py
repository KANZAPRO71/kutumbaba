from __future__ import annotations

from persona_ai.plugins.registry import live_function_declarations, non_blocking_tool_names
from persona_ai.plugins.live_dispatch import live_session_tools


def test_all_registered_io_tools_are_non_blocking():
    names = non_blocking_tool_names()
    assert "get_location_snapshot" in names
    assert "get_device_status" in names
    from persona_ai.plugins import web_search_live  # noqa: F401
    from persona_ai.web.live_web_search import LIVE_WEB_SEARCH_TOOL_NAME

    assert LIVE_WEB_SEARCH_TOOL_NAME in names


def test_declarations_include_non_blocking_behavior():
    from persona_ai.plugins import web_search_live  # noqa: F401

    decls = {d["name"]: d for d in live_function_declarations()}
    for name in non_blocking_tool_names():
        assert decls[name].get("behavior") == "NON_BLOCKING"


def test_live_session_tools_genai_behavior():
    from google.genai import types

    from persona_ai.plugins import web_search_live  # noqa: F401

    tools = live_session_tools(embedded_app=True, async_web_search=True)
    assert tools is not None
    for fn in tools[0].function_declarations or []:
        assert fn.behavior == types.Behavior.NON_BLOCKING
