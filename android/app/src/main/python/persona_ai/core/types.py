"""Shared types for Persona AI v0."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class SpeakAction(str, Enum):
    RESPOND = "RESPOND"
    SILENCE = "SILENCE"
    DEFER = "DEFER"
    ACK_ONLY = "ACK_ONLY"


class ResponseLength(str, Enum):
    MINIMAL = "MINIMAL"
    NORMAL = "NORMAL"
    EXPAND = "EXPAND"


class QuestionPolicy(str, Enum):
    NONE = "NONE"
    CLARIFY_ONLY = "CLARIFY_ONLY"
    ALLOWED = "ALLOWED"


class ToneShift(str, Enum):
    STABLE = "STABLE"
    WARMER = "WARMER"
    SOFTER = "SOFTER"
    MATCH_USER = "MATCH_USER"


class IntentDepth(str, Enum):
    NONE = "none"
    SHALLOW = "shallow"
    MODERATE = "moderate"
    DEEP = "deep"


class ArcPhase(str, Enum):
    OPENING = "opening"
    EXPLORATION = "exploration"
    DEEPENING = "deepening"
    RESOLUTION = "resolution"
    WINDING_DOWN = "winding_down"


class Message(BaseModel):
    role: str
    text: str
    word_count: int = 0

    @classmethod
    def from_text(cls, role: str, text: str) -> Message:
        return cls(role=role, text=text.strip(), word_count=len(text.split()))


class TurnHistory(BaseModel):
    last_speaker: str = "user"
    last_assistant_word_count: int = 0
    last_assistant_verbosity: ResponseLength = ResponseLength.NORMAL
    consecutive_assistant_turns: int = 0


class PolicySignal(BaseModel):
    type: str = "must_respond"
    reason: str = ""


class IntentInterpretation(BaseModel):
    depth: IntentDepth = IntentDepth.SHALLOW
    intent_need: float = 0.25
    requires_response: bool = False
    is_direct_question: bool = False
    is_command: bool = False
    is_vent: bool = False
    is_closure_ack: bool = False
    is_rhetorical: bool = False
    is_mixed_intent: bool = False
    is_confusion_signal: bool = False
    incompleteness_score: float = 0.0
    emotional_load: float = 0.2
    reason_codes: list[str] = Field(default_factory=list)


class ContextPressureScore(BaseModel):
    urgency: float = 0.0
    emotional_intensity: float = 0.0
    momentum: float = 0.5
    user_expectation: float = 0.0
    assistant_load: float = 0.0
    speak_pressure: float = 0.0
    silence_pressure: float = 0.0
    defer_pressure: float = 0.0


class BehaviorReasoning(BaseModel):
    primary_reason: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    action_probabilities: dict[str, float] = Field(default_factory=dict)


class BehaviorDirectiveVector(BaseModel):
    speak: SpeakAction
    length: ResponseLength = ResponseLength.NORMAL
    questions: QuestionPolicy = QuestionPolicy.NONE
    question_budget: int = 0
    tone_shift: ToneShift = ToneShift.STABLE
    partial_response: bool = False
    engagement_level: float = 0.5
    timing_delay_ms: int = 0
    pressure: Optional[ContextPressureScore] = None
    reasoning: Optional[BehaviorReasoning] = None

    @property
    def requires_llm(self) -> bool:
        return self.speak in (SpeakAction.RESPOND, SpeakAction.ACK_ONLY)

    @property
    def is_early_exit(self) -> bool:
        return self.speak in (SpeakAction.SILENCE, SpeakAction.DEFER)


class ConversationArc(BaseModel):
    session_id: str = ""
    turn_count: int = 0
    arc_phase: ArcPhase = ArcPhase.OPENING
    relational_warmth: float = 0.45
    emotional_drift: float = 0.0
    closure_attempts: int = 0


class BehaviorInput(BaseModel):
    message: Message
    history: TurnHistory = Field(default_factory=TurnHistory)
    policy_signals: list[PolicySignal] = Field(default_factory=list)
    voice_pause_ms: Optional[int] = None
    arc: Optional[ConversationArc] = None


class AckTemplates(BaseModel):
    vent: list[str] = Field(default_factory=list)
    neutral: list[str] = Field(default_factory=list)
    warm: list[str] = Field(default_factory=list)
    closure: list[str] = Field(default_factory=list)


class PersonalityProfile(BaseModel):
    id: str = "default"
    preset_id: str | None = None
    preset_version: str | None = None
    display_name: str = "Papua AI"
    warmth: float = 0.6
    formality: float = 0.3
    directness: float = 0.5
    empathy: float = 0.5
    humor: float = 0.0
    default_language: str = "id"
    max_words_minimal: int = 20
    max_words_normal: int = 70
    max_words_expand: int = 180
    question_budget_cap: int = 0
    lexicon_preferred: list[str] = Field(default_factory=list)
    lexicon_avoided: list[str] = Field(default_factory=list)
    tone_baseline: str = "casual-warm"
    allowed_tone_shifts: list[str] = Field(
        default_factory=lambda: ["STABLE", "WARMER", "SOFTER", "MATCH_USER"]
    )
    ack_templates: AckTemplates = Field(default_factory=AckTemplates)


class ExpressionConstraints(BaseModel):
    effective_warmth: float = 0.5
    voice_register: str = "casual"
    max_words: int = 60
    max_sentences: int = 2
    question_budget: int = 0
    tone_shift: ToneShift = ToneShift.STABLE
    prompt_fragments: list[str] = Field(default_factory=list)
    template_ack: Optional[str] = None


class IdentityAnchor(BaseModel):
    session_tone_baseline: float = 0.5
    max_drift_per_turn: float = 0.12


class VoiceDirective(BaseModel):
    speak: SpeakAction
    effective_warmth: float
    max_words: int
    max_sentences: int
    question_budget: int
    tone_shift: ToneShift
    prompt_fragments: list[str] = Field(default_factory=list)
    template_ack: Optional[str] = None
    timing_delay_ms: int = 0


class PolicyConstraintsRef(BaseModel):
    """Lightweight policy constraint injection for LLM assembly."""

    inject_system_lines: list[str] = Field(default_factory=list)
    blocked_phrases: list[str] = Field(default_factory=list)
    required_disclaimer: str | None = None


class LLMRequest(BaseModel):
    user_message: str
    voice: VoiceDirective
    history: list[Message] = Field(default_factory=list)
    policy_constraints: Optional["PolicyConstraintsRef"] = None
    agent_timezone: str | None = None
    language: str = "id"


class LLMResponse(BaseModel):
    text: str
    model: str = "mock"
    usage_tokens: int = 0
