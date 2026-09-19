from __future__ import annotations

from persona_ai.web.experience_mode_switch import prepare_live_experience_mode_switch
from persona_ai.web.live_mode_meta_injection import format_meta_override_turn, live_meta_inject_enabled
from persona_ai.web.live_mode import LiveModeConfig


def test_format_meta_override_turn():
    t = format_meta_override_turn("Mode baru: Teman Jalan")
    assert t.startswith("[META_SYSTEM_OVERRIDE:")
    assert "Teman Jalan" in t
    assert t.endswith("]")


def test_prepare_mode_switch_updates_gov():
    gov = {"conversation_mode": "nongkrong"}
    live_mode = LiveModeConfig()
    steer = prepare_live_experience_mode_switch(
        gov, live_mode, "teman_jalan", dialect="papua"
    )
    assert steer is not None
    assert gov["conversation_mode"] == "teman_jalan"
    assert "teman_jalan" in steer.lower() or "Teman Jalan" in steer


def test_prepare_mode_switch_noop_same_mode():
    gov = {"conversation_mode": "mop"}
    live_mode = LiveModeConfig()
    assert prepare_live_experience_mode_switch(gov, live_mode, "mop") is None


def test_live_meta_inject_enabled_default():
    assert live_meta_inject_enabled() is True
