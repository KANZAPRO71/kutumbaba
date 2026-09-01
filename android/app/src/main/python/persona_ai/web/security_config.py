"""Retell Security & Fallback Settings mapped to Persona live sessions."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from persona_ai.core.types import Message, PersonalityProfile
from persona_ai.personality.preset import read_preset_json
from persona_ai.policy.redact import categories_for_storage_mode, redact_text
from persona_ai.policy.rules import DEFAULT_CRISIS_KEYWORDS, FP4_DEFAULT_DENYLIST
from persona_ai.policy.types import PiiHandling, PolicyContext
from persona_ai.session.models import SessionState
from persona_ai.web.voice_config import normalize_voice_name

_VALID_STORAGE_MODES = frozenset({"everything", "except_pii", "basic_attributes"})
_VALID_PII_HANDLING = frozenset({"allow", "refuse", "redact"})
_VALID_PII_CATEGORIES = frozenset({"email", "phone", "credit_card", "ssn", "address", "name"})


@dataclass(frozen=True)
class LiveSecurityConfig:
    """Security, storage, and fallback settings from Retell agent dashboard."""

    # Data Storage Settings
    storage_mode: str = "everything"
    retention_days: int | None = None  # None = keep forever

    # Personal Info Redaction (PII)
    pii_redaction_enabled: bool = False
    pii_categories: tuple[str, ...] = ()

    # Safety Guardrails → PolicyEngine
    guardrails_enabled: bool = True
    crisis_keywords: tuple[str, ...] = ()
    phrase_denylist: tuple[str, ...] = ()
    slur_denylist: tuple[str, ...] = ()
    pii_handling: str = "allow"
    regulated_domain: bool = False
    required_disclaimer: str | None = None

    # Opt In Secure URLs
    secure_urls_enabled: bool = False
    secure_url_ttl_hours: int = 24

    # Fallback Voice ID
    automatic_fallback: bool = False
    fallback_voice_name: str | None = None

    # Default Dynamic Variables
    default_dynamic_variables: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.storage_mode not in _VALID_STORAGE_MODES:
            raise ValueError("storage_mode must be everything, except_pii, or basic_attributes")
        if self.retention_days is not None and self.retention_days < 0:
            raise ValueError("retention_days must be >= 0 or null")
        if self.pii_handling not in _VALID_PII_HANDLING:
            raise ValueError("pii_handling must be allow, refuse, or redact")
        if self.secure_url_ttl_hours < 1:
            raise ValueError("secure_url_ttl_hours must be >= 1")
        for cat in self.pii_categories:
            if cat not in _VALID_PII_CATEGORIES:
                raise ValueError(f"unknown pii category: {cat}")
        if self.fallback_voice_name is not None:
            object.__setattr__(self, "fallback_voice_name", normalize_voice_name(self.fallback_voice_name))

    def effective_pii_categories(self) -> tuple[str, ...]:
        if self.pii_categories:
            return self.pii_categories
        return categories_for_storage_mode(
            self.storage_mode,
            pii_enabled=self.pii_redaction_enabled,
        )

    def to_policy_context(self) -> PolicyContext:
        if not self.guardrails_enabled:
            return PolicyContext(pii_mode=PiiHandling.ALLOW)
        pii_mode = PiiHandling(self.pii_handling)
        return PolicyContext(
            crisis_keywords=list(self.crisis_keywords or DEFAULT_CRISIS_KEYWORDS),
            regulated_domain=self.regulated_domain,
            required_disclaimer=self.required_disclaimer,
            phrase_denylist=list(self.phrase_denylist or FP4_DEFAULT_DENYLIST),
            slur_denylist=list(self.slur_denylist),
            pii_mode=pii_mode,
        )

    def effective_fallback_voice(self, primary_voice: str) -> str | None:
        if not self.automatic_fallback:
            return None
        primary = normalize_voice_name(primary_voice)
        fallback = normalize_voice_name(self.fallback_voice_name)
        if fallback == primary:
            return None
        return fallback

    def redact_text(self, text: str) -> str:
        if not text:
            return text
        if not self.pii_redaction_enabled and self.storage_mode == "everything":
            return text
        categories = self.effective_pii_categories()
        if not categories:
            return text
        return redact_text(text, categories)

    def filter_session_for_storage(self, session: SessionState) -> SessionState:
        if self.storage_mode == "everything" and not self.pii_redaction_enabled:
            return session
        if self.storage_mode == "basic_attributes":
            return session.model_copy(
                update={
                    "messages": [
                        Message(
                            role=msg.role,
                            text=self._basic_attribute_text(msg),
                            word_count=0,
                        )
                        for msg in session.messages
                    ],
                    "post_call": self._filter_post_call(session.post_call),
                }
            )
        redacted_messages = [
            Message(
                role=msg.role,
                text=self.redact_text(msg.text or ""),
                word_count=len(self.redact_text(msg.text or "").split()),
            )
            for msg in session.messages
        ]
        return session.model_copy(
            update={
                "messages": redacted_messages,
                "post_call": self._filter_post_call(session.post_call),
            }
        )

    def _basic_attribute_text(self, msg: Message) -> str:
        text = (msg.text or "").strip()
        if not text:
            return ""
        return f"[{msg.role} turn, {len(text.split())} words]"

    def _filter_post_call(self, post_call: dict[str, Any] | None) -> dict[str, Any] | None:
        if post_call is None:
            return None
        if self.storage_mode == "basic_attributes":
            return {k: v for k, v in post_call.items() if k in {"call_successful", "user_sentiment"}}
        if self.storage_mode == "except_pii" or self.pii_redaction_enabled:
            filtered: dict[str, Any] = {}
            for key, value in post_call.items():
                if isinstance(value, str):
                    filtered[key] = self.redact_text(value)
                else:
                    filtered[key] = value
            return filtered
        return post_call

    def sign_url(self, path: str, *, secret: str, base_url: str = "") -> str:
        """HMAC-signed URL with expiry — Retell secure URL parity."""
        if not self.secure_urls_enabled:
            return f"{base_url}{path}" if base_url else path
        expires = int(time.time()) + self.secure_url_ttl_hours * 3600
        payload = f"{path}:{expires}"
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        sep = "&" if "?" in path else "?"
        signed = f"{path}{sep}expires={expires}&sig={quote(sig)}"
        return f"{base_url}{signed}" if base_url else signed

    def to_client_dict(self) -> dict[str, bool | int | str | list[str] | dict[str, str] | None]:
        return {
            "storage_mode": self.storage_mode,
            "retention_days": self.retention_days,
            "pii_redaction_enabled": self.pii_redaction_enabled,
            "pii_categories": list(self.pii_categories),
            "guardrails_enabled": self.guardrails_enabled,
            "pii_handling": self.pii_handling,
            "regulated_domain": self.regulated_domain,
            "required_disclaimer": self.required_disclaimer,
            "secure_urls_enabled": self.secure_urls_enabled,
            "secure_url_ttl_hours": self.secure_url_ttl_hours,
            "automatic_fallback": self.automatic_fallback,
            "fallback_voice_name": self.fallback_voice_name,
            "default_dynamic_variables": dict(self.default_dynamic_variables),
        }

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> LiveSecurityConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("live_security")
        if not isinstance(block, dict):
            return cls()
        return cls.from_dict(block)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveSecurityConfig:
        known = {
            "storage_mode",
            "retention_days",
            "pii_redaction_enabled",
            "pii_categories",
            "guardrails_enabled",
            "crisis_keywords",
            "phrase_denylist",
            "slur_denylist",
            "pii_handling",
            "regulated_domain",
            "required_disclaimer",
            "secure_urls_enabled",
            "secure_url_ttl_hours",
            "automatic_fallback",
            "fallback_voice_name",
            "default_dynamic_variables",
        }
        kwargs: dict[str, Any] = {k: data[k] for k in known if k in data}
        if "pii_categories" in kwargs:
            kwargs["pii_categories"] = tuple(kwargs["pii_categories"])
        for list_key in ("crisis_keywords", "phrase_denylist", "slur_denylist"):
            if list_key in kwargs:
                kwargs[list_key] = tuple(kwargs[list_key])
        if "default_dynamic_variables" in kwargs and isinstance(kwargs["default_dynamic_variables"], dict):
            kwargs["default_dynamic_variables"] = {
                str(k): str(v) for k, v in kwargs["default_dynamic_variables"].items()
            }
        return cls(**kwargs)
