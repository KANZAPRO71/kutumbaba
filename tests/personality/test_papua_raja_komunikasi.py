"""Tests for smart barge-in, mop balasan, prosody sim."""

from __future__ import annotations

from persona_ai.personality.papua_mop_balasan import is_user_funny_mop, mop_challenge_steering_text
from persona_ai.personality.papua_prosody_sim import normalize_prosody_sim, prosody_sim_prompt_lines
from persona_ai.personality.papua_smart_barge_in import (
    is_challenge_interrupt,
    is_filler_only,
    should_allow_barge_in,
)


class TestSmartBargeIn:
    def test_filler_iyo_rejected(self):
        assert is_filler_only("Iyo")
        assert not should_allow_barge_in({"partial_text": "Iyo"}, transcript="Iyo", dialect="papua")

    def test_challenge_ko_tipu_allowed(self):
        assert is_challenge_interrupt("Ah ko tipu!")
        assert should_allow_barge_in(
            {"user_speech_started_at": 0.0, "partial_text": "Ah ko tipu!"},
            transcript="Ah ko tipu!",
            dialect="papua",
        )

    def test_ganti_mop_allowed(self):
        assert should_allow_barge_in(
            {"partial_text": "Stop sudah! Ganti mop!"},
            transcript="Stop sudah! Ganti mop!",
            dialect="papua",
        )


    def test_natural_speech_interrupt_allowed(self):
        assert should_allow_barge_in(
            {"user_speech_started_at": 0.0},
            transcript="Ko tunggu dulu sa, sa mau tanya",
            dialect="papua",
        )

    def test_client_rms_barge_allowed(self):
        assert should_allow_barge_in({}, transcript="", dialect="papua", client_rms=True)


class TestMopBalasan:
    def test_challenge_prompt(self):
        text = mop_challenge_steering_text()
        assert "kasi sa mop satu" in text.lower()

    def test_user_funny_mop(self):
        assert is_user_funny_mop(
            "Hahaha pace, ada mop lampu merah — polisi tahan dia terus jawab santai toh!"
        )


class TestProsodySim:
    def test_normalize_clamps(self):
        cfg = normalize_prosody_sim({"speech_tempo": 9, "tone_pitch": -1, "mop_frequency": 2})
        assert cfg["speech_tempo"] == 1.5
        assert cfg["tone_pitch"] == 0.5
        assert cfg["mop_frequency"] == 1.0

    def test_prompt_lines_papua(self):
        lines = prosody_sim_prompt_lines("papua", {"speech_tempo": 1.2, "tone_pitch": 0.8, "mop_frequency": 0.9})
        assert lines
        assert any("Tempo" in line for line in lines)
