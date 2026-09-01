"""Tests for Retell voice webhook POC."""

from persona_ai.core.types import SpeakAction
from persona_ai.integrations.retell_webhook import (
    RetellPersonaBridge,
    RetellResponseType,
    RetellWebhookRequest,
    turn_output_to_retell,
)
from persona_ai.runtime import PersonaRuntime, TurnOutput


class TestTurnOutputToRetell:
    def test_silence_no_response(self):
        from persona_ai.behavior.engine import decide
        from persona_ai.core.types import BehaviorInput, Message, ResponseLength, TurnHistory

        inp = BehaviorInput(
            message=Message.from_text("user", "Oke"),
            history=TurnHistory(last_assistant_word_count=200, last_assistant_verbosity=ResponseLength.EXPAND),
        )
        bdv = decide(inp)
        out = TurnOutput(voice=object(), text=None, llm_called=False, cps_score=0.0, cps_hits=[], bdv=bdv)
        resp = turn_output_to_retell(out)
        assert resp.response_type == RetellResponseType.NO_RESPONSE
        assert resp.text is None
        assert resp.bdv_action == SpeakAction.SILENCE.value

    def test_ack_speak(self):
        from persona_ai.behavior.engine import decide
        from persona_ai.core.types import BehaviorInput, Message

        bdv = decide(BehaviorInput(message=Message.from_text("user", "Ah capek banget...")))
        out = TurnOutput(
            voice=object(),
            text="Berat ya.",
            llm_called=False,
            cps_score=0.0,
            cps_hits=[],
            bdv=bdv,
        )
        resp = turn_output_to_retell(out)
        assert resp.response_type == RetellResponseType.SPEAK
        assert resp.text == "Berat ya."
        assert resp.bdv_action == SpeakAction.ACK_ONLY.value


class TestRetellPersonaBridge:
    def test_closure_via_bridge(self):
        bridge = RetellPersonaBridge(preset_id="default_companion")
        sid = "retell-closure-test"
        runtime = bridge.runtime
        from persona_ai.core.types import Message, ResponseLength, TurnHistory
        from persona_ai.session.models import SessionState

        seed = " ".join(["detail"] * 120)
        session = SessionState.new(sid, profile_warmth=runtime.personality_profile.warmth)
        session.messages.append(Message.from_text("assistant", seed))
        session.turn_history = TurnHistory(
            last_speaker="assistant",
            last_assistant_word_count=len(seed.split()),
            last_assistant_verbosity=ResponseLength.EXPAND,
            consecutive_assistant_turns=1,
        )
        runtime.session_store.save(session)

        resp = bridge.handle_turn(RetellWebhookRequest(session_id=sid, transcript="Oke"))
        assert resp.response_type == RetellResponseType.NO_RESPONSE
        assert resp.bdv_action == SpeakAction.SILENCE.value

    def test_defer_on_pause(self):
        bridge = RetellPersonaBridge(preset_id="default_companion")
        resp = bridge.handle_turn(
            RetellWebhookRequest(
                session_id="retell-defer-test",
                transcript="Jadi rencananya...",
                voice_pause_ms=1200,
            )
        )
        assert resp.response_type == RetellResponseType.NO_RESPONSE
        assert resp.bdv_action == SpeakAction.DEFER.value
        assert resp.delay_ms >= 1500

    def test_handle_dict_payload(self):
        bridge = RetellPersonaBridge(preset_id="default_companion")
        payload = bridge.handle_dict(
            {
                "call_id": "call_abc",
                "transcript": "Besok meeting jam berapa?",
            }
        )
        assert payload["response_type"] == RetellResponseType.SPEAK.value
        assert payload["bdv_action"] == SpeakAction.RESPOND.value
        assert payload["llm_called"] is True
