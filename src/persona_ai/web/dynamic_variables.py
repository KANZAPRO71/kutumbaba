"""Retell default dynamic variables — {{key}} template substitution."""

from __future__ import annotations

import re
from typing import Any, Mapping

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def merge_dynamic_variables(
    defaults: Mapping[str, str] | None,
    *overrides: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Later mappings win; values coerced to str."""
    merged: dict[str, str] = {}
    for block in (defaults, *overrides):
        if not block:
            continue
        for key, value in block.items():
            if value is None:
                continue
            merged[str(key)] = str(value)
    return merged


def substitute_dynamic_variables(template: str, variables: Mapping[str, str]) -> str:
    if not template or not variables:
        return template

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return _VAR_PATTERN.sub(_replace, template)
