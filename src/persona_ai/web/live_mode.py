"""Live session mode — natural S2S vs governed Persona-first pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from persona_ai.core.types import PersonalityProfile
from persona_ai.personality.preset import read_preset_json

_VALID_MODES = frozenset({"natural", "governed"})


@dataclass(frozen=True)
class LiveModeConfig:
    """natural: ChatGPT-like S2S flow. governed: Persona steer before every reply."""

    mode: str = "natural"

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError("mode must be natural or governed")

    @property
    def is_natural(self) -> bool:
        return self.mode == "natural"

    @property
    def is_governed(self) -> bool:
        return self.mode == "governed"

    def response_policy(self) -> str:
        return "live_voice_natural" if self.is_natural else "live_voice"

    def to_client_dict(self) -> dict[str, str]:
        return {"mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveModeConfig:
        raw = data.get("mode", "natural")
        return cls(mode=str(raw).strip().lower() if raw else "natural")

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> LiveModeConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("live_mode")
        if isinstance(block, dict):
            return cls.from_dict(block)
        if isinstance(block, str) and block.strip():
            return cls(mode=block.strip().lower())
        return cls()
