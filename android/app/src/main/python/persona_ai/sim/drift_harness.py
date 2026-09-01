"""Multi-turn drift test harness — long-session behavioral stress."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev

from persona_ai.arc import store as arc_store
from persona_ai.coherence.bind import IdentityAnchor
from persona_ai.conversation.pipeline_v0 import process_turn
from persona_ai.core.types import (
    ArcPhase,
    ConversationArc,
    Message,
    PersonalityProfile,
    ResponseLength,
    SpeakAction,
    TurnHistory,
    clamp,
)
from persona_ai.llm.adapter import LLMAdapter, default_adapter
from persona_ai.diagnostics.turn_context import TurnCausalContext, build_turn_context
from persona_ai.behavior.interpret import interpret


@dataclass
class TurnRecord:
    index: int
    user_text: str
    speak: SpeakAction
    effective_warmth: float
    tone_shift: str
    anchor_baseline: float
    arc_warmth: float
    text: str | None
    llm_called: bool
    cps_score: float
    cps_hits: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    context: TurnCausalContext | None = None


@dataclass
class DriftMetrics:
    turn_count: int
    warmth_values: list[float]
    anchor_values: list[float]
    max_warmth_step: float
    warmth_range: float
    anchor_range: float
    warmth_std: float
    speak_counts: dict[str, int]
    max_same_speak_streak: int
    silence_ratio: float
    mechanical_score: float
    identity_stable: bool
    grade: str
    notes: list[str] = field(default_factory=list)


@dataclass
class SessionReport:
    script_name: str
    turns: list[TurnRecord]
    metrics: DriftMetrics


def _verbosity_from_words(count: int) -> ResponseLength:
    if count >= 40:
        return ResponseLength.EXPAND
    if count <= 8:
        return ResponseLength.MINIMAL
    return ResponseLength.NORMAL


def _advance_arc(arc: ConversationArc, record: TurnRecord) -> ConversationArc:
    turn_count = arc.turn_count + 1
    emotional = record.speak in (SpeakAction.ACK_ONLY, SpeakAction.RESPOND) and any(
        c in record.reason_codes for c in ("user_venting", "mixed_intent", "confusion_signal")
    )
    warmth_delta = 0.015 if emotional else -0.004
    relational_warmth = clamp(arc.relational_warmth + warmth_delta, 0.25, 0.82)

    phase = arc.arc_phase
    if turn_count >= 14:
        phase = ArcPhase.WINDING_DOWN
    elif turn_count >= 8:
        phase = ArcPhase.DEEPENING
    elif turn_count >= 3:
        phase = ArcPhase.EXPLORATION

    warmth_series_hint = abs(record.effective_warmth - relational_warmth)
    emotional_drift = clamp(0.85 * arc.emotional_drift + 0.15 * warmth_series_hint)

    closure_attempts = arc.closure_attempts
    if record.user_text.strip().lower() in {"oke", "ok", "thanks", "sip", "noted", "bye"}:
        closure_attempts += 1

    return arc.model_copy(
        update={
            "turn_count": turn_count,
            "relational_warmth": relational_warmth,
            "emotional_drift": emotional_drift,
            "arc_phase": phase,
            "closure_attempts": closure_attempts,
        }
    )


def _assistant_words(text: str | None, speak: SpeakAction) -> int:
    if not text:
        return 55 if speak == SpeakAction.SILENCE else 0
    return len(text.split())


def _long_assistant_bootstrap() -> TurnHistory:
    """Simulate prior long assistant monologue for silence-pressure scripts."""
    return TurnHistory(
        last_speaker="assistant",
        last_assistant_word_count=120,
        last_assistant_verbosity=ResponseLength.EXPAND,
        consecutive_assistant_turns=1,
    )


class SessionSimulator:
    """Runs multi-turn sessions with persistent anchor, arc, and history."""

    def __init__(
        self,
        session_id: str,
        profile: PersonalityProfile | None = None,
        adapter: LLMAdapter | None = None,
        anchor: IdentityAnchor | None = None,
        bootstrap_long_assistant: bool = False,
    ):
        self.session_id = session_id
        self.profile = profile or PersonalityProfile()
        self.adapter = adapter or default_adapter()
        self.anchor = anchor or IdentityAnchor(session_tone_baseline=self.profile.warmth)
        self.history = _long_assistant_bootstrap() if bootstrap_long_assistant else TurnHistory()
        self.messages: list[Message] = []
        self.turns: list[TurnRecord] = []
        arc_store.save(
            ConversationArc(session_id=session_id, relational_warmth=self.profile.warmth - 0.05)
        )

    def seed_long_assistant(self, word_count: int = 120) -> None:
        """Inject prior long assistant turn for silence/closure pressure tests."""
        filler = " ".join(["detail"] * word_count)
        self.history = TurnHistory(
            last_speaker="assistant",
            last_assistant_word_count=word_count,
            last_assistant_verbosity=ResponseLength.EXPAND,
            consecutive_assistant_turns=1,
        )
        self.messages.append(Message.from_text("assistant", filler))

    def run_turn(self, user_text: str) -> TurnRecord:
        arc = arc_store.load(self.session_id)
        out = process_turn(
            self.session_id,
            user_text,
            history=self.history,
            anchor=self.anchor,
            profile=self.profile,
            adapter=self.adapter,
            message_history=self.messages,
        )
        if out.anchor is not None:
            self.anchor = out.anchor

        bdv = out.bdv
        reason_codes = list(bdv.reasoning.reason_codes) if bdv and bdv.reasoning else []
        intent = interpret(Message.from_text("user", user_text), self.history.last_assistant_word_count)
        ctx = (
            build_turn_context(intent, bdv, arc, self.anchor.session_tone_baseline, out.voice.effective_warmth)
            if bdv
            else None
        )

        record = TurnRecord(
            index=len(self.turns),
            user_text=user_text,
            speak=out.voice.speak,
            effective_warmth=out.voice.effective_warmth,
            tone_shift=out.voice.tone_shift.value,
            anchor_baseline=self.anchor.session_tone_baseline,
            arc_warmth=arc.relational_warmth,
            text=out.text,
            llm_called=out.llm_called,
            cps_score=out.cps_score,
            cps_hits=list(out.cps_hits),
            reason_codes=reason_codes,
            context=ctx,
        )
        self.turns.append(record)

        assistant_words = _assistant_words(out.text, out.voice.speak)
        if out.voice.speak in (SpeakAction.SILENCE, SpeakAction.DEFER):
            self.history = TurnHistory(
                last_speaker="user",
                last_assistant_word_count=self.history.last_assistant_word_count,
                last_assistant_verbosity=self.history.last_assistant_verbosity,
                consecutive_assistant_turns=0,
            )
        elif assistant_words > 0 or out.text:
            self.history = TurnHistory(
                last_speaker="assistant",
                last_assistant_word_count=assistant_words or self.history.last_assistant_word_count,
                last_assistant_verbosity=_verbosity_from_words(assistant_words or 20),
                consecutive_assistant_turns=self.history.consecutive_assistant_turns + 1,
            )
        else:
            self.history = TurnHistory(last_speaker="user")

        self.messages.append(Message.from_text("user", user_text))
        if out.text:
            self.messages.append(Message.from_text("assistant", out.text))

        arc_store.save(_advance_arc(arc, record))
        return record

    def run_script(self, name: str, turns: list[str]) -> SessionReport:
        for text in turns:
            self.run_turn(text)
        metrics = compute_drift_metrics(self.turns, self.profile)
        return SessionReport(script_name=name, turns=list(self.turns), metrics=metrics)


def compute_drift_metrics(turns: list[TurnRecord], profile: PersonalityProfile) -> DriftMetrics:
    if not turns:
        return DriftMetrics(
            turn_count=0,
            warmth_values=[],
            anchor_values=[],
            max_warmth_step=0.0,
            warmth_range=0.0,
            anchor_range=0.0,
            warmth_std=0.0,
            speak_counts={},
            max_same_speak_streak=0,
            silence_ratio=0.0,
            mechanical_score=1.0,
            identity_stable=False,
            grade="C",
            notes=["empty session"],
        )

    warmth = [t.effective_warmth for t in turns]
    anchors = [t.anchor_baseline for t in turns]
    steps = [abs(warmth[i] - warmth[i - 1]) for i in range(1, len(warmth))]
    max_step = max(steps) if steps else 0.0
    w_range = max(warmth) - min(warmth)
    a_range = max(anchors) - min(anchors)
    w_std = pstdev(warmth) if len(warmth) > 1 else 0.0

    speak_counts: dict[str, int] = {}
    streak = 1
    max_streak = 1
    prev = turns[0].speak
    for t in turns[1:]:
        speak_counts[t.speak.value] = speak_counts.get(t.speak.value, 0) + 1
        if t.speak == prev:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 1
            prev = t.speak
    speak_counts[turns[0].speak.value] = speak_counts.get(turns[0].speak.value, 0) + 1

    silence_ratio = speak_counts.get(SpeakAction.SILENCE.value, 0) / len(turns)
    respond_ratio = speak_counts.get(SpeakAction.RESPOND.value, 0) / len(turns)

    notes: list[str] = []
    stable = True

    drift_limit = 0.12 + 0.03  # coherence max + tolerance
    if max_step > drift_limit:
        stable = False
        notes.append(f"warmth step {max_step:.3f} > {drift_limit:.2f}")

    if w_range > 0.4:
        stable = False
        notes.append(f"warmth range {w_range:.3f} too wide")
    elif w_range < 0.04 and len(turns) >= 10:
        stable = False
        notes.append("warmth collapsed — entity feels flat")

    if a_range > 0.35:
        notes.append(f"anchor drift range {a_range:.3f} elevated")
        if a_range > 0.45:
            stable = False

    if max_streak >= 10:
        stable = False
        notes.append(f"speak streak {max_streak} — mechanical pattern")

    if respond_ratio > 0.85 and len(turns) >= 15:
        stable = False
        notes.append("over-responsive — not enough silence/ack/defer")

    if silence_ratio > 0.55:
        notes.append("high silence ratio — check closure pressure")

    mechanical = 0.0
    mechanical += min(1.0, max_streak / 12)
    mechanical += min(1.0, max(0.0, respond_ratio - 0.7) * 2)
    mechanical += min(1.0, max(0.0, 0.05 - w_std) * 10)
    mechanical = clamp(mechanical / 3)

    grade = classify_grade(stable, mechanical, notes)

    return DriftMetrics(
        turn_count=len(turns),
        warmth_values=warmth,
        anchor_values=anchors,
        max_warmth_step=max_step,
        warmth_range=w_range,
        anchor_range=a_range,
        warmth_std=w_std,
        speak_counts=speak_counts,
        max_same_speak_streak=max_streak,
        silence_ratio=silence_ratio,
        mechanical_score=mechanical,
        identity_stable=stable,
        grade=grade,
        notes=notes,
    )


def classify_grade(stable: bool, mechanical: float, notes: list[str]) -> str:
    if stable and mechanical < 0.35:
        return "A"
    if stable or (mechanical < 0.55 and len(notes) <= 2):
        return "B"
    return "C"


def classify_session(report: SessionReport) -> str:
    return report.metrics.grade
