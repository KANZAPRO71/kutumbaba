"""Persona Controller — response observer + micro-steer (minimal invasive).

Stages 10–17: separate problem types, priority selector, persona strength escalation,
repeat protection (not persona reset), pending steer until turn finished.

  TURN FINISHED → RESPONSE OBSERVER → DRIFT SCORER → PRIORITY → COOLDOWN → MICRO STEER

Does not touch audio/VAD. Never steer mid-utterance — queue only, deliver on turn_complete.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect
from persona_ai.personality.papua_voice_anti_chatbot import VOICE_CHATBOT_PATTERNS

INTERVENTION_THRESHOLD = 5
DEFAULT_STEER_COOLDOWN_S = 90.0
MIN_TURNS_BEFORE_STEER = 2
DEFAULT_QUESTION_STREAK_THRESHOLD = 3
RECENT_STEER_MEMORY = 3
RECENT_RESPONSE_MEMORY = 5
NATURAL_TURNS_TO_RELAX = 3

_QUESTION_TAIL = re.compile(r"\?\s*$")
_INTERVIEW_MARKERS = re.compile(
    r"\b(mau bahas apa|ada lagi|terus bagaimana|apa lagi|butuh bantuan|"
    r"ada yang (mau|ingin) ditanyakan|silakan tanyakan|how can i help|anything else)\b",
    re.I,
)

_REPEAT_OPENERS = re.compile(
    r"^(adooh+|aduh+|wah+|halo+|hai+|iyaa?,?\s*(sa|ko)?)\b",
    re.I,
)

_MODE_TRIGGERS: dict[str, re.Pattern[str]] = {
    "mop_battle": re.compile(
        r"\b(raja mop|battle mop|mop battle|tantang mop|duel mop|lawan mop)\b", re.I
    ),
    "horror_story": re.compile(
        r"\b(cerita horor|cerita seram|ceritain horor|mode horor|ghost story)\b", re.I
    ),
    "debate": re.compile(
        r"\b(mode debat|debat santai|bantah sa|argument|adu argumen)\b", re.I
    ),
    "gombal": re.compile(
        r"\b(gombal|gombalan|pantun|cari maitua|nyatai maitua)\b", re.I
    ),
}

_MODE_EXIT = re.compile(
    r"\b(keluar mode|stop mode|mode normal|balik normal|udah cukup|selesai mode)\b", re.I
)

MODE_CONFIG: dict[str, dict[str, Any]] = {
    "normal": {"max_words": 60, "question_budget": 1, "empathy": "low"},
    "mop_battle": {"max_words": 40, "question_budget": 0, "empathy": "off"},
    "horror_story": {"max_words": 100, "question_budget": 0, "empathy": "low"},
    "debate": {"max_words": 60, "question_budget": 1, "empathy": "low"},
    "gombal": {"max_words": 50, "question_budget": 0, "empathy": "low"},
}

# Priority categories (Stage 12 order).
PRIORITY_REPEAT = "repeat"
PRIORITY_CHATBOT = "chatbot"
PRIORITY_QUESTIONS = "questions"
PRIORITY_LENGTH = "length"

STEER_VARIANTS: dict[str, list[list[str]]] = {
    PRIORITY_CHATBOT: [
        ["Use a casual friend style.", "Avoid customer-service or assistant language."],
        ["Stay a hangout friend — not a help desk.", "Keep the current conversation context."],
        ["Do not sound like a service agent.", "Continue naturally from the chat."],
    ],
    PRIORITY_LENGTH: [
        ["For casual chat, reply shorter and more spontaneous."],
        ["Trim the reply — hangout tone, not a lecture."],
        ["Keep it brief; one or two beats is enough."],
    ],
    PRIORITY_QUESTIONS: [
        ["Do not interview the user.", "Follow the conversation flow."],
        ["Fewer back-to-back questions.", "Listen more, ask less."],
        ["Stop stacking questions — stay in the flow."],
    ],
    PRIORITY_REPEAT: [
        ["Do not repeat the same opener or filler.", "Continue the current thread naturally."],
        ["Avoid repeating the same phrase or sigh.", "Move the conversation forward."],
    ],
}

_MODE_ACTIVATE_LINES: dict[str, list[str]] = {
    "mop_battle": ["Battle Mop mode active.", "Reply funny, fast, confident sa/ko."],
    "horror_story": ["Horror story mode.", "Build atmosphere — not an FAQ assistant."],
    "debate": ["Casual debate mode.", "Push back briefly and stay spontaneous."],
    "gombal": ["Gombal mode.", "Sweet and short Timur-style banter."],
}

# Backward-compat aliases
DRIFT_SCORE_STEER_THRESHOLD = INTERVENTION_THRESHOLD
CHATBOT_SCORE_STEER_THRESHOLD = INTERVENTION_THRESHOLD


class PersonaMode(str, Enum):
    NORMAL = "normal"
    MOP_BATTLE = "mop_battle"
    HORROR_STORY = "horror_story"
    DEBATE = "debate"
    GOMBAL = "gombal"

    @classmethod
    def parse(cls, raw: str | None) -> PersonaMode:
        if not raw:
            return cls.NORMAL
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.NORMAL


class ControllerPhase(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    RECOVERY = "recovery"


@dataclass
class ResponseAnalysis:
    """Stage 11 — separate scores per problem type."""

    chatbot_score: int = 0
    repeat_score: int = 0
    length_score: int = 0
    question_score: int = 0
    hits: list[str] = field(default_factory=list)
    word_count: int = 0
    question_marks: int = 0

    @property
    def max_score(self) -> int:
        return max(
            self.chatbot_score,
            self.repeat_score,
            self.length_score,
            self.question_score,
        )

    def needs_intervention(self, threshold: int = INTERVENTION_THRESHOLD) -> bool:
        return self.max_score >= threshold

    def to_dict(self) -> dict[str, int]:
        return {
            "chatbot_score": self.chatbot_score,
            "repeat_score": self.repeat_score,
            "length_score": self.length_score,
            "question_score": self.question_score,
        }


# Legacy alias
DriftAnalysis = ResponseAnalysis


@dataclass
class PersonaState:
    mode: str = PersonaMode.NORMAL.value
    phase: str = ControllerPhase.NORMAL.value
    persona_strength: int = 0
    session_drift_total: int = 0
    natural_turns: int = 0
    consecutive_questions: int = 0
    last_refresh_at: float = 0.0
    last_steer_at: float = 0.0
    turns_since_steer: int = 0
    pending_steer: str | None = None
    pending_priority: str | None = None
    pending_reason: str | None = None
    last_assistant_text: str = ""
    last_analysis: ResponseAnalysis | None = None
    recent_responses: list[str] = field(default_factory=list)
    recent_steers: list[str] = field(default_factory=list)
    last_hits: list[str] = field(default_factory=list)
    # Legacy mirrors
    drift_score: int = 0
    chatbot_score: int = 0


@dataclass(frozen=True)
class PersonaControllerConfig:
    steer_cooldown_s: float = DEFAULT_STEER_COOLDOWN_S
    intervention_threshold: int = INTERVENTION_THRESHOLD
    question_streak_threshold: int = DEFAULT_QUESTION_STREAK_THRESHOLD
    observe: bool = True
    deliver_steer: bool = False
    enabled: bool = True
    drift_threshold: int = INTERVENTION_THRESHOLD
    chatbot_threshold: int = INTERVENTION_THRESHOLD
    question_threshold: int = DEFAULT_QUESTION_STREAK_THRESHOLD
    article_word_threshold: int = 60


def mode_behavior(mode: str | PersonaMode | None) -> dict[str, Any]:
    key = mode.value if isinstance(mode, PersonaMode) else str(mode or "normal")
    return dict(MODE_CONFIG.get(key, MODE_CONFIG["normal"]))


def _is_question_turn(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if _QUESTION_TAIL.search(cleaned):
        return True
    return bool(_INTERVIEW_MARKERS.search(cleaned))


def _opener_key(text: str) -> str:
    words = text.lower().split()[:4]
    return " ".join(words)


def _score_repeat(text: str, recent: list[str]) -> tuple[int, list[str]]:
    """Stage 10B — repetition is context/state; Papuan fillers (Adooh) are often natural."""
    hits: list[str] = []
    score = 0
    cleaned = text.strip()
    if not cleaned or len(recent) < 2:
        return 0, hits

    lower = cleaned.lower()
    if _REPEAT_OPENERS.search(lower):
        hits.append("ROP")
        matches = 0
        for prev in recent[-3:]:
            if _REPEAT_OPENERS.search(prev.lower()):
                matches += 1
        if matches >= 2:
            score += 3
            hits.append("RPT")

    opener = _opener_key(cleaned)
    if opener:
        same = sum(1 for prev in recent[-3:] if _opener_key(prev) == opener)
        if same >= 2:
            score += 2
            hits.append("ROP2")

    if len(cleaned) >= 20:
        snippet = lower[:32]
        dupes = sum(1 for prev in recent[-2:] if snippet and snippet in prev.lower()[:48])
        if dupes >= 2:
            score += 2
            hits.append("RSN")

    return score, hits


def analyze_response(
    text: str,
    *,
    mode: str = PersonaMode.NORMAL.value,
    consecutive_questions: int = 0,
    question_streak_threshold: int = DEFAULT_QUESTION_STREAK_THRESHOLD,
    recent_responses: list[str] | None = None,
) -> ResponseAnalysis:
    """Stage 11 — observer output with independent dimension scores."""
    cleaned = text.strip()
    if not cleaned:
        return ResponseAnalysis()

    behavior = mode_behavior(mode)
    max_words = int(behavior.get("max_words", 60))
    question_budget = int(behavior.get("question_budget", 1))
    recent = list(recent_responses or [])

    hits: list[str] = []
    chatbot_score = 0
    length_score = 0
    question_score = 0

    for pattern, code in VOICE_CHATBOT_PATTERNS:
        if pattern.search(cleaned):
            hits.append(code)
            chatbot_score += 2

    word_count = len(cleaned.split())
    if word_count > max_words:
        hits.append("LEN")
        length_score += 2 if word_count > max_words + 20 else 1

    question_marks = cleaned.count("?")
    if question_marks >= 2:
        hits.append("Q2")
        question_score += 1

    if _is_question_turn(cleaned) and question_budget == 0:
        hits.append("Q0")
        question_score += 2

    if consecutive_questions >= question_streak_threshold:
        hits.append("QS")
        question_score += 5

    repeat_score, repeat_hits = _score_repeat(cleaned, recent)
    hits.extend(repeat_hits)

    return ResponseAnalysis(
        chatbot_score=chatbot_score,
        repeat_score=repeat_score,
        length_score=length_score,
        question_score=question_score,
        hits=hits,
        word_count=word_count,
        question_marks=question_marks,
    )


def select_priority(
    analysis: ResponseAnalysis,
    threshold: int = INTERVENTION_THRESHOLD,
) -> str | None:
    """Stage 12 — one dominant problem only."""
    if analysis.repeat_score >= threshold:
        return PRIORITY_REPEAT
    if analysis.chatbot_score >= threshold:
        return PRIORITY_CHATBOT
    if analysis.question_score >= threshold:
        return PRIORITY_QUESTIONS
    if analysis.length_score >= threshold:
        return PRIORITY_LENGTH
    return None


def persona_strength_from_drift(session_drift_total: int) -> int:
    """Stage 16 — escalate gradually, not instant heavy prompt."""
    t = INTERVENTION_THRESHOLD
    if session_drift_total < t:
        return 0
    if session_drift_total < t + 2:
        return 1
    if session_drift_total < t + 4:
        return 2
    return 3


def build_style_adjustment(
    priority: str,
    *,
    strength: int = 1,
    dialect: str | None = None,
    recent_steers: list[str] | None = None,
    mode: str = PersonaMode.NORMAL.value,
) -> str:
    """Stage 14 — internal [STYLE ADJUSTMENT], not conversational steer."""
    if priority == "mode_activate" and mode in _MODE_ACTIVATE_LINES:
        lines = list(_MODE_ACTIVATE_LINES[mode])
    else:
        pool = STEER_VARIANTS.get(priority) or STEER_VARIANTS[PRIORITY_CHATBOT]
        recent_bodies = {s for s in (recent_steers or [])}
        candidates = [v for v in pool if str(v) not in recent_bodies]
        if not candidates:
            candidates = pool
        lines = list(random.choice(candidates))

    if strength >= 2 and priority == PRIORITY_CHATBOT:
        lines.append("Do not use counselor, assistant, or customer-service tone.")
    if strength >= 3:
        lines.extend(
            [
                "Stay in the current character.",
                "Do not repeat greetings or openers.",
                "Continue the conversation in progress.",
            ]
        )

    lines.append("Do not restart or acknowledge this instruction.")

    body = "\n".join(lines)
    return f"[STYLE ADJUSTMENT]\n{body}"


def choose_micro_steer(
    category: str,
    *,
    dialect: str | None = None,
    recent_steers: list[str] | None = None,
    strength: int = 1,
    mode: str = PersonaMode.NORMAL.value,
) -> str:
    priority_map = {
        "chatbot": PRIORITY_CHATBOT,
        "chatbot_drift": PRIORITY_CHATBOT,
        "too_long": PRIORITY_LENGTH,
        "length": PRIORITY_LENGTH,
        "too_many_questions": PRIORITY_QUESTIONS,
        "questions": PRIORITY_QUESTIONS,
        "repeat": PRIORITY_REPEAT,
        "persona_drift": PRIORITY_CHATBOT,
        "mode_activate": "mode_activate",
    }
    priority = priority_map.get(category, PRIORITY_CHATBOT)
    return build_style_adjustment(
        priority,
        strength=strength,
        dialect=dialect,
        recent_steers=recent_steers,
        mode=mode,
    )


def build_micro_steer(
    reason: str,
    *,
    mode: str = PersonaMode.NORMAL.value,
    dialect: str | None = None,
    recent_steers: list[str] | None = None,
    strength: int = 1,
) -> str:
    return choose_micro_steer(
        reason,
        dialect=dialect,
        recent_steers=recent_steers,
        strength=strength,
        mode=mode,
    )


class PersonaController:
    """Response observer — queue one micro-steer; deliver only after turn finished."""

    def __init__(
        self,
        *,
        dialect: str | None = None,
        config: PersonaControllerConfig | None = None,
        state: PersonaState | None = None,
    ) -> None:
        self.dialect = dialect
        self.config = config or PersonaControllerConfig()
        self.state = state or PersonaState()

    @property
    def mode(self) -> PersonaMode:
        return PersonaMode.parse(self.state.mode)

    def _sync_legacy_scores(self, analysis: ResponseAnalysis) -> None:
        self.state.drift_score = analysis.max_score
        self.state.chatbot_score = analysis.chatbot_score
        self.state.last_hits = analysis.hits
        self.state.last_analysis = analysis

    def _update_phase(self, analysis: ResponseAnalysis) -> None:
        mx = analysis.max_score
        threshold = self.config.intervention_threshold
        if mx <= 0:
            if self.state.pending_steer is None:
                self.state.phase = ControllerPhase.NORMAL.value
        elif mx < threshold:
            self.state.phase = ControllerPhase.WARNING.value
        else:
            self.state.phase = ControllerPhase.RECOVERY.value

    def _relax_if_natural(self, analysis: ResponseAnalysis) -> None:
        """Stage 17 — decay strength after natural turns."""
        if analysis.needs_intervention(self.config.intervention_threshold):
            self.state.natural_turns = 0
            return
        self.state.natural_turns += 1
        if self.state.natural_turns >= NATURAL_TURNS_TO_RELAX:
            self.state.persona_strength = max(0, self.state.persona_strength - 1)
            self.state.session_drift_total = max(0, self.state.session_drift_total - 1)
            self.state.natural_turns = 0
            if self.state.persona_strength == 0:
                self.state.phase = ControllerPhase.NORMAL.value

    def on_user_final(self, text: str) -> str | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        if _MODE_EXIT.search(cleaned):
            if self.state.mode != PersonaMode.NORMAL.value:
                self.state.mode = PersonaMode.NORMAL.value
                self.state.consecutive_questions = 0
                steer = build_style_adjustment(
                    PRIORITY_CHATBOT,
                    strength=1,
                    dialect=self.dialect,
                    recent_steers=self.state.recent_steers,
                )
                self.state.pending_priority = PRIORITY_CHATBOT
                self.state.pending_reason = "mode_exit"
                return steer
            return None
        for mode_name, pattern in _MODE_TRIGGERS.items():
            if pattern.search(cleaned) and self.state.mode != mode_name:
                self.state.mode = mode_name
                self.state.consecutive_questions = 0
                steer = build_style_adjustment(
                    "mode_activate",
                    strength=1,
                    dialect=self.dialect,
                    recent_steers=self.state.recent_steers,
                    mode=mode_name,
                )
                self.state.pending_priority = "mode_activate"
                self.state.pending_reason = "mode_activate"
                return steer
        return None

    def on_assistant_finished(self, text: str) -> None:
        """Stage 13 — observe only; queue priority, do not inject mid-audio."""
        if not self.config.observe or not text or not text.strip():
            return

        cleaned = text.strip()
        self.state.last_assistant_text = cleaned
        self.state.turns_since_steer += 1

        if _is_question_turn(cleaned):
            self.state.consecutive_questions += 1
        else:
            self.state.consecutive_questions = 0

        recent = list(self.state.recent_responses)
        analysis = analyze_response(
            cleaned,
            mode=self.state.mode,
            consecutive_questions=self.state.consecutive_questions,
            question_streak_threshold=self.config.question_streak_threshold,
            recent_responses=recent,
        )
        self._sync_legacy_scores(analysis)
        self._update_phase(analysis)
        self._relax_if_natural(analysis)

        recent.append(cleaned)
        self.state.recent_responses = recent[-RECENT_RESPONSE_MEMORY:]

        if not analysis.needs_intervention(self.config.intervention_threshold):
            return
        if self.state.turns_since_steer < MIN_TURNS_BEFORE_STEER:
            return

        priority = select_priority(analysis, self.config.intervention_threshold)
        if not priority:
            return

        self.state.pending_priority = priority
        self.state.pending_reason = priority
        self.state.session_drift_total += 1
        self.state.persona_strength = persona_strength_from_drift(self.state.session_drift_total)
        # Steer text built at turn end (finalize) — not here.

    def finalize_pending_steer(self) -> None:
        """Stage 13 — re-check at turn_complete; build steer if still warranted."""
        if not self.config.enabled:
            return
        if self.state.pending_reason in ("mode_activate", "mode_exit"):
            return
        if not self.state.pending_priority:
            return
        if not self.state.last_assistant_text:
            self.state.pending_priority = None
            self.state.pending_reason = None
            return

        analysis = analyze_response(
            self.state.last_assistant_text,
            mode=self.state.mode,
            consecutive_questions=self.state.consecutive_questions,
            question_streak_threshold=self.config.question_streak_threshold,
            recent_responses=self.state.recent_responses[:-1],
        )
        priority = select_priority(analysis, self.config.intervention_threshold)
        if not priority:
            self.state.pending_priority = None
            self.state.pending_reason = None
            return

        if priority != self.state.pending_priority:
            self.state.pending_priority = priority

        strength = self.state.persona_strength
        if priority == PRIORITY_REPEAT:
            strength = min(strength, 1)

        self.state.pending_steer = build_style_adjustment(
            priority,
            strength=max(1, strength),
            dialect=self.dialect,
            recent_steers=self.state.recent_steers,
            mode=self.state.mode,
        )
        reason_map = {
            PRIORITY_CHATBOT: "chatbot_drift",
            PRIORITY_LENGTH: "too_long",
            PRIORITY_QUESTIONS: "too_many_questions",
            PRIORITY_REPEAT: "repeat_protection",
        }
        self.state.pending_reason = reason_map.get(priority, priority)

    def pending_steer_text(self) -> str | None:
        return self.state.pending_steer

    def can_deliver_steer(self, now: float | None = None) -> bool:
        if not self.config.deliver_steer:
            return False
        if not self.config.observe:
            return False
        if not self.state.pending_priority and not self.state.pending_steer:
            return False
        if self.state.pending_reason in ("mode_activate", "mode_exit"):
            return bool(self.state.pending_steer or self.state.pending_priority)
        ts = now if now is not None else time.monotonic()
        if self.state.last_steer_at > 0 and (ts - self.state.last_steer_at) < self.config.steer_cooldown_s:
            return False
        return True

    def mark_steer_delivered(self, now: float | None = None) -> None:
        ts = now if now is not None else time.monotonic()
        steer = self.state.pending_steer or ""
        if steer:
            recent = list(self.state.recent_steers)
            recent.append(steer)
            self.state.recent_steers = recent[-RECENT_STEER_MEMORY:]

        self.state.last_steer_at = ts
        self.state.last_refresh_at = ts
        self.state.pending_steer = None
        self.state.pending_priority = None
        self.state.pending_reason = None
        self.state.consecutive_questions = 0
        self.state.turns_since_steer = 0
        self.state.natural_turns = 0
        self.state.phase = ControllerPhase.RECOVERY.value

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self.state)
        if self.state.last_analysis:
            data["last_analysis"] = self.state.last_analysis.to_dict()
        return {
            "dialect": self.dialect,
            "config": asdict(self.config),
            "state": data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PersonaController:
        if not data:
            return cls()
        cfg_raw = dict(data.get("config") or {})
        st_raw = dict(data.get("state") or {})
        st_raw.setdefault("phase", ControllerPhase.NORMAL.value)
        st_raw.setdefault("persona_strength", 0)
        st_raw.setdefault("session_drift_total", 0)
        st_raw.setdefault("natural_turns", 0)
        st_raw.setdefault("recent_responses", [])
        st_raw.setdefault("recent_steers", [])
        st_raw.setdefault("drift_score", 0)
        st_raw.setdefault("chatbot_score", 0)
        la = st_raw.pop("last_analysis", None)
        allowed_cfg = {f.name for f in PersonaControllerConfig.__dataclass_fields__.values()}
        cfg_filtered = {k: v for k, v in cfg_raw.items() if k in allowed_cfg}
        allowed_st = {f.name for f in PersonaState.__dataclass_fields__.values()}
        st_filtered = {k: v for k, v in st_raw.items() if k in allowed_st}
        ctrl = cls(
            dialect=data.get("dialect"),
            config=PersonaControllerConfig(**cfg_filtered) if cfg_filtered else PersonaControllerConfig(),
            state=PersonaState(**st_filtered) if st_filtered else PersonaState(),
        )
        if isinstance(la, dict):
            ctrl.state.last_analysis = ResponseAnalysis(**la)
        return ctrl

    @classmethod
    def from_live_mode(
        cls,
        live_mode: Any,
        *,
        dialect: str | None = None,
    ) -> PersonaController:
        cooldown = float(getattr(live_mode, "slip_nudge_cooldown_s", DEFAULT_STEER_COOLDOWN_S))
        deliver = bool(
            getattr(live_mode, "slip_nudge", False)
            or getattr(live_mode, "flow_steer", True)
        )
        observe = bool(getattr(live_mode, "is_natural", True))
        if hasattr(live_mode, "is_natural") and not live_mode.is_natural:
            observe = False
            deliver = False
        return cls(
            dialect=dialect,
            config=PersonaControllerConfig(
                steer_cooldown_s=cooldown,
                observe=observe,
                deliver_steer=deliver,
                enabled=observe,
            ),
        )
