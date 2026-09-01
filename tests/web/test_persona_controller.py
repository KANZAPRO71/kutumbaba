"""Tests for PersonaController — stages 10–17."""

from __future__ import annotations

from persona_ai.web.persona_controller import (
    PRIORITY_CHATBOT,
    PRIORITY_QUESTIONS,
    PRIORITY_REPEAT,
    PersonaController,
    PersonaControllerConfig,
    ResponseAnalysis,
    analyze_response,
    build_style_adjustment,
    persona_strength_from_drift,
    select_priority,
)


def test_single_mild_phrase_no_steer():
    ctrl = PersonaController(dialect="papua")
    ctrl.on_assistant_finished("Iyo sa paham ko ee.")
    assert ctrl.pending_steer_text() is None
    assert ctrl.state.drift_score == 0


def test_response_analysis_dimensions():
    analysis = analyze_response(
        "Tentu saja! Semoga membantu. Ada lagi yang ingin ditanyakan?"
    )
    assert analysis.chatbot_score >= 4
    assert select_priority(analysis, threshold=4) == PRIORITY_CHATBOT


def test_select_priority_order_repeat_over_chatbot():
    analysis = ResponseAnalysis(
        chatbot_score=4,
        repeat_score=5,
        length_score=2,
        question_score=2,
    )
    assert select_priority(analysis) == PRIORITY_REPEAT


def test_select_priority_chatbot_over_length():
    analysis = ResponseAnalysis(chatbot_score=5, length_score=2)
    assert select_priority(analysis) == PRIORITY_CHATBOT


def test_chatbot_combo_queues_priority_not_steer_text():
    ctrl = PersonaController(
        dialect="papua",
        config=PersonaControllerConfig(steer_cooldown_s=0, intervention_threshold=4),
    )
    ctrl.on_assistant_finished("Mantap cerita ko.")
    ctrl.on_assistant_finished("Iyo toh.")
    ctrl.on_assistant_finished(
        "Tentu saja! Saya paham perasaan ko. Ada lagi yang ingin ko tanyakan?"
    )
    assert ctrl.state.pending_priority == PRIORITY_CHATBOT
    ctrl.finalize_pending_steer()
    assert ctrl.pending_steer_text() is not None
    assert "[STYLE ADJUSTMENT]" in ctrl.pending_steer_text()


def test_deliver_steer_disabled_by_default():
    ctrl = PersonaController(
        dialect="papua",
        config=PersonaControllerConfig(steer_cooldown_s=0, intervention_threshold=4),
    )
    ctrl.on_assistant_finished("Mantap.")
    ctrl.on_assistant_finished("Iyo.")
    ctrl.on_assistant_finished(
        "Tentu saja! Semoga membantu. Ada lagi yang ingin ditanyakan?"
    )
    ctrl.finalize_pending_steer()
    assert ctrl.pending_steer_text() is not None
    assert ctrl.can_deliver_steer() is False


def test_consecutive_questions_trigger():
    ctrl = PersonaController(
        dialect="papua",
        config=PersonaControllerConfig(steer_cooldown_s=0, question_streak_threshold=3),
    )
    ctrl.on_assistant_finished("Mau bahas apa?")
    ctrl.on_assistant_finished("Terus bagaimana?")
    assert ctrl.state.pending_priority is None
    ctrl.on_assistant_finished("Ada lagi?")
    assert ctrl.state.pending_priority == PRIORITY_QUESTIONS


def test_style_adjustment_not_conversational():
    text = build_style_adjustment(PRIORITY_CHATBOT, strength=2)
    assert text.startswith("[STYLE ADJUSTMENT]")
    assert "Do not restart or acknowledge" in text


def test_persona_strength_escalation():
    assert persona_strength_from_drift(4) == 0
    assert persona_strength_from_drift(5) == 1
    assert persona_strength_from_drift(7) == 2
    assert persona_strength_from_drift(9) == 3


def test_cooldown_blocks_repeat_steer():
    ctrl = PersonaController(
        dialect="papua",
        config=PersonaControllerConfig(
            steer_cooldown_s=999,
            deliver_steer=True,
            intervention_threshold=4,
        ),
    )
    ctrl.on_assistant_finished("Mantap.")
    ctrl.on_assistant_finished("Iyo.")
    ctrl.on_assistant_finished(
        "Tentu saja! Saya paham perasaan ko. Ada lagi yang ingin ko tanyakan?"
    )
    ctrl.finalize_pending_steer()
    assert ctrl.can_deliver_steer() is True
    ctrl.mark_steer_delivered(now=1000.0)
    ctrl.on_assistant_finished("Mantap.")
    ctrl.on_assistant_finished("Iyo.")
    ctrl.on_assistant_finished(
        "Tentu saja! Semoga membantu. Ada yang mau ditanyakan lagi?"
    )
    ctrl.finalize_pending_steer()
    assert ctrl.can_deliver_steer(now=1100.0) is False


def test_serialize_roundtrip():
    ctrl = PersonaController(dialect="papua")
    ctrl.on_assistant_finished("Tentu saja!")
    raw = ctrl.to_dict()
    restored = PersonaController.from_dict(raw)
    assert restored.state.drift_score == ctrl.state.drift_score
    assert restored.dialect == "papua"
