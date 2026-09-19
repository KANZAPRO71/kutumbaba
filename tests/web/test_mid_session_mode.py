from __future__ import annotations

from persona_ai.conversation.mode_prompt import mid_session_experience_mode_steer
from persona_ai.web.conversation_controller import ConversationController
from persona_ai.web.gemini_live_bridge import apply_live_conversation_mode_switch
from persona_ai.web.live_mode import LiveModeConfig


def test_mid_session_steer_names_new_mode():
    text = mid_session_experience_mode_steer("mop", prev_mode="nongkrong", dialect="papua")
    assert "Mop" in text
    assert "GANTI GAYA" in text
    assert "punchline" in text.lower() or "humor" in text.lower() or "mop" in text.lower()


def test_apply_live_conversation_mode_switch_updates_controller():
    live = LiveModeConfig(mode="natural")
    gov = {
        "conversation_mode": "nongkrong",
        "conv_ctrl": ConversationController.from_live_mode(live, conversation_mode="nongkrong"),
    }
    steer = apply_live_conversation_mode_switch(gov, live, "cerita_tong", dialect="papua")
    assert steer
    assert gov["conversation_mode"] == "cerita_tong"
    assert gov["conv_ctrl"].conversation_mode == "cerita_tong"


def test_apply_live_conversation_mode_switch_noop_same_mode():
    live = LiveModeConfig(mode="natural")
    gov = {"conversation_mode": "mop", "conv_ctrl": ConversationController(conversation_mode="mop")}
    assert apply_live_conversation_mode_switch(gov, live, "mop") is None
