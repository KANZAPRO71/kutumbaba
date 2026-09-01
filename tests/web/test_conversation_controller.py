"""Tests for unified ConversationController sidecar."""

from __future__ import annotations

import time

from persona_ai.web.conversation_controller import ConversationController, DriftCategory


def test_menu_pattern_triggers_menu_loop():
    ctrl = ConversationController(deliver_steer=True)
    analysis = ctrl.analyze(
        "Mau bahas apa nih? Soal cuaca, tentang perjalanan, atau mau dengar mop lagi?"
    )
    assert analysis["menu_score"] == 3  # hierarchical: selection only, no topic stack
    assert ctrl.decide(analysis) == DriftCategory.MENU_LOOP


def test_menu_overlap_scores_once_per_group():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Mau bahas apa nih?")
    assert analysis["menu_score"] == 3


def test_menu_selection_does_not_stack_topic_substring():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Mau cerita tentang apa?")
    assert analysis["menu_score"] == 3


def test_single_menu_triggers_menu_loop():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Ko mau dengar yang lain lagi kah?")
    assert analysis["menu_score"] == 1  # invitation group only
    assert ctrl.decide(analysis) is None


def test_menu_selection_alone_triggers():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Mau bahas apa nih?")
    assert analysis["menu_score"] == 3
    assert ctrl.decide(analysis) == DriftCategory.MENU_LOOP


def test_observe_queues_menu_steer():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    ctrl.on_model_turn_complete("Mau cerita tentang apa dulu?")
    assert ctrl.state.pending_steer is not None


def test_single_follow_question_not_menu_drift():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Terus habis itu bagaimana?")
    assert analysis["menu_score"] == 0
    assert analysis["offering_question"] == 0
    assert ctrl.decide(analysis) is None


def test_invitation_only_no_immediate_steer():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    category = ctrl.on_model_turn_complete("Ko mau dengar yang lain lagi kah?")
    assert ctrl.state.invitation_streak == 1
    assert category is None
    assert ctrl.state.pending_steer is None


def test_invitation_streak_triggers_question_loop():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    ctrl.on_model_turn_complete("Ko mau dengar yang lain lagi kah?")
    category = ctrl.on_model_turn_complete("Mau dengar mop kah?")
    assert ctrl.state.invitation_streak == 2
    assert category == DriftCategory.QUESTION_LOOP


def test_pivot_question_detected_as_offering():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Tadi lagu apa yang ko dengar?")
    assert analysis["offering_question"] == 1
    assert analysis["menu_score"] == 0


def test_mild_similarity_capped_at_two():
    ctrl = ConversationController()
    ctrl.state.recent_responses = [
        "Iyo toh pace aduh santai ko dong.",
        "Iyo toh pace aduh santai ko lai.",
        "Iyo toh pace aduh santai ko juga.",
    ]
    analysis = ctrl.analyze("Iyo toh pace aduh santai ko nih.")
    assert analysis["repetition_score"] <= 5
    assert analysis["repetition_score"] >= 2


def test_offering_question_streak_triggers_question_loop():
    ctrl = ConversationController()
    ctrl.state.offering_question_streak = 2
    analysis = ctrl.analyze("Terus habis itu bagaimana menurut ko?")
    assert ctrl.decide(analysis) == DriftCategory.QUESTION_LOOP


def test_same_category_cooldown_blocks():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = time.monotonic() - 10
    ctrl.state.last_steer_category = DriftCategory.MENU_LOOP
    assert ctrl.can_steer(DriftCategory.MENU_LOOP) is False


def test_different_category_allowed_during_cooldown():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = time.monotonic() - 10
    ctrl.state.last_steer_category = DriftCategory.MENU_LOOP
    assert ctrl.can_steer(DriftCategory.CHATBOT) is True


def test_natural_turns_increment_when_clean():
    ctrl = ConversationController()
    for text in (
        "Iyo toh Pace, santai saja.",
        "Wah betul tu cerita ko.",
        "Hmm iyo, tra masalah.",
    ):
        ctrl.observe_response(text)
    assert ctrl.state.natural_turns == 3


def test_take_pending_clears():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    ctrl.request_steer(DriftCategory.CHATBOT)
    steer = ctrl.take_pending_steer()
    assert steer is not None
    assert ctrl.state.pending_steer is None


def test_sa_siap_dengar_triggers_chatbot():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Sa siap dengar ini.")
    assert analysis["chatbot_score"] == 3
    assert ctrl.decide(analysis) == DriftCategory.CHATBOT


def test_repetition_near_repeat():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    ctrl.on_model_turn_complete("Aduh, iyo toh. Santai saja ko.")
    category = ctrl.on_model_turn_complete("Aduh iyo toh, santai sudah.")
    assert category == DriftCategory.REPETITION


def test_adoh_repeat_triggers_repetition():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    ctrl.on_model_turn_complete("Adohhhh ko lucu skali.")
    category = ctrl.on_model_turn_complete("Adohhhh iyo toh Pace.")
    assert category == DriftCategory.REPETITION


def test_topic_escape_requires_refusal_and_redirect():
    ctrl = ConversationController()
    analysis = ctrl.analyze(
        "Sa tra bisa bicara toh, itu sensitif sekali. Lebih baik cerita lucu-lucu saja."
    )
    assert analysis["topic_escape_score"] == 3
    assert ctrl.decide(analysis) == DriftCategory.TOPIC_ESCAPE


def test_casual_topic_change_not_escape():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Eh, kita ganti cerita saja.")
    assert analysis["topic_escape_score"] == 0
    assert ctrl.decide(analysis) is None


def test_redirect_alone_not_escape():
    ctrl = ConversationController()
    analysis = ctrl.analyze("Lebih baik cerita lucu-lucu saja.")
    assert analysis["topic_escape_score"] == 0


def test_repetition_priority_over_menu():
    ctrl = ConversationController()
    ctrl.state.recent_responses = ["Aduh iyo toh Pace santai."]
    analysis = ctrl.analyze("Aduh iyo toh Pace santai. Mau bahas apa?")
    assert ctrl.decide(analysis) == DriftCategory.REPETITION


def test_push_forward_after_santai_user_turn():
    ctrl = ConversationController(deliver_steer=True)
    ctrl.state.last_steer_time = 0.0
    ctrl.observe_user_turn("Peduli sekarang, santai saja.")
    assert ctrl.state.last_user_follow_through is True
    category = ctrl.on_model_turn_complete(
        "Iyo santai toh. Terus ko ada cerita apa lagi? Apa yang sedang ko pikirkan?"
    )
    assert category == DriftCategory.PUSH_FORWARD
    assert ctrl.state.pending_steer is not None


def test_follow_through_short_response_not_push():
    ctrl = ConversationController()
    ctrl.observe_user_turn("Santai saja.")
    analysis = ctrl.analyze("Iyo eh, santai saja toh.")
    assert ctrl.decide(analysis) is None
