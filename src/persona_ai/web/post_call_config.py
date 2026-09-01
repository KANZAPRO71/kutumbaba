"""Retell Post-Call Data Extraction configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from persona_ai.core.types import PersonalityProfile
from persona_ai.llm.gemini_models import gemini_post_call_model
from persona_ai.personality.preset import read_preset_json

_VALID_FIELD_TYPES = frozenset({"string", "boolean", "number", "enum"})

# Retell default post-call fields
DEFAULT_POST_CALL_FIELDS: tuple[dict[str, str], ...] = (
    {
        "id": "call_summary",
        "name": "Call Summary",
        "type": "string",
        "description": "Brief summary of what was discussed and the outcome.",
    },
    {
        "id": "call_successful",
        "name": "Call Successful",
        "type": "boolean",
        "description": "True if the user's goal was met or the conversation ended naturally.",
    },
    {
        "id": "user_sentiment",
        "name": "User Sentiment",
        "type": "enum",
        "description": "Overall user sentiment: positive, neutral, or negative.",
    },
)


@dataclass(frozen=True)
class PostCallField:
    id: str
    name: str
    type: str = "string"
    description: str = ""

    def schema_fragment(self) -> dict[str, Any]:
        if self.type == "boolean":
            return {"type": "boolean", "description": self.description or self.name}
        if self.type == "number":
            return {"type": "number", "description": self.description or self.name}
        if self.type == "enum" and self.id == "user_sentiment":
            return {
                "type": "string",
                "enum": ["positive", "neutral", "negative"],
                "description": self.description or self.name,
            }
        return {"type": "string", "description": self.description or self.name}


@dataclass(frozen=True)
class PostCallConfig:
    enabled: bool = True
    extraction_model: str | None = None
    fields: tuple[PostCallField, ...] = ()

    def __post_init__(self) -> None:
        if not self.fields:
            object.__setattr__(self, "fields", _default_fields())
        for field in self.fields:
            if field.type not in _VALID_FIELD_TYPES:
                raise ValueError(f"invalid post-call field type: {field.type}")

    def model_name(self) -> str:
        return self.extraction_model or gemini_post_call_model()

    def json_schema(self) -> dict[str, Any]:
        props = {field.id: field.schema_fragment() for field in self.fields}
        return {
            "type": "object",
            "properties": props,
            "required": list(props.keys()),
            "additionalProperties": False,
        }

    def to_client_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "extraction_model": self.model_name(),
            "fields": [
                {
                    "id": f.id,
                    "name": f.name,
                    "type": f.type,
                    "description": f.description,
                }
                for f in self.fields
            ],
        }

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> PostCallConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("live_post_call")
        if not isinstance(block, dict):
            return cls()
        return cls.from_dict(block)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PostCallConfig:
        fields_raw = data.get("fields")
        fields: tuple[PostCallField, ...] = _default_fields()
        if isinstance(fields_raw, list) and fields_raw:
            parsed: list[PostCallField] = []
            for item in fields_raw:
                if not isinstance(item, dict):
                    continue
                field_id = str(item.get("id") or "").strip()
                if not field_id:
                    continue
                parsed.append(
                    PostCallField(
                        id=field_id,
                        name=str(item.get("name") or field_id).strip(),
                        type=str(item.get("type") or "string").strip(),
                        description=str(item.get("description") or "").strip(),
                    )
                )
            if parsed:
                fields = tuple(parsed)
        return cls(
            enabled=bool(data.get("enabled", True)),
            extraction_model=(
                str(data["extraction_model"]).strip()
                if data.get("extraction_model")
                else None
            ),
            fields=fields,
        )


def _default_fields() -> tuple[PostCallField, ...]:
    return tuple(
        PostCallField(
            id=item["id"],
            name=item["name"],
            type=item["type"],
            description=item["description"],
        )
        for item in DEFAULT_POST_CALL_FIELDS
    )
