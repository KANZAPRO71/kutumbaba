"""Dispatch Gemini Live server tool calls to local plugins."""

from __future__ import annotations

import logging
from typing import Any

from google.genai import types

from persona_ai.plugins.registry import invoke_tool, live_function_declarations

_log = logging.getLogger(__name__)


def _ensure_web_search_tool_registered() -> None:
    from persona_ai.plugins import web_search_live  # noqa: F401


def _declaration_to_function(d: dict[str, Any]) -> types.FunctionDeclaration:
    behavior_raw = d.get("behavior")
    behavior = None
    if isinstance(behavior_raw, str) and behavior_raw.upper() == "NON_BLOCKING":
        behavior = types.Behavior.NON_BLOCKING
    kwargs: dict[str, Any] = {
        "name": d["name"],
        "description": d.get("description") or "",
        "parameters": types.Schema(**_schema_kwargs(d.get("parameters") or {})),
    }
    if behavior is not None:
        kwargs["behavior"] = behavior
    return types.FunctionDeclaration(**kwargs)


def live_session_tools(
    *,
    embedded_app: bool,
    async_web_search: bool,
) -> list[types.Tool] | None:
    """Merge embedded device tools with optional async web search for Live connect."""
    if not embedded_app and not async_web_search:
        return None
    if embedded_app:
        from persona_ai.plugins import device_context  # noqa: F401
    if async_web_search:
        _ensure_web_search_tool_registered()
    decls = live_function_declarations()
    if not decls:
        return None
    if not embedded_app:
        decls = [d for d in decls if d.get("name") == LIVE_WEB_SEARCH_TOOL_NAME]
        if not decls:
            return None
    functions = [_declaration_to_function(d) for d in decls]
    return [types.Tool(function_declarations=functions)]


def embedded_live_tools() -> list[types.Tool] | None:
    """Backward-compatible alias — embedded device tools only."""
    return live_session_tools(embedded_app=True, async_web_search=False)


def _schema_kwargs(spec: dict[str, Any]) -> dict[str, Any]:
    """Map JSON-schema-ish dict to genai Schema fields."""
    out: dict[str, Any] = {}
    if "type" in spec:
        raw = spec["type"]
        if isinstance(raw, str):
            out["type"] = raw.upper()
        else:
            out["type"] = raw
    if "properties" in spec:
        props = spec["properties"]
        if isinstance(props, dict):
            mapped: dict[str, Any] = {}
            for key, val in props.items():
                if isinstance(val, dict) and "type" in val and isinstance(val["type"], str):
                    mapped[key] = {**val, "type": val["type"].upper()}
                else:
                    mapped[key] = val
            out["properties"] = mapped
        else:
            out["properties"] = props
    if "required" in spec:
        out["required"] = spec["required"]
    return out or {"type": "OBJECT"}


def build_tool_context(gov: dict[str, Any]) -> dict[str, Any]:
    return {
        "embedded_app": bool(gov.get("embedded_app")),
        "conversation_mode": gov.get("conversation_mode"),
        "session_id": gov.get("_telemetry_session_id"),
        "api_key": gov.get("_gemini_api_key") or "",
    }


def function_responses_for_calls(
    function_calls: list[Any],
    gov: dict[str, Any],
) -> list[types.FunctionResponse]:
    ctx = build_tool_context(gov)
    responses: list[types.FunctionResponse] = []
    for call in function_calls:
        name = getattr(call, "name", None) or ""
        call_id = getattr(call, "id", None)
        args = getattr(call, "args", None) or {}
        if not isinstance(args, dict):
            args = {}
        payload = invoke_tool(name, args, ctx)
        _log.info("live tool %s ok=%s", name, payload.get("ok"))
        responses.append(
            types.FunctionResponse(
                id=call_id,
                name=name,
                response=payload,
            )
        )
    return responses
