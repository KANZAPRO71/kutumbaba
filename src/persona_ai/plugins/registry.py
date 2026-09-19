"""Plugin registry for Gemini Live function calling (embedded Android)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    non_blocking: bool = True


_REGISTRY: dict[str, RegisteredTool] = {}


def register_tool(
    name: str,
    *,
    description: str,
    parameters: dict[str, Any] | None = None,
    handler: ToolHandler,
    non_blocking: bool = True,
) -> None:
    _REGISTRY[name] = RegisteredTool(
        name=name,
        description=description,
        parameters=parameters or {"type": "object", "properties": {}},
        handler=handler,
        non_blocking=non_blocking,
    )


def live_function_declarations() -> list[dict[str, Any]]:
    """OpenAPI-style declarations for google.genai.types.FunctionDeclaration."""
    _ensure_device_tools_registered()
    out: list[dict[str, Any]] = []
    for tool in _REGISTRY.values():
        entry: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        if tool.non_blocking:
            entry["behavior"] = "NON_BLOCKING"
        out.append(entry)
    return out


def non_blocking_tool_names() -> frozenset[str]:
    _ensure_device_tools_registered()
    from persona_ai.plugins import web_search_live  # noqa: F401

    return frozenset(n for n, t in _REGISTRY.items() if t.non_blocking)


def invoke_tool(name: str, args: dict[str, Any] | None, ctx: dict[str, Any]) -> dict[str, Any]:
    tool = _REGISTRY.get(name or "")
    if not tool:
        return {"ok": False, "error": "unknown_tool", "tool": name}
    started = time.monotonic()
    try:
        result = tool.handler(args or {}, ctx)
        if not isinstance(result, dict):
            result = {"ok": True, "output": result}
        result.setdefault("ok", True)
        return result
    except Exception as exc:
        _log.warning("plugin tool %s failed: %s", name, exc)
        return {"ok": False, "error": str(exc), "tool": name}
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _log.info("plugin tool %s %sms", name, elapsed_ms)


def _ensure_device_tools_registered() -> None:
    if "get_location_snapshot" in _REGISTRY:
        return
    from persona_ai.plugins import device_context  # noqa: F401 — registers handlers


def all_tools() -> list[RegisteredTool]:
    _ensure_device_tools_registered()
    return list(_REGISTRY.values())
