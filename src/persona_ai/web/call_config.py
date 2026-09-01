"""Retell Call Settings mapped to Persona live voice sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from persona_ai.core.types import PersonalityProfile
from persona_ai.personality.preset import read_preset_json

_VALID_VOICEMAIL_ACTIONS = frozenset({"hangup", "leave_message"})
_VALID_KEYPAD_KEYS = frozenset("0123456789#*")


@dataclass(frozen=True)
class LiveCallConfig:
    """Telephony + session limits from Retell agent Call Settings."""

    # Telephony-only — stored for Retell parity; inactive on browser voice.
    enable_voicemail_detection: bool = False
    voicemail_action: str = "hangup"
    enable_call_screen_message: bool = False
    call_screen_message: str | None = None
    enable_ivr_hangup: bool = False
    ring_duration_ms: int = 30_000

    # Keypad / DTMF — browser maps keyboard 0-9 # * when enabled.
    enable_keypad_detection: bool = False
    keypad_timeout_ms: int = 2500
    keypad_termination_key: str | None = None
    keypad_digit_limit: int | None = None

    # Session watchdog — active on local voice.
    end_call_on_silence_ms: int = 600_000  # 10 minutes
    max_call_duration_ms: int = 3_600_000  # 1 hour

    def __post_init__(self) -> None:
        if self.voicemail_action not in _VALID_VOICEMAIL_ACTIONS:
            raise ValueError("voicemail_action must be hangup or leave_message")
        if self.keypad_timeout_ms < 0:
            raise ValueError("keypad_timeout_ms must be >= 0")
        if self.end_call_on_silence_ms < 0:
            raise ValueError("end_call_on_silence_ms must be >= 0")
        if self.max_call_duration_ms < 0:
            raise ValueError("max_call_duration_ms must be >= 0")
        if self.ring_duration_ms < 0:
            raise ValueError("ring_duration_ms must be >= 0")
        if self.keypad_digit_limit is not None and self.keypad_digit_limit < 1:
            raise ValueError("keypad_digit_limit must be >= 1")
        key = self.keypad_termination_key
        if key is not None and key not in _VALID_KEYPAD_KEYS:
            raise ValueError("keypad_termination_key must be 0-9, #, or *")

    def keypad_complete(self, buffer: str, *, latest_digit: str) -> tuple[bool, str]:
        """True when Retell keypad rules say the AI may respond."""
        digits = buffer
        if self.keypad_termination_key and latest_digit == self.keypad_termination_key:
            trimmed = digits[:-1] if digits.endswith(self.keypad_termination_key) else digits
            return True, trimmed
        if self.keypad_digit_limit and len(digits) >= self.keypad_digit_limit:
            return True, digits[: self.keypad_digit_limit]
        return False, digits

    def to_client_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "enable_voicemail_detection": self.enable_voicemail_detection,
            "voicemail_action": self.voicemail_action,
            "enable_call_screen_message": self.enable_call_screen_message,
            "call_screen_message": self.call_screen_message,
            "enable_ivr_hangup": self.enable_ivr_hangup,
            "ring_duration_ms": self.ring_duration_ms,
            "enable_keypad_detection": self.enable_keypad_detection,
            "keypad_timeout_ms": self.keypad_timeout_ms,
            "keypad_termination_key": self.keypad_termination_key,
            "keypad_digit_limit": self.keypad_digit_limit,
            "end_call_on_silence_ms": self.end_call_on_silence_ms,
            "max_call_duration_ms": self.max_call_duration_ms,
        }

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> LiveCallConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("live_call")
        if not isinstance(block, dict):
            return cls()
        return cls.from_dict(block)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveCallConfig:
        known = {
            "enable_voicemail_detection",
            "voicemail_action",
            "enable_call_screen_message",
            "call_screen_message",
            "enable_ivr_hangup",
            "ring_duration_ms",
            "enable_keypad_detection",
            "keypad_timeout_ms",
            "keypad_termination_key",
            "keypad_digit_limit",
            "end_call_on_silence_ms",
            "max_call_duration_ms",
        }
        kwargs = {k: data[k] for k in known if k in data}
        return cls(**kwargs)
