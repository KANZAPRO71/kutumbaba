"""Tests for Retell Security & Fallback Settings mapping."""

from __future__ import annotations

from persona_ai.core.types import Message, PersonalityProfile
from persona_ai.policy.engine import PolicyEngine
from persona_ai.policy.types import PiiHandling
from persona_ai.session.models import SessionState
from persona_ai.web.dynamic_variables import merge_dynamic_variables, substitute_dynamic_variables
from persona_ai.web.security_config import LiveSecurityConfig


def test_defaults_match_retell_security_settings() -> None:
    cfg = LiveSecurityConfig()
    assert cfg.storage_mode == "everything"
    assert cfg.retention_days is None
    assert cfg.guardrails_enabled is True
    assert cfg.pii_handling == "allow"
    assert not cfg.pii_redaction_enabled
    assert not cfg.secure_urls_enabled
    assert cfg.secure_url_ttl_hours == 24
    assert not cfg.automatic_fallback


def test_from_profile_reads_live_security_block() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = LiveSecurityConfig.from_profile(profile)
    assert cfg.storage_mode == "everything"
    assert cfg.default_dynamic_variables.get("agent_name") == "Persona"
    assert cfg.fallback_voice_name == "Leda"


def test_pii_redaction_masks_email() -> None:
    cfg = LiveSecurityConfig(pii_redaction_enabled=True, pii_categories=("email",))
    out = cfg.redact_text("Hubungi saya di alice@example.com ya.")
    assert "alice@example.com" not in out
    assert "[REDACTED]" in out


def test_except_pii_storage_mode_redacts_messages() -> None:
    cfg = LiveSecurityConfig(storage_mode="except_pii")
    session = SessionState.new("s1")
    session = session.model_copy(
        update={
            "messages": [
                Message.from_text("user", "Email saya bob@test.com"),
            ]
        }
    )
    filtered = cfg.filter_session_for_storage(session)
    assert "bob@test.com" not in filtered.messages[0].text


def test_basic_attributes_storage_strips_content() -> None:
    cfg = LiveSecurityConfig(storage_mode="basic_attributes")
    session = SessionState.new("s1")
    session = session.model_copy(
        update={"messages": [Message.from_text("user", "Ini rahasia banget")]}
    )
    filtered = cfg.filter_session_for_storage(session)
    assert "rahasia" not in filtered.messages[0].text
    assert "[user turn" in filtered.messages[0].text


def test_guardrails_build_policy_context() -> None:
    cfg = LiveSecurityConfig(pii_handling="refuse", guardrails_enabled=True)
    ctx = cfg.to_policy_context()
    engine = PolicyEngine(ctx)
    result = engine.pre_check("Kirim ke john.doe@mail.com")
    assert result.input_blocked is True
    assert ctx.pii_mode == PiiHandling.REFUSE


def test_automatic_fallback_voice() -> None:
    cfg = LiveSecurityConfig(automatic_fallback=True, fallback_voice_name="Leda")
    assert cfg.effective_fallback_voice("Sulafat") == "Leda"
    assert cfg.effective_fallback_voice("Leda") is None


def test_dynamic_variables_substitution() -> None:
    merged = merge_dynamic_variables(
        {"agent_name": "Persona"},
        {"company": "Acme"},
    )
    text = substitute_dynamic_variables(
        "Hai, saya {{agent_name}} dari {{company}}.",
        merged,
    )
    assert text == "Hai, saya Persona dari Acme."


def test_secure_url_signing() -> None:
    cfg = LiveSecurityConfig(secure_urls_enabled=True, secure_url_ttl_hours=24)
    signed = cfg.sign_url("/api/recording/abc", secret="test-secret", base_url="http://localhost")
    assert signed.startswith("http://localhost/api/recording/abc")
    assert "expires=" in signed
    assert "sig=" in signed
