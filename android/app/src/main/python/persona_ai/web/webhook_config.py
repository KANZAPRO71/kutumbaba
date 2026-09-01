"""Retell Webhook Settings mapped to Persona live voice sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from persona_ai.core.types import PersonalityProfile
from persona_ai.personality.preset import read_preset_json

DEFAULT_WEBHOOK_EVENTS = ("call_started", "call_ended", "call_analyzed")

_VALID_WEBHOOK_EVENTS = frozenset(
    {
        "call_started",
        "call_ended",
        "call_analyzed",
        "transcript_updated",
        "transfer_started",
        "transfer_bridged",
        "transfer_cancelled",
        "transfer_ended",
    }
)


@dataclass(frozen=True)
class LiveWebhookConfig:
    """Agent-level outbound webhook — Retell dashboard Webhook Settings parity."""

    webhook_url: str | None = None
    webhook_timeout_ms: int = 5000
    webhook_events: tuple[str, ...] = DEFAULT_WEBHOOK_EVENTS

    def __post_init__(self) -> None:
        if self.webhook_timeout_ms < 1000 or self.webhook_timeout_ms > 30_000:
            raise ValueError("webhook_timeout_ms must be between 1000 and 30000")
        url = self.webhook_url
        if url is not None:
            cleaned = url.strip()
            if not cleaned:
                object.__setattr__(self, "webhook_url", None)
            elif not cleaned.startswith(("http://", "https://")):
                raise ValueError("webhook_url must be http or https")
            else:
                object.__setattr__(self, "webhook_url", cleaned)
        for event in self.webhook_events:
            if event not in _VALID_WEBHOOK_EVENTS:
                raise ValueError(f"unknown webhook event: {event}")

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def should_emit(self, event: str) -> bool:
        return self.enabled and event in self.webhook_events

    def to_client_dict(self) -> dict[str, str | int | list[str] | bool | None]:
        return {
            "webhook_url": self.webhook_url,
            "webhook_timeout_ms": self.webhook_timeout_ms,
            "webhook_events": list(self.webhook_events),
            "enabled": self.enabled,
        }

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> LiveWebhookConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("live_webhook")
        if not isinstance(block, dict):
            return cls()
        return cls.from_dict(block)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveWebhookConfig:
        known = {"webhook_url", "webhook_timeout_ms", "webhook_events"}
        kwargs = {k: data[k] for k in known if k in data}
        if "webhook_events" in kwargs:
            kwargs["webhook_events"] = tuple(kwargs["webhook_events"])
        return cls(**kwargs)
