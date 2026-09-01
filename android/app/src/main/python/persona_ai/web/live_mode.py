"""Live session mode — natural S2S vs governed Persona-first pipeline.

natural mode tradeoff (default):
  Pro: faster S2S, less double-speak, no per-turn steer inject.
  Con: less persona corset — Gemini chatbot habits slip through more often.

  Light corset via PersonaController (persona_controller.py):
  - observe assistant turns; accumulate chatbot_score
  - micro-steer only when score >= 3, 3+ questions, or article-length
  - slip_nudge in preset maps to controller steer_cooldown_s
"""

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
    slip_nudge: bool = True
    flow_steer: bool = True
    slip_nudge_cooldown_s: float = 90.0
    persona_refresh_s: float = 240.0

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

    def to_client_dict(self) -> dict[str, str | bool | float]:
        return {
            "mode": self.mode,
            "slip_nudge": self.slip_nudge,
            "slip_nudge_cooldown_s": self.slip_nudge_cooldown_s,
            "persona_refresh_s": self.persona_refresh_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveModeConfig:
        raw = data.get("mode", "natural")
        slip = data.get("slip_nudge", True)
        flow = data.get("flow_steer", True)
        cooldown = data.get("slip_nudge_cooldown_s", 90.0)
        refresh = data.get("persona_refresh_s", 240.0)
        return cls(
            mode=str(raw).strip().lower() if raw else "natural",
            slip_nudge=bool(slip),
            flow_steer=bool(flow),
            slip_nudge_cooldown_s=float(cooldown),
            persona_refresh_s=float(refresh),
        )

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
