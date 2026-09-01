"""Tests for Conversation Flow Controller — full flow spec."""

from __future__ import annotations

from persona_ai.web.conversation_flow_controller import (
    QUESTION_LIMIT,
    WINDOW_TURNS,
    ConversationFlowController,
    FlowDirective,
    ResponseType,
    analyze_assistant_turn,
    analyze_user_turn,
    classify_response,
    decide_next_turn,
    ConversationState,
)


def test_classify_reaction():
    assert classify_response("Aduh, itu baru lucu sekali.") == ResponseType.REACTION


def test_classify_mop_story():
    assert classify_response(
        "Ada satu Pace dulu, Tinus bawa truk kontainer ke Jayapura..."
    ) in (ResponseType.MOP, ResponseType.STORY, ResponseType.COMMENT)


def test_classify_menu_as_question():
    t = classify_response("Mau bahas apa nih? Cuaca atau perjalanan?")
    assert t == ResponseType.QUESTION


def test_menu_detected():
    analysis = analyze_assistant_turn(
        "Mau bahas apa nih? Soal cuaca, tentang perjalanan, atau mau dengar mop lagi?"
    )
    assert analysis.is_menu_slip
    assert analysis.menu_score >= 4


def test_user_santai_comment_only():
    signal = analyze_user_turn("santai aja")
    decision = decide_next_turn(ConversationState(), signal)
    assert decision.directive == FlowDirective.COMMENT_ONLY
    assert not decision.allow_question


def test_user_capek_follow_not_helper():
    signal = analyze_user_turn("Sa capek hari ini, kerja dari pagi.")
    decision = decide_next_turn(ConversationState(), signal)
    assert decision.directive in (FlowDirective.NO_HELPER, FlowDirective.FOLLOW)
    assert not decision.allow_question


def test_short_answer_no_question():
    state = ConversationState()
    signal = analyze_user_turn("Iya.")
    decision = decide_next_turn(state, signal)
    assert decision.directive == FlowDirective.FOLLOW
    assert not decision.allow_question


def test_anti_question_streak():
    state = ConversationState(question_streak=1, must_not_question=True)
    signal = analyze_user_turn("Terus habis itu jadi begini.")
    decision = decide_next_turn(state, signal)
    assert decision.directive == FlowDirective.NO_QUESTION
    assert not decision.allow_question


def test_question_budget_one_per_window():
    state = ConversationState(questions_in_window=QUESTION_LIMIT)
    signal = analyze_user_turn("Terus habis itu jadi ribet di kantor.")
    decision = decide_next_turn(state, signal)
    assert not decision.allow_question
    assert decision.directive == FlowDirective.NO_QUESTION


def test_mop_request_deliver_directly():
    signal = analyze_user_turn("Mo dengar sa pu Mop dong.")
    decision = decide_next_turn(ConversationState(), signal)
    assert decision.directive == FlowDirective.DELIVER_MOP
    assert not decision.allow_question


def test_flow_controller_tracks_question_streak():
    flow = ConversationFlowController()
    flow.on_assistant_finished("Mau dengar mop kah?")
    assert flow.state.question_streak == 1
    assert flow.state.must_not_question is True


def test_flow_controller_no_pre_turn_after_santai():
    flow = ConversationFlowController()
    steer = flow.on_user_final("santai aja")
    assert steer is None
    assert flow.last_decision is not None
    assert flow.last_decision.reason == "user_santai"
    assert flow.last_decision.needs_pre_turn_steer is False


def test_flow_controller_correction_after_menu():
    flow = ConversationFlowController()
    flow.on_assistant_finished(
        "Mau bahas apa nih? Soal cuaca, tentang perjalanan, atau mop?"
    )
    assert flow.take_correction_steer() is None


def test_single_closing_question_no_correction_steer():
    flow = ConversationFlowController()
    flow.on_assistant_finished("Terus habis itu bagaimana?")
    assert flow.take_correction_steer() is None


def test_natural_turns_increment():
    flow = ConversationFlowController()
    flow.on_assistant_finished("Iyo toh Pace, santai saja.")
    assert flow.state.question_streak == 0
    assert flow.state.natural_turns == 1


def test_window_constants():
    assert QUESTION_LIMIT == 1
    assert WINDOW_TURNS == 3


def test_normal_turn_skips_pre_turn_steer():
    flow = ConversationFlowController()
    steer = flow.on_user_final("Terus habis itu jadi ribet di kantor.")
    assert steer is None
    assert flow.last_decision is not None
    assert flow.last_decision.needs_pre_turn_steer is False


    signal = analyze_user_turn("santai aja")
    decision = decide_next_turn(ConversationState(), signal)
    assert decision.directive == FlowDirective.COMMENT_ONLY
    assert not decision.allow_question
    assert decision.needs_pre_turn_steer is False


def test_santai_in_long_sentence_is_normal_intent():
    signal = analyze_user_turn("Peduli sekarang, santai saja.")
    assert signal.intent == "normal"
