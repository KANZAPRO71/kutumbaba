"""Conversation controller — conversation mode steering."""

from __future__ import annotations

from persona_ai.web.conversation_controller import ConversationController, DriftCategory
from persona_ai.web.live_mode import LiveModeConfig


def test_curhat_enables_steer_in_natural_mode():
    live = LiveModeConfig(mode="natural")
    conv = ConversationController.from_live_mode(live, conversation_mode="curhat")
    assert conv.deliver_steer is True
    assert conv.steer_cooldown <= 45.0


def test_casual_natural_steer_off():
    live = LiveModeConfig(mode="natural")
    conv = ConversationController.from_live_mode(live, conversation_mode="casual_chat")
    assert conv.deliver_steer is False


def test_curhat_long_reply_triggers_steer():
    conv = ConversationController(conversation_mode="curhat", deliver_steer=True)
    long_text = " ".join(["word"] * 90)
    category = conv.on_model_turn_complete(long_text)
    assert category == DriftCategory.TOO_LONG
    assert conv.state.pending_steer


def test_funny_enables_steer_in_natural_mode():
    live = LiveModeConfig(mode="natural")
    conv = ConversationController.from_live_mode(live, conversation_mode="funny")
    assert conv.deliver_steer is True


def test_funny_long_monolog_triggers_steer():
    conv = ConversationController(conversation_mode="funny", deliver_steer=True)
    long_text = " ".join(["haha"] * 90)
    category = conv.on_model_turn_complete(long_text)
    assert category == DriftCategory.TOO_LONG
    steer = conv.take_pending_steer()
    assert steer and "punchline" in steer.lower()


def test_brainstorm_enables_steer_in_natural_mode():
    live = LiveModeConfig(mode="natural")
    conv = ConversationController.from_live_mode(live, conversation_mode="brainstorm")
    assert conv.deliver_steer is True


def test_brainstorm_menu_question_triggers_steer():
    conv = ConversationController(conversation_mode="brainstorm", deliver_steer=True)
    text = "Mau bahas ide A atau ide B dulu?"
    category = conv.on_model_turn_complete(text)
    assert category == DriftCategory.QUESTION_LOOP
    steer = conv.take_pending_steer()
    assert steer and "yes-and" in steer.lower()


def test_story_enables_steer_in_natural_mode():
    live = LiveModeConfig(mode="natural")
    conv = ConversationController.from_live_mode(live, conversation_mode="story")
    assert conv.deliver_steer is True


def test_story_long_block_triggers_steer():
    conv = ConversationController(conversation_mode="story", deliver_steer=True)
    text = " ".join(["dan"] * 140)
    category = conv.on_model_turn_complete(text)
    assert category == DriftCategory.TOO_LONG


def test_roleplay_menu_triggers_steer():
    conv = ConversationController(conversation_mode="roleplay", deliver_steer=True)
    text = "Mau bahas apa dulu — jadi HR atau jadi teman?"
    category = conv.on_model_turn_complete(text)
    assert category == DriftCategory.MENU_LOOP
    steer = conv.take_pending_steer()
    assert steer and "roleplay" in steer.lower()
