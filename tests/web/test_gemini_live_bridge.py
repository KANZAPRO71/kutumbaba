from __future__ import annotations

from persona_ai.web.gemini_live_bridge import (
    _append_ungoverned_audio,
    _apply_natural_allow,
    _floor_event,
    _flush_ungoverned_audio_buffer,
    _is_playable_pcm,
    _is_voice_filler,
    _partial_is_stable,
    _should_close_audio_gate,
    _should_forward_governed_audio,
    _should_open_user_activity,
    _should_schedule_governance_fallback,
    _take_floor,
    _transcript_commit_reason,
    _update_partial_stability,
    MAX_UNGOVERNED_BUFFER_BYTES,
)
from persona_ai.web.persona_live import LiveSteerMode


def _commit_gov(**overrides):
    """Minimal gov dict for commit-reason / VAD commit tests."""
    base = {
        "vad_turn_active": True,
        "user_activity_open": True,
        "gemini_activity_open": True,
        "pending": False,
        "commit_scheduled": False,
        "awaiting_steered_turn": False,
        "final_task": None,
        "activity_started_at": 0.0,
        "last_loud_mic_at": 0.2,
        "had_loud_speech": True,
        "partial_text": "",
        "last_user_transcript": "",
        "activity_end_for_asr": False,
    }
    base.update(overrides)
    return base


def test_greeting_audio_can_play_before_governance():
    assert _should_forward_governed_audio(
        {"greeting_phase": True, "mode": LiveSteerMode.ALLOW, "steer_applied": False}
    )


def test_ungoverned_audio_plays_after_greeting():
    assert _should_forward_governed_audio(
        {"greeting_phase": False, "mode": LiveSteerMode.ALLOW, "steer_applied": False}
    )


def test_ungoverned_audio_plays_during_asr_recovery():
    assert _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "mode": LiveSteerMode.ALLOW,
            "steer_applied": False,
            "activity_end_for_asr": True,
            "awaiting_asr_recovery": True,
            "had_loud_speech": True,
            "turn_peak_mic_rms": 0.08,
        }
    )


def test_natural_mode_forwards_audio_during_asr_wait():
    assert _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "natural_mode": True,
            "mode": LiveSteerMode.ALLOW,
            "steer_applied": True,
            "activity_end_for_asr": True,
            "awaiting_asr_recovery": True,
            "had_loud_speech": True,
            "turn_peak_mic_rms": 0.09,
        }
    )


def test_ghost_echo_does_not_forward_during_asr_recovery():
    assert not _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "mode": LiveSteerMode.ALLOW,
            "steer_applied": False,
            "activity_end_for_asr": True,
            "awaiting_asr_recovery": True,
            "had_loud_speech": False,
            "turn_peak_mic_rms": 0.03,
        }
    )


def test_recovery_with_transcript_still_forwards():
    assert _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "mode": LiveSteerMode.ALLOW,
            "activity_end_for_asr": True,
            "awaiting_asr_recovery": True,
            "had_loud_speech": False,
            "turn_peak_mic_rms": 0.02,
            "last_user_transcript": "Halo.",
        }
    )


def test_pauses_playback_while_user_is_speaking():
    assert not _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "user_activity_open": True,
            "mode": LiveSteerMode.ALLOW,
        }
    )


def test_websocket_floor_changes_once_per_speaker():
    gov = {"floor": None}
    assert _take_floor(gov, "agent") is True
    assert gov["floor"] == "agent"
    assert _take_floor(gov, "agent") is False
    assert _take_floor(gov, "user") is True
    assert gov["floor"] == "user"
    assert _floor_event("user", reason="turn_complete") == {
        "type": "floor",
        "speaker": "user",
        "reason": "turn_complete",
    }


def test_mark_asr_recovery_keeps_audio_open():
    from persona_ai.web.gemini_live_bridge import _mark_asr_recovery

    gov = {"mode": LiveSteerMode.ALLOW, "play_steered": True, "steer_applied": True}
    _mark_asr_recovery(gov)
    assert gov["mode"] == LiveSteerMode.ALLOW
    assert gov["awaiting_asr_recovery"] is True
    assert gov["play_steered"] is False


def test_mark_asr_recovery_natural_keeps_buffered_reply():
    from persona_ai.web.gemini_live_bridge import _mark_asr_recovery

    gov = {
        "mode": LiveSteerMode.ALLOW,
        "play_steered": True,
        "steer_applied": True,
        "natural_mode": True,
        "ungoverned_audio_buffer": [b"\x00" * 200],
        "ungoverned_audio_buffer_bytes": 200,
    }
    _mark_asr_recovery(gov)
    assert gov["mode"] == LiveSteerMode.ALLOW
    assert gov["awaiting_asr_recovery"] is True
    assert gov["ungoverned_audio_buffer"] == [b"\x00" * 200]


def test_natural_allow_holds_mic_until_turn_complete():
    gov = {
        "ungoverned_audio_buffer": [b"\x00" * 200],
        "ungoverned_audio_buffer_bytes": 200,
        "activity_end_for_asr": True,
        "awaiting_asr_recovery": True,
        "recovery_generation_complete": False,
        "accept_mic": True,
    }
    flushed = _apply_natural_allow(gov)
    assert flushed == [b"\x00" * 200]
    assert gov["accept_mic"] is False
    assert gov["awaiting_turn_complete"] is True
    assert gov["activity_end_for_asr"] is False
    assert gov["mode"] == LiveSteerMode.ALLOW


def test_natural_allow_reopens_mic_if_generation_already_done():
    gov = {
        "ungoverned_audio_buffer": [b"\x00" * 200],
        "ungoverned_audio_buffer_bytes": 200,
        "activity_end_for_asr": True,
        "awaiting_asr_recovery": True,
        "recovery_generation_complete": True,
        "accept_mic": False,
    }
    flushed = _apply_natural_allow(gov)
    assert flushed == [b"\x00" * 200]
    assert gov["accept_mic"] is True
    assert gov["awaiting_turn_complete"] is False
    assert gov["model_generating"] is False


def test_stray_abort_disabled():
    from persona_ai.web.gemini_live_bridge import _should_abort_stray_model

    assert not _should_abort_stray_model({"ready_for_next_utterance": True})
    assert not _should_abort_stray_model({"natural_mode": True, "held_audio": 99})


def test_tiny_pcm_is_not_playable():
    assert not _is_playable_pcm(b"\x00\x01")
    assert _is_playable_pcm(b"\x00" * 160)


def test_open_user_activity_blocked_while_model_generating():
    gov = {
        "accept_mic": True,
        "ready_for_next_utterance": True,
        "greeting_phase": False,
        "user_activity_open": False,
        "gemini_activity_open": False,
        "awaiting_turn_complete": False,
        "model_generating": True,
        "pending": False,
        "commit_scheduled": False,
        "final_task": None,
        "awaiting_steered_turn": False,
    }
    assert not _should_open_user_activity(gov, 0.5)


def test_live_activity_does_not_buffer_mic():
    from persona_ai.web.gemini_live_bridge import _should_buffer_mic

    gov = {
        "gemini_activity_open": True,
        "user_activity_open": True,
        "model_generating": True,
        "awaiting_turn_complete": True,
        "pending": True,
    }
    assert not _should_buffer_mic(gov)


def test_steered_audio_can_play_after_governance():
    assert _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "mode": LiveSteerMode.STEER,
            "steer_applied": True,
            "awaiting_steered_turn": True,
            "play_steered": True,
        }
    )


def test_steered_audio_plays_without_mute_gate():
    assert _should_forward_governed_audio(
        {
            "greeting_phase": False,
            "mode": LiveSteerMode.STEER,
            "steer_applied": True,
            "awaiting_steered_turn": True,
            "play_steered": False,
        }
    )


def test_fallback_governance_disabled_in_persona_first():
    assert not _should_schedule_governance_fallback(
        {
            "greeting_phase": False,
            "pending": False,
            "fallback_final_scheduled": False,
            "ready_for_next_utterance": True,
            "final_task": None,
            "partial_text": "Bantu apa?",
            "last_user_transcript": "",
            "last_transcript_at": 0.0,
        },
        now=1.0,
    )


def test_fallback_governance_waits_for_idle():
    assert not _should_schedule_governance_fallback(
        {
            "greeting_phase": False,
            "pending": False,
            "fallback_final_scheduled": False,
            "ready_for_next_utterance": True,
            "final_task": None,
            "partial_text": "Halo.",
            "last_user_transcript": "Halo.",
            "last_transcript_at": 0.4,
        },
        now=0.5,
    )


def test_fallback_skips_already_governed_transcript():
    assert not _should_schedule_governance_fallback(
        {
            "greeting_phase": False,
            "pending": False,
            "fallback_final_scheduled": False,
            "ready_for_next_utterance": True,
            "final_task": None,
            "partial_text": "Halo.",
            "last_user_transcript": "Halo.",
            "last_transcript_at": 0.0,
            "last_governed_transcript": "Halo.",
        },
        now=2.0,
    )


def test_fallback_governance_waits_for_user_transcript():
    assert not _should_schedule_governance_fallback(
        {
            "greeting_phase": False,
            "pending": False,
            "fallback_final_scheduled": False,
            "ready_for_next_utterance": True,
            "final_task": None,
            "partial_text": "",
            "last_user_transcript": "",
            "last_transcript_at": 0.0,
        },
        now=1.0,
    )


def test_stale_turn_complete_does_not_close_gate_before_steered_audio():
    assert not _should_close_audio_gate(
        {
            "pending": False,
            "final_task": None,
            "awaiting_steered_turn": True,
            "play_steered": False,
            "steered_audio_seen": False,
        }
    )


def test_gate_stays_open_until_steered_audio_arrives():
    assert not _should_close_audio_gate(
        {
            "pending": False,
            "final_task": None,
            "awaiting_steered_turn": True,
            "play_steered": True,
            "steered_audio_seen": False,
        }
    )


def test_fallback_governance_waits_for_loud_mic():
    assert not _should_schedule_governance_fallback(
        {
            "greeting_phase": False,
            "pending": False,
            "fallback_final_scheduled": False,
            "ready_for_next_utterance": True,
            "final_task": None,
            "partial_text": "lagi mikirin",
            "last_user_transcript": "lagi mikirin",
            "last_transcript_at": 0.0,
            "last_loud_mic_at": 0.9,
        },
        now=1.0,
    )


def test_gate_stays_open_while_audio_is_still_flowing():
    assert not _should_close_audio_gate(
        {
            "pending": False,
            "final_task": None,
            "awaiting_steered_turn": True,
            "play_steered": True,
            "steered_audio_seen": True,
            "steer_applied": True,
            "last_forward_at": 1.0,
        },
        now=1.2,
    )


def test_gate_closes_after_steered_audio_completes():
    assert _should_close_audio_gate(
        {
            "pending": False,
            "final_task": None,
            "awaiting_steered_turn": True,
            "play_steered": True,
            "steered_audio_seen": True,
            "steer_applied": True,
            "last_forward_at": 0.0,
        },
        now=1.0,
    )


def test_overlapping_same_utterance_is_blocked_while_answer_plays():
    from persona_ai.web.gemini_live_bridge import _should_start_final_governance

    gov = {
        "pending": False,
        "final_task": None,
        "awaiting_steered_turn": True,
        "ready_for_next_utterance": False,
    }
    assert not _should_start_final_governance(gov, "Halo. Halo.", {"s1": "Halo. Halo."}, "s1")


def test_new_utterance_waits_while_answer_plays():
    from persona_ai.web.gemini_live_bridge import _should_start_final_governance

    gov = {
        "pending": False,
        "final_task": None,
        "awaiting_steered_turn": True,
        "ready_for_next_utterance": False,
    }
    assert not _should_start_final_governance(gov, "Tunggu dulu.", {"s1": "Halo."}, "s1")


def test_new_utterance_can_start_after_answer_completes():
    from persona_ai.web.gemini_live_bridge import _should_start_final_governance

    gov = {
        "pending": False,
        "final_task": None,
        "awaiting_steered_turn": False,
        "ready_for_next_utterance": True,
    }
    assert _should_start_final_governance(gov, "Halo.", {}, "s1")


def test_apply_barge_in_reopens_next_utterance():
    from persona_ai.web.gemini_live_bridge import _apply_barge_in, _answer_in_flight

    class _Open:
        def __init__(self) -> None:
            self.cancelled = False

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self.cancelled = True

    task = _Open()
    gov = {
        "pending": True,
        "mode": LiveSteerMode.STEER,
        "steer_applied": True,
        "awaiting_steered_turn": True,
        "steered_audio_seen": True,
        "play_steered": True,
        "ungoverned_complete": True,
        "fallback_final_scheduled": True,
        "ready_for_next_utterance": False,
        "partial_text": "halo",
        "queued_transcript": "queued",
        "last_forward_at": 12.0,
        "final_task": task,
        "partial_task": None,
        "greeting_phase": True,
        "model_generating": True,
        "accept_mic": False,
        "user_activity_open": False,
        "gemini_activity_open": False,
    }
    _apply_barge_in(gov)
    assert task.cancelled is True
    assert gov["ready_for_next_utterance"] is True
    assert gov["pending"] is False
    assert gov["queued_transcript"] == ""
    assert gov["ignore_model_audio"] is True
    assert gov["greeting_phase"] is False
    assert gov["last_forward_at"] == 0.0
    assert not _answer_in_flight(gov)
    assert _should_open_user_activity(gov, 0.05)
    assert not _should_forward_governed_audio(gov)


def test_drop_queued_audio_keeps_control_messages():
    import asyncio

    from persona_ai.web.gemini_live_bridge import _drop_queued_audio

    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait({"type": "audio", "data": "a"})
    queue.put_nowait({"type": "transcript", "text": "hi"})
    queue.put_nowait({"type": "audio", "data": "b"})
    queue.put_nowait(None)
    assert _drop_queued_audio(queue) == 2
    assert queue.get_nowait() == {"type": "transcript", "text": "hi"}
    assert queue.get_nowait() is None
    assert queue.empty()


def test_zero_interruption_disables_gemini_barge_in():
    from google.genai import types

    from persona_ai.web.gemini_live_bridge import _activity_handling
    from persona_ai.web.voice_config import LiveVoiceConfig

    assert (
        _activity_handling(LiveVoiceConfig(interruption_sensitivity=0.0))
        == types.ActivityHandling.NO_INTERRUPTION
    )


def test_gemini_barge_in_interrupts_agent_reply():
    from google.genai import types

    from persona_ai.web.gemini_live_bridge import _activity_handling, _live_connect_config
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig()
    assert _activity_handling(voice) == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
    assert (
        _activity_handling(LiveVoiceConfig(interruption_sensitivity=1.0))
        == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
    )
    config = _live_connect_config("hi", voice)
    assert (
        config.realtime_input_config.activity_handling
        == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
    )
    vad = config.realtime_input_config.automatic_activity_detection
    assert vad.disabled is True
    assert (
        config.realtime_input_config.turn_coverage
        == types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY
    )
    assert config.session_resumption is not None
    assert config.session_resumption.handle is None
    assert config.session_resumption.transparent is None
    assert config.context_window_compression is not None
    assert config.context_window_compression.sliding_window is not None
    resumed = _live_connect_config("hi", voice, resumption_handle="tok_abc")
    assert resumed.session_resumption.handle == "tok_abc"


def test_gemini_goaway_error_matches_truncated_1008():
    from persona_ai.web.gemini_live_bridge import (
        GEMINI_SESSION_EXPIRED_MSG,
        _browser_gemini_error,
        _is_gemini_goaway_error,
        _live_session_idle,
        _store_resumption_handle,
    )

    msg = (
        "1008 None. Connection aborted because the client failed to close "
        "the connection after receiving a GoAway signal once the session durat"
    )
    assert _is_gemini_goaway_error(msg)
    assert _is_gemini_goaway_error(Exception(msg))
    assert _browser_gemini_error(msg) == GEMINI_SESSION_EXPIRED_MSG
    assert _is_gemini_goaway_error("1000 None.")
    assert _browser_gemini_error("1000 None.") == GEMINI_SESSION_EXPIRED_MSG

    gov = {"resumption_handle": "old"}
    _store_resumption_handle(gov, type("U", (), {"new_handle": "new", "resumable": True})())
    assert gov["resumption_handle"] == "new"
    _store_resumption_handle(gov, type("U", (), {"new_handle": "", "resumable": False})())
    assert gov["resumption_handle"] == "new"
    assert _live_session_idle(
        {
            "user_activity_open": False,
            "gemini_activity_open": False,
            "model_generating": False,
            "pending": False,
            "awaiting_steered_turn": False,
            "awaiting_turn_complete": False,
            "final_task": None,
        }
    )
    assert not _live_session_idle({"user_activity_open": True})


def test_persona_opens_activity_on_loud_mic_when_ready():
    from persona_ai.web.gemini_live_bridge import _should_open_user_activity
    from persona_ai.web.persona_live import LiveSteerMode

    gov = {
        "greeting_phase": False,
        "user_activity_open": False,
        "gemini_activity_open": False,
        "accept_mic": True,
        "ready_for_next_utterance": True,
        "pending": False,
        "commit_scheduled": False,
        "awaiting_steered_turn": False,
        "awaiting_turn_complete": False,
        "final_task": None,
        "mode": LiveSteerMode.ALLOW,
    }
    assert _should_open_user_activity(gov, 0.05)
    assert not _should_open_user_activity(gov, 0.001)
    assert not _should_open_user_activity(gov, 0.03)
    gov["greeting_phase"] = True
    assert not _should_open_user_activity(gov, 0.05)
    gov["greeting_phase"] = False
    gov["awaiting_turn_complete"] = True
    assert not _should_open_user_activity(gov, 0.05)


def test_echo_after_agent_does_not_open_activity():
    from persona_ai.web.gemini_live_bridge import _should_open_user_activity

    gov = {
        "greeting_phase": False,
        "user_activity_open": False,
        "gemini_activity_open": False,
        "accept_mic": True,
        "ready_for_next_utterance": True,
        "pending": False,
        "commit_scheduled": False,
        "awaiting_steered_turn": False,
        "awaiting_turn_complete": False,
        "final_task": None,
        "last_forward_at": 10.0,
    }
    assert not _should_open_user_activity(gov, 0.035, now=10.4)
    assert not _should_open_user_activity(gov, 0.05, now=10.4)
    assert _should_open_user_activity(gov, 0.08, now=10.4)
    assert _should_open_user_activity(gov, 0.05, now=11.2)


def test_persona_commits_after_configured_silence():
    from persona_ai.web.gemini_live_bridge import _should_commit_user_activity
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        partial_text="Halo apa kabar",
        last_user_transcript="Halo apa kabar",
        partial_stable_text="Halo apa kabar",
        partial_stable_since=0.0,
        first_partial_at=0.1,
    )
    assert not _should_commit_user_activity(gov, voice, now=0.3)
    assert not _should_commit_user_activity(gov, voice, now=0.55)
    assert not _should_commit_user_activity(gov, voice, now=1.15)
    assert not _should_commit_user_activity(gov, voice, now=1.55)
    assert _should_commit_user_activity(gov, voice, now=2.05)


def test_unstable_partial_waits_for_final_or_timeout():
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        partial_text="M itu apa?",
        last_user_transcript="M itu apa?",
        partial_stable_text="M itu",
        partial_stable_since=0.95,
        first_partial_at=0.8,
    )
    assert _transcript_commit_reason(gov, voice, now=1.0) is None
    gov["partial_stable_text"] = "M itu apa?"
    gov["partial_stable_since"] = 0.95
    assert _transcript_commit_reason(gov, voice, now=1.2) is None
    assert _transcript_commit_reason(gov, voice, now=1.55) == "partial_stable"


def test_hanging_partial_waits_for_rest_of_clause():
    from persona_ai.web.gemini_live_bridge import HANGING_ASR_WAIT_S, _asr_looks_unfinished
    from persona_ai.web.voice_config import LiveVoiceConfig

    assert _asr_looks_unfinished("Saya ngobrol sama")
    assert _asr_looks_unfinished("Kenapa kamu")
    assert not _asr_looks_unfinished("Kita ngobrol soal kamu saja.")
    assert not _asr_looks_unfinished("Apa kabar?")

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        partial_text="Saya ngobrol sama",
        last_user_transcript="Saya ngobrol sama",
        partial_stable_text="Saya ngobrol sama",
        partial_stable_since=0.0,
        first_partial_at=0.1,
    )
    assert _transcript_commit_reason(gov, voice, now=0.55) is None
    assert (
        _transcript_commit_reason(gov, voice, now=0.1 + HANGING_ASR_WAIT_S + 0.05)
        == "incomplete_utterance"
    )


def test_asr_recovery_does_not_commit_first_partial():
    from persona_ai.web.gemini_live_bridge import FINAL_TRANSCRIPT_TIMEOUT_S
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        user_activity_open=False,
        gemini_activity_open=False,
        last_loud_mic_at=2.0,
        activity_started_at=0.0,
        activity_end_for_asr=True,
        activity_end_for_asr_at=3.0,
        awaiting_asr_recovery=True,
        partial_text="Kita ngobrol soal kamu saja.",
        last_user_transcript="Kita ngobrol soal kamu saja.",
        partial_stable_text="Kita ngobrol soal kamu saja.",
        partial_stable_since=3.0,
        first_partial_at=3.0,
    )
    assert _transcript_commit_reason(gov, voice, now=3.2) is None
    assert _transcript_commit_reason(gov, voice, now=3.0 + FINAL_TRANSCRIPT_TIMEOUT_S + 0.05) is None
    assert _transcript_commit_reason(gov, voice, now=3.8) == "incomplete_utterance"


def test_no_transcript_waits_for_asr():
    from persona_ai.web.gemini_live_bridge import (
        MIN_ACTIVITY_BEFORE_FLUSH_S,
        STT_GRACE_AFTER_SILENCE_S,
        _commit_silence_s,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov()
    silence_s = _commit_silence_s(voice)
    flush_at = max(
        0.2 + silence_s + STT_GRACE_AFTER_SILENCE_S,
        MIN_ACTIVITY_BEFORE_FLUSH_S,
    ) + 0.05
    assert _transcript_commit_reason(gov, voice, now=flush_at - 0.1) is None
    assert _transcript_commit_reason(gov, voice, now=flush_at) == "end_activity_for_asr"


def test_end_activity_for_asr_after_speech_silence():
    from persona_ai.web.gemini_live_bridge import (
        MIN_ACTIVITY_BEFORE_FLUSH_S,
        STT_GRACE_AFTER_SILENCE_S,
        _commit_silence_s,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov()
    silence_s = _commit_silence_s(voice)
    flush_at = max(
        0.2 + silence_s + STT_GRACE_AFTER_SILENCE_S,
        MIN_ACTIVITY_BEFORE_FLUSH_S,
    ) + 0.05
    assert _transcript_commit_reason(gov, voice, now=flush_at - 0.1) is None
    assert (
        _transcript_commit_reason(gov, voice, now=flush_at)
        == "end_activity_for_asr"
    )


def test_no_transcript_abandons_after_asr_wait_timeout():
    from persona_ai.web.gemini_live_bridge import (
        MAX_ASR_WAIT_AFTER_END_S,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        user_activity_open=False,
        gemini_activity_open=False,
        activity_end_for_asr=True,
        activity_end_for_asr_at=1.0,
    )
    assert _transcript_commit_reason(gov, voice, now=1.0 + MAX_ASR_WAIT_AFTER_END_S - 0.5) is None
    assert (
        _transcript_commit_reason(
            gov, voice, now=1.0 + MAX_ASR_WAIT_AFTER_END_S + 0.1
        )
        == "abandon_no_transcript"
    )


def test_abandon_skipped_when_gemini_already_replied():
    from persona_ai.web.gemini_live_bridge import (
        MAX_ASR_WAIT_AFTER_END_S,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        user_activity_open=False,
        gemini_activity_open=False,
        activity_end_for_asr=True,
        activity_end_for_asr_at=1.0,
        recovery_generation_complete=True,
    )
    assert (
        _transcript_commit_reason(
            gov, voice, now=1.0 + MAX_ASR_WAIT_AFTER_END_S + 0.1
        )
        is None
    )


def test_abandon_does_not_repeat_after_vad_reset():
    from persona_ai.web.gemini_live_bridge import (
        MAX_ASR_WAIT_AFTER_END_S,
        _reset_vad_turn,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        user_activity_open=False,
        gemini_activity_open=False,
        activity_end_for_asr=True,
        activity_end_for_asr_at=1.0,
    )
    abandon_at = 1.0 + MAX_ASR_WAIT_AFTER_END_S + 0.1
    assert _transcript_commit_reason(gov, voice, now=abandon_at) == "abandon_no_transcript"
    _reset_vad_turn(gov)
    assert _transcript_commit_reason(gov, voice, now=abandon_at + 30) is None


def test_noise_only_turn_abandons_after_timeout():
    from persona_ai.web.gemini_live_bridge import (
        MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        had_loud_speech=False,
        activity_started_at=0.0,
        last_loud_mic_at=0.0,
    )
    assert _transcript_commit_reason(gov, voice, now=MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S - 0.5) is None
    assert (
        _transcript_commit_reason(gov, voice, now=MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S + 0.5)
        == "abandon_no_transcript"
    )


def test_noise_only_abandon_not_repeated_when_activity_closed():
    from persona_ai.web.gemini_live_bridge import (
        MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        user_activity_open=False,
        gemini_activity_open=False,
        had_loud_speech=False,
        activity_started_at=0.0,
        last_loud_mic_at=0.0,
        vad_turn_active=True,
    )
    assert (
        _transcript_commit_reason(gov, voice, now=MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S + 5.0) is None
    )


def test_waits_for_asr_after_activity_end():
    from persona_ai.web.gemini_live_bridge import (
        MAX_ASR_WAIT_AFTER_END_S,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        user_activity_open=False,
        gemini_activity_open=False,
        last_loud_mic_at=2.0,
        activity_end_for_asr=True,
        activity_end_for_asr_at=3.0,
    )
    assert _transcript_commit_reason(gov, voice, now=3.0 + MAX_ASR_WAIT_AFTER_END_S - 1) is None


def test_slow_asr_waits_after_real_speech():
    from persona_ai.web.gemini_live_bridge import (
        MIN_ACTIVITY_BEFORE_FLUSH_S,
        STT_GRACE_AFTER_SILENCE_S,
        _commit_silence_s,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        last_loud_mic_at=2.0,
    )
    silence_s = _commit_silence_s(voice)
    flush_at = max(
        2.0 + silence_s + STT_GRACE_AFTER_SILENCE_S,
        MIN_ACTIVITY_BEFORE_FLUSH_S,
    ) + 0.05
    assert _transcript_commit_reason(gov, voice, now=flush_at - 0.1) is None
    assert _transcript_commit_reason(gov, voice, now=flush_at) == "end_activity_for_asr"


def test_ungoverned_audio_never_uses_mute_buffer():
    from persona_ai.web.gemini_live_bridge import _should_buffer_ungoverned_audio

    assert not _should_buffer_ungoverned_audio({"mode": "allow"})
    assert not _should_buffer_ungoverned_audio(
        {
            "natural_mode": True,
            "awaiting_steered_turn": True,
            "play_steered": True,
            "steered_audio_seen": False,
        }
    )


def test_incomplete_utterance_after_final_timeout():
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        partial_text="This kamu",
        last_user_transcript="This kamu",
        partial_stable_text="This kamu dikembangkan",
        partial_stable_since=1.15,
        first_partial_at=0.1,
    )
    assert _transcript_commit_reason(gov, voice, now=1.2) is None
    assert _transcript_commit_reason(gov, voice, now=2.2) == "incomplete_utterance"


def test_mid_clause_does_not_commit_on_short_pause():
    from persona_ai.web.gemini_live_bridge import HANGING_ENDPOINT_SILENCE_S
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        last_loud_mic_at=0.2,
        activity_started_at=0.0,
        partial_text="Kenapa kamu",
        last_user_transcript="Kenapa kamu",
        partial_stable_text="Kenapa kamu",
        partial_stable_since=0.3,
        first_partial_at=0.25,
    )
    assert _transcript_commit_reason(gov, voice, now=0.2 + 0.92) is None
    assert _transcript_commit_reason(gov, voice, now=0.2 + HANGING_ENDPOINT_SILENCE_S - 0.05) is None


def test_brief_utterance_waits_out_a_breath():
    from persona_ai.web.gemini_live_bridge import (
        SHORT_UTTERANCE_SILENCE_S,
        _asr_looks_brief,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    assert _asr_looks_brief("Bro.")
    assert _asr_looks_brief("Halo")
    assert not _asr_looks_brief("Halo apa kabar")

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        partial_text="Bro.",
        last_user_transcript="Bro.",
        partial_stable_text="Bro.",
        partial_stable_since=0.0,
        first_partial_at=0.1,
    )
    assert _transcript_commit_reason(gov, voice, now=0.2 + 1.15) is None
    assert (
        _transcript_commit_reason(gov, voice, now=0.2 + SHORT_UTTERANCE_SILENCE_S + 0.05)
        == "partial_stable"
    )


def test_ungoverned_audio_buffers_until_gate_opens():
    gov: dict = {"held_audio": 0}
    assert _append_ungoverned_audio(gov, b"\x00" * 1000)
    assert len(gov["ungoverned_audio_buffer"]) == 1
    assert gov["ungoverned_audio_buffer_bytes"] == 1000
    assert gov["held_audio"] == 1
    flushed = _flush_ungoverned_audio_buffer(gov)
    assert len(flushed) == 1
    assert gov["ungoverned_audio_buffer_bytes"] == 0


def test_ungoverned_audio_drop_on_overflow():
    gov: dict = {"held_audio": 0}
    chunk = b"\x00" * (MAX_UNGOVERNED_BUFFER_BYTES // 2 + 1)
    assert _append_ungoverned_audio(gov, chunk)
    assert not _append_ungoverned_audio(gov, chunk)
    assert gov["ungoverned_audio_drops"] == 1
    assert gov["ungoverned_audio_buffer_bytes"] == 0


def test_barge_in_clears_ungoverned_buffer():
    from persona_ai.web.gemini_live_bridge import _apply_barge_in

    class _Done:
        def done(self) -> bool:
            return True

        def cancel(self) -> None:
            pass

    gov = {
        "partial_task": None,
        "final_task": _Done(),
        "ungoverned_audio_buffer": [b"\x00" * 100],
        "ungoverned_audio_buffer_bytes": 100,
    }
    _apply_barge_in(gov)
    assert gov["ungoverned_audio_buffer_bytes"] == 0
    assert gov["ungoverned_audio_buffer"] == []


def test_partial_stability_tracks_text_changes():
    gov: dict = {}
    _update_partial_stability(gov, "Halo", now=1.0)
    assert gov["partial_stable_text"] == "Halo"
    assert gov["first_partial_at"] == 1.0
    assert not _partial_is_stable(gov, now=1.1)
    assert not _partial_is_stable(gov, now=1.4)
    assert _partial_is_stable(gov, now=1.55)
    _update_partial_stability(gov, "Halo apa", now=1.6)
    assert not _partial_is_stable(gov, now=1.9)
    assert _partial_is_stable(gov, now=2.15)


def test_asr_finished_commits_without_waiting_silence_floor():
    from persona_ai.web.gemini_live_bridge import _should_commit_user_activity
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        asr_finished=True,
        first_partial_at=0.1,
        last_transcript_at=0.15,
        partial_text="Jam berapa sekarang?",
        last_user_transcript="Jam berapa sekarang?",
    )
    assert _should_commit_user_activity(gov, voice, now=0.25)


def test_commit_uses_longest_growing_transcript():
    from persona_ai.web.gemini_live_bridge import _latest_governance_transcript

    gov = {
        "partial_text": ", pesan tiket, cari hotel.",
        "last_user_transcript": (
            "Kalau saya sih lebih pengen AI itu bisa order Grab, Gojek, pesan tiket, cari hotel."
        ),
    }
    assert "order Grab" in _latest_governance_transcript(gov)


def test_live_uses_live_voice_policy():
    from persona_ai.web.persona_live import LIVE_RESPONSE_POLICY

    assert LIVE_RESPONSE_POLICY == "live_voice"


def test_final_governance_blocked_while_awaiting_turn_complete():
    from persona_ai.web.gemini_live_bridge import _should_start_final_governance

    gov = {
        "ready_for_next_utterance": True,
        "awaiting_turn_complete": True,
        "final_scheduled_for": "",
        "final_task": None,
    }
    assert not _should_start_final_governance(gov, "Halo", {}, "s1")


def test_final_governance_not_scheduled_twice_for_same_transcript():
    from persona_ai.web.gemini_live_bridge import _should_start_final_governance

    gov = {
        "ready_for_next_utterance": True,
        "final_scheduled_for": "apa kabar",
        "final_task": None,
    }
    assert not _should_start_final_governance(gov, "apa kabar", {}, "s1")


def test_late_asr_only_after_flush_or_abandon():
    from persona_ai.web.gemini_live_bridge import _should_schedule_late_asr

    assert not _should_schedule_late_asr({"ready_for_next_utterance": True})
    assert _should_schedule_late_asr({"activity_end_for_asr": True})
    assert _should_schedule_late_asr({"awaiting_asr_recovery": True})


def test_build_latency_metrics_slices():
    from persona_ai.web.gemini_live_bridge import (
        _build_latency_metrics,
        _latency_mark,
    )

    gov: dict = {"_latency_turn_id": 1}
    _latency_mark(gov, "connect_start", now=0.0)
    _latency_mark(gov, "session_active", now=0.45)
    _latency_mark(gov, "speech_end", now=1.0)
    _latency_mark(gov, "user_commit", now=1.85)
    _latency_mark(gov, "governance_start", now=1.86)
    _latency_mark(gov, "governance_done", now=2.01)
    _latency_mark(gov, "first_audio", now=2.55)
    metrics = _build_latency_metrics(
        gov, turn_id=1, phase="turn_response", extra={"commit_reason": "partial_stable"}
    )
    assert metrics["connect_ms"] == 450
    assert metrics["vad_wait_ms"] == 850
    assert metrics["governance_ms"] == 150
    assert metrics["steer_to_audio_ms"] == 540
    assert metrics["commit_to_audio_ms"] == 700
    assert metrics["commit_reason"] == "partial_stable"


def test_voice_filler_is_not_a_new_topic():
    assert _is_voice_filler("Mmm.")
    assert _is_voice_filler("hmm")
    assert not _is_voice_filler("M itu apa?")
    assert not _is_voice_filler("ada mobil Honda")


def test_note_mic_rms_ignores_borderline_noise_after_speech():
    from persona_ai.web.gemini_live_bridge import SILENCE_RESET_RMS, _note_mic_rms

    gov = {
        "user_activity_open": True,
        "gemini_activity_open": True,
        "had_loud_speech": True,
        "last_loud_mic_at": 5.0,
    }
    _note_mic_rms(gov, SILENCE_RESET_RMS - 0.001, now=8.0)
    assert gov["last_loud_mic_at"] == 5.0
    _note_mic_rms(gov, SILENCE_RESET_RMS + 0.01, now=8.1)
    assert gov["last_loud_mic_at"] == 8.1


def test_had_loud_speech_triggers_asr_flush_not_immediate_abandon():
    from persona_ai.web.gemini_live_bridge import (
        MIN_ACTIVITY_BEFORE_FLUSH_S,
        STT_GRACE_AFTER_SILENCE_S,
        _commit_silence_s,
        _transcript_commit_reason,
    )
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        last_loud_mic_at=0.05,
    )
    silence_s = _commit_silence_s(voice)
    flush_at = max(
        0.05 + silence_s + STT_GRACE_AFTER_SILENCE_S,
        MIN_ACTIVITY_BEFORE_FLUSH_S,
    ) + 0.05
    assert _transcript_commit_reason(gov, voice, now=flush_at) == "end_activity_for_asr"


def test_stale_partial_does_not_commit_on_new_activity():
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        activity_started_at=10.0,
        last_loud_mic_at=10.5,
        partial_text="Lanjut.",
        last_user_transcript="Lanjut.",
        partial_stable_text="Lanjut.",
        partial_stable_since=9.0,
        first_partial_at=0.0,
    )
    assert _transcript_commit_reason(gov, voice, now=12.5) == "end_activity_for_asr"


def test_stale_asr_ignored_when_no_activity_open():
    from persona_ai.web.gemini_live_bridge import _should_accept_input_transcription

    assert _should_accept_input_transcription(
        {"user_activity_open": True, "gemini_activity_open": True}
    )
    assert _should_accept_input_transcription({"activity_end_for_asr": True})
    assert not _should_accept_input_transcription(
        {
            "user_activity_open": False,
            "gemini_activity_open": False,
            "activity_end_for_asr": False,
            "awaiting_asr_recovery": False,
        }
    )


def test_asr_recovery_locks_first_partial():
    from persona_ai.web.gemini_live_bridge import _lock_asr_recovery_partial

    gov = {"activity_end_for_asr": True, "asr_recovery_partial": ""}
    assert _lock_asr_recovery_partial(gov, "Lanjut yang tadi.") == "Lanjut yang tadi."
    assert _lock_asr_recovery_partial(gov, "Saya tidak tahu.") == "Lanjut yang tadi."


def test_phantom_asr_dropped_when_mic_weak():
    from persona_ai.web.gemini_live_bridge import _should_drop_phantom_asr

    gov = {"had_loud_speech": False, "turn_peak_mic_rms": 0.01}
    assert _should_drop_phantom_asr(gov, "Saya tidak tahu.")
    assert not _should_drop_phantom_asr(gov, "Lanjut yang tadi.")


def test_phantom_asr_kept_when_mic_strong():
    from persona_ai.web.gemini_live_bridge import _should_drop_phantom_asr

    gov = {"had_loud_speech": True, "turn_peak_mic_rms": 0.08}
    assert not _should_drop_phantom_asr(gov, "Saya tidak tahu.")


def test_activity_start_skipped_when_already_open():
    from persona_ai.web.gemini_live_bridge import _should_open_user_activity

    gov = {
        "activity_end_for_asr": False,
        "awaiting_asr_recovery": False,
        "greeting_phase": False,
        "user_activity_open": False,
        "gemini_activity_open": True,
        "accept_mic": True,
        "awaiting_turn_complete": False,
        "ready_for_next_utterance": True,
        "commit_scheduled": False,
    }
    assert not _should_open_user_activity(gov, 0.05)


def test_mic_buffered_during_asr_recovery():
    import struct

    from persona_ai.web.gemini_live_bridge import (
        _append_recovery_mic,
        _pcm_rms,
        _schedule_recovery_mic_release,
        _should_buffer_mic,
        _should_open_user_activity,
        _take_recovery_mic,
    )

    gov = {"activity_end_for_asr": True, "gemini_activity_open": False}
    assert _should_buffer_mic(gov)
    assert not _should_open_user_activity(
        {
            **gov,
            "awaiting_asr_recovery": False,
            "greeting_phase": False,
            "user_activity_open": False,
            "accept_mic": True,
            "awaiting_turn_complete": False,
            "ready_for_next_utterance": True,
            "commit_scheduled": False,
        },
        0.05,
    )
    silent = b"\x00" * 3200
    loud = struct.pack("<1600h", *([8000] * 1600))
    assert _pcm_rms(loud) >= 0.02
    for _ in range(25):
        _append_recovery_mic(gov, silent)
    _append_recovery_mic(gov, loud)
    chunks = _take_recovery_mic(gov)
    assert len(chunks) <= 20
    assert chunks[-1] == loud

    gov["recovery_mic_buffer"] = [(b"a", 0.001), (b"b", 0.05)]
    _schedule_recovery_mic_release(gov, "test")
    assert gov.get("recovery_mic_pending") == [b"b"]
    assert not gov.get("recovery_mic_buffer")


def test_promote_recovery_for_flush_drops_silence():
    from persona_ai.web.gemini_live_bridge import _promote_recovery_for_flush

    gov = {
        "recovery_mic_buffer": [(b"\x00" * 3200, 0.001)],
        "live_voice_thresholds": {"loud_mic_rms": 0.02},
    }
    assert _promote_recovery_for_flush(gov) == 0
    assert not gov.get("recovery_mic_pending")


def test_promote_recovery_for_flush_keeps_loud_speech():
    import struct

    from persona_ai.web.gemini_live_bridge import _pcm_rms, _promote_recovery_for_flush

    loud = struct.pack("<1600h", *([8000] * 1600))
    gov = {
        "recovery_mic_buffer": [(loud, _pcm_rms(loud))],
        "live_voice_thresholds": {"loud_mic_rms": 0.02},
    }
    assert _promote_recovery_for_flush(gov) == 1
    assert gov.get("recovery_mic_pending") == [loud]


def test_commit_blocked_while_recovery_speech_pending():
    from persona_ai.web.gemini_live_bridge import _recovery_speech_pending, _transcript_commit_reason
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(last_loud_mic_at=10.5, activity_started_at=10.0)
    gov["recovery_mic_pending"] = [b"x" * 3200]
    assert _recovery_speech_pending(gov)
    assert _transcript_commit_reason(gov, voice, now=12.0) is None


def test_leftover_recovery_buffer_does_not_block_live_commit():
    from persona_ai.web.gemini_live_bridge import _transcript_commit_reason
    from persona_ai.web.voice_config import LiveVoiceConfig

    voice = LiveVoiceConfig(responsiveness=1.0)
    gov = _commit_gov(
        last_loud_mic_at=10.5,
        activity_started_at=10.0,
        recovery_mic_buffer=[(b"x" * 3200, 0.08)],
    )
    assert _transcript_commit_reason(gov, voice, now=12.4) is not None


def test_recovery_mic_drip_respects_queue_headroom():
    import asyncio

    from persona_ai.web.gemini_live_bridge import (
        MAX_AUDIO_QUEUE_CHUNKS,
        RECOVERY_QUEUE_HEADROOM,
        _drip_recovery_mic,
    )

    gov = {
        "recovery_mic_pending": [b"x" * 3200],
        "recovery_release_next_at": 0.0,
    }
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MAX_AUDIO_QUEUE_CHUNKS)
    for _ in range(MAX_AUDIO_QUEUE_CHUNKS - RECOVERY_QUEUE_HEADROOM + 1):
        q.put_nowait(b"y" * 3200)
    assert not _drip_recovery_mic(gov, q)
    assert gov["recovery_mic_pending"]


def test_opening_rms_sets_had_loud_speech():
    from persona_ai.web.gemini_live_bridge import LOUD_MIC_RMS

    gov = _commit_gov(had_loud_speech=False)
    assert LOUD_MIC_RMS + 0.01 >= LOUD_MIC_RMS
    # opening_rms at threshold should count as speech when activity opens
    gov["had_loud_speech"] = LOUD_MIC_RMS + 0.01 >= LOUD_MIC_RMS
    assert gov["had_loud_speech"]


def test_build_engine_directive_for_transcript_includes_user_line():
    from persona_ai.web.voice_instruction import build_engine_directive_for_transcript

    text = build_engine_directive_for_transcript("Halo. Halo.", "Answer warmly.")
    assert 'The user said: "Halo. Halo."' in text
    assert "Answer warmly." in text
    assert "you heard their audio" not in text
