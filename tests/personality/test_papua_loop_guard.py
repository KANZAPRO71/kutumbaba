"""Tests for filler loop detection."""

from __future__ import annotations

from persona_ai.personality.papua_loop_guard import (
    build_pre_turn_loop_nudge,
    build_santai_loop_nudge,
    has_mau_offer_phrase,
    has_santai_loop_phrase,
    is_mau_menu_line,
    is_pure_filler_line,
    is_santai_echo_line,
    mau_offer_needs_nudge,
    note_assistant_turn,
    opener_streak_high,
    pre_turn_loop_nudge_needed,
    santai_loop_needs_nudge,
    should_omit_assistant_from_recap,
)


def test_pure_filler_omitted():
    assert is_pure_filler_line("Adooo.")
    assert is_pure_filler_line("santai saja")
    assert should_omit_assistant_from_recap("hahaha")


def test_santai_echo_detected():
    assert has_santai_loop_phrase("Iyo santai saja toh")
    assert is_santai_echo_line("Iyo santai saja toh")
    assert should_omit_assistant_from_recap("santai saja dong")
    assert should_omit_assistant_from_recap("Iyo santai saja toh")
    assert not has_santai_loop_phrase("Santai di Entrop memang beda — angin sepo-sepo.")


def test_santai_repeat_omitted_from_recap():
    recent = ["iyo santai saja toh"]
    assert should_omit_assistant_from_recap("tenang saja ko", recent=recent)
    assert should_omit_assistant_from_recap("tenang saja ko")


def test_content_with_filler_kept():
    assert not is_pure_filler_line("Adooo... pi tidur sudah.")
    assert not should_omit_assistant_from_recap("Iyo — tadi ko cerita soal kantor kan.")


def test_near_duplicate_omitted():
    a = "iyo kerja parah minggu ini"
    assert should_omit_assistant_from_recap(a, recent=[a])


def test_opener_streak_needs_three():
    gov: dict = {}
    note_assistant_turn(gov, "Adooo iyo.")
    note_assistant_turn(gov, "Adooo.")
    assert not opener_streak_high(gov)
    note_assistant_turn(gov, "Adooo toh.")
    assert opener_streak_high(gov)


def test_mau_menu_detected():
    assert has_mau_offer_phrase("Mau bahas apa nih?")
    assert has_mau_offer_phrase("Ko mau cerita yang mana")
    assert is_mau_menu_line("Mau cerita apa lagi?")
    assert should_omit_assistant_from_recap("Mau ngobrol apa?")
    assert should_omit_assistant_from_recap("Ko mau dengar mop dulu")


def test_mau_repeat_omitted_from_recap():
    assert should_omit_assistant_from_recap("Ko mau bahas apa?", recent=["mau cerita apa"])


def test_mau_streak_triggers_nudge():
    gov: dict = {}
    note_assistant_turn(gov, "Mau bahas apa nih?")
    assert mau_offer_needs_nudge(gov)
    assert pre_turn_loop_nudge_needed(gov)
    nudge = build_pre_turn_loop_nudge(gov)
    assert "ko mau" in nudge.lower()
    assert "dilarang" in nudge.lower()


def test_santai_streak_triggers_nudge():
    gov: dict = {}
    note_assistant_turn(gov, "Iyo santai saja toh.")
    assert santai_loop_needs_nudge(gov)
    nudge = build_santai_loop_nudge()
    assert "santai saja" not in nudge.lower()
    assert "konkret" in nudge.lower()
