"""Conversation Flow Controller — ritme tongkrongan vs host/CS/interview.

Persona Controller = siapa AI bicara.
Conversation Flow Controller = bagaimana AI merespons giliran ini.

Architecture:
  RESPONSE OBSERVER → classify → ConversationState → FlowDecision → micro-steer
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# --- Tunables ---

QUESTION_LIMIT = 1
WINDOW_TURNS = 3
FLOW_INTERVENTION_THRESHOLD = 2

# --- Response taxonomy ---

class ResponseType(str, Enum):
    COMMENT = "comment"
    REACTION = "reaction"
    STORY = "story"
    QUESTION = "question"
    MOP = "mop"
    SUPPORT = "support"
    SILENCE = "silence"


class FlowDirective(str, Enum):
    ASK_OK = "ask_ok"
    COMMENT_ONLY = "comment_only"
    FOLLOW = "follow"
    REACT = "react"
    LISTEN = "listen"
    NO_MENU = "no_menu"
    NO_HELPER = "no_helper"
    DELIVER_MOP = "deliver_mop"
    NO_QUESTION = "no_question"


# --- Hard blacklist: menu / host patterns ---

MENU_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmau bahas apa\b", re.I), "FM1"),
    (re.compile(r"\bmau yang mana\b", re.I), "FM2"),
    (re.compile(r"\b(soal|tentang) .{0,50}(atau|or)\b", re.I), "FM3"),
    (re.compile(r"\bmau dengar mop (atau|or)\b", re.I), "FM4"),
    (re.compile(r"\bmau cerita tentang\b", re.I), "FM5"),
    (re.compile(r"\bmau (dengar|cerita|ngomong) (apa|mop|lagi)\b", re.I), "FM6"),
    (re.compile(r"\bmau mulai dari mana\b", re.I), "FM7"),
    (re.compile(r"\bmau dengar mop\b.*\?\s*$", re.I), "FM8"),
    (re.compile(r"\bmau cerita apa\b", re.I), "FM9"),
    (re.compile(r"\bsilakan pilih\b", re.I), "FM10"),
    (re.compile(r"\bapa (lagi|nih) (yang|mau)\b", re.I), "FM11"),
]

HELPER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsa siap (dengar|membantu|mendengar|hibur)\b", re.I), "FH1"),
    (re.compile(r"\bsaya siap (dengar|membantu|mendengar)\b", re.I), "FH2"),
    (re.compile(r"\b(kasih masukan|sa kasih masukan)\b", re.I), "FH3"),
    (re.compile(r"\b(kalau bisa|biar sa) (bantu|hibur)\b", re.I), "FH4"),
    (re.compile(r"\bkasian sekali\b", re.I), "FH5"),
    (re.compile(r"\bsa siap bantu\b", re.I), "FH6"),
    (re.compile(r"\bhow can i help\b", re.I), "FH7"),
    (re.compile(r"\bsa siap kasih masukan\b", re.I), "FH8"),
]

_CLOSING_Q = re.compile(r"\?\s*$")

# --- Classification heuristics ---

_MOP_MARKERS = re.compile(
    r"\b(pace|mop|cerita lucu|tinus|komandan|adooo|jedag)\b", re.I
)
_STORY_MARKERS = re.compile(
    r"\b(tadi sa (ingat|dengar|lihat)|dulu (sa|ko)|suatu hari|"
    r"jadi cerita|begini ceritanya)\b",
    re.I,
)
_REACTION_MARKERS = re.compile(
    r"^(aduh+|adoo+|wah+|haha+|hehe+|iyaa?|mantap|parah|gila)\b", re.I
)
_SUPPORT_MARKERS = re.compile(
    r"\b(jangan (terlalu )?(dipikir|dipaks)|istirahat dulu|tenang dulu|"
    r"santai dulu|jangan paksa)\b",
    re.I,
)
_USER_MOP_REQUEST = re.compile(
    r"\b(mau dengar mop|ceritain mop|kasih mop|mo dengar sa pu mop|"
    r"dong mop|cerita mop)\b",
    re.I,
)
_USER_DIRECT_QUESTION = re.compile(r"\?\s*$")
_USER_SHORT = re.compile(
    r"^(iya|iyo|betul|benar|gitu|oh|oke|ok|hm+|hmm+|ya|yoi|mantap|"
    r"sudah|cukup|gitu saja|gitu aja)\.?\s*$",
    re.I,
)
_USER_SANTAI = re.compile(
    r"\b(santai|tenang|relax|tak usah|tra usah|jangan (terlalu )?pikir|"
    r"bacarita saja|ngobrol (saja|aja|mengalir)|mengalir saja)\b",
    re.I,
)
_USER_CAPEK = re.compile(
    r"\b(capek|lelah|pikiran (agak )?capek|kepala (panas|penuh|ribet)|"
    r"otak (panas|penuh)|burnout|kerja (banyak|padat))\b",
    re.I,
)
_USER_CLOSURE = re.compile(
    r"\b(makasih|thank|sampai|bye|dadah|sudah dulu)\b", re.I
)


@dataclass
class ConversationState:
    """Rolling flow state — separate from persona identity."""

    question_streak: int = 0
    natural_turns: int = 0
    window_turns: int = 0
    questions_in_window: int = 0
    silence_allowed: bool = True
    last_response_type: ResponseType | None = None
    last_user_short: bool = False
    user_wants_mop: bool = False
    must_not_question: bool = False
    follow_topic: bool = True


@dataclass
class UserFlowSignal:
    intent: str = "normal"
    directive: FlowDirective = FlowDirective.FOLLOW
    direct_question: bool = False
    short_answer: bool = False
    hits: list[str] = field(default_factory=list)


@dataclass
class AssistantFlowAnalysis:
    response_type: ResponseType = ResponseType.COMMENT
    menu_score: int = 0
    helper_score: int = 0
    closing_question: bool = False
    hits: list[str] = field(default_factory=list)

    @property
    def is_menu_slip(self) -> bool:
        return self.menu_score >= 2

    @property
    def is_helper_slip(self) -> bool:
        return self.helper_score >= 2

    def needs_correction(self) -> bool:
        if self.is_menu_slip or self.is_helper_slip:
            return True
        if self.response_type == ResponseType.QUESTION and self.closing_question:
            return False  # handled by budget/streak
        return False


@dataclass
class FlowDecision:
    """Output of decision tree — what the next turn should look like."""

    directive: FlowDirective
    preferred_types: tuple[ResponseType, ...] = (ResponseType.COMMENT,)
    allow_question: bool = False
    allow_silence: bool = True
    reason: str = ""


def classify_response(text: str) -> ResponseType:
    """Classify assistant turn into flow category."""
    cleaned = text.strip()
    if not cleaned:
        return ResponseType.SILENCE

    lower = cleaned.lower()
    if any(p.search(cleaned) for p, _ in MENU_PATTERNS):
        return ResponseType.QUESTION
    if _MOP_MARKERS.search(cleaned) and len(cleaned.split()) > 12:
        return ResponseType.MOP
    if _STORY_MARKERS.search(cleaned):
        return ResponseType.STORY
    if _SUPPORT_MARKERS.search(cleaned) or any(
        p.search(cleaned) for p, _ in HELPER_PATTERNS
    ):
        return ResponseType.SUPPORT
    if _REACTION_MARKERS.search(cleaned) and len(cleaned.split()) <= 12:
        return ResponseType.REACTION
    if _CLOSING_Q.search(cleaned):
        return ResponseType.QUESTION
    if len(cleaned.split()) <= 8:
        return ResponseType.COMMENT
    return ResponseType.COMMENT


def analyze_user_turn(text: str) -> UserFlowSignal:
    cleaned = text.strip()
    if not cleaned:
        return UserFlowSignal()

    hits: list[str] = []
    if _USER_MOP_REQUEST.search(cleaned):
        hits.append("UMOP")
        return UserFlowSignal(
            intent="mop_request",
            directive=FlowDirective.DELIVER_MOP,
            hits=hits,
        )
    if _USER_SHORT.match(cleaned):
        hits.append("USHORT")
        return UserFlowSignal(
            intent="short",
            directive=FlowDirective.FOLLOW,
            short_answer=True,
            hits=hits,
        )
    if _USER_SANTAI.search(cleaned):
        hits.append("USANTAI")
        return UserFlowSignal(
            intent="santai",
            directive=FlowDirective.COMMENT_ONLY,
            hits=hits,
        )
    if _USER_CAPEK.search(cleaned):
        hits.append("UCAPEK")
        return UserFlowSignal(
            intent="capek",
            directive=FlowDirective.NO_HELPER,
            hits=hits,
        )
    if _USER_CLOSURE.search(cleaned) and len(cleaned.split()) <= 8:
        hits.append("UCLOSE")
        return UserFlowSignal(
            intent="closure",
            directive=FlowDirective.LISTEN,
            hits=hits,
        )
    direct_q = bool(_USER_DIRECT_QUESTION.search(cleaned))
    if direct_q:
        hits.append("UDQ")
    return UserFlowSignal(
        intent="normal",
        directive=FlowDirective.FOLLOW,
        direct_question=direct_q,
        hits=hits,
    )


def analyze_assistant_turn(text: str) -> AssistantFlowAnalysis:
    cleaned = text.strip()
    if not cleaned:
        return AssistantFlowAnalysis()

    hits: list[str] = []
    menu_score = 0
    helper_score = 0

    for pattern, code in MENU_PATTERNS:
        if pattern.search(cleaned):
            hits.append(code)
            menu_score += 2
    for pattern, code in HELPER_PATTERNS:
        if pattern.search(cleaned):
            hits.append(code)
            helper_score += 2

    closing = bool(_CLOSING_Q.search(cleaned))
    if closing:
        hits.append("FQ")

    return AssistantFlowAnalysis(
        response_type=classify_response(cleaned),
        menu_score=menu_score,
        helper_score=helper_score,
        closing_question=closing,
        hits=hits,
    )


def decide_next_turn(
    state: ConversationState,
    user: UserFlowSignal,
) -> FlowDecision:
    """Decision tree after user finishes speaking."""

    # User asked a direct question → answer it (question in answer is OK if needed)
    if user.direct_question:
        return FlowDecision(
            directive=FlowDirective.FOLLOW,
            preferred_types=(ResponseType.COMMENT, ResponseType.REACTION),
            allow_question=False,
            allow_silence=False,
            reason="answer_direct_question",
        )

    # User wants mop → deliver story, no menu follow-up
    if user.intent == "mop_request" or state.user_wants_mop:
        return FlowDecision(
            directive=FlowDirective.DELIVER_MOP,
            preferred_types=(ResponseType.MOP, ResponseType.STORY),
            allow_question=False,
            allow_silence=False,
            reason="deliver_mop",
        )

    if user.intent == "santai":
        return FlowDecision(
            directive=FlowDirective.COMMENT_ONLY,
            preferred_types=(ResponseType.COMMENT, ResponseType.REACTION),
            allow_question=False,
            allow_silence=True,
            reason="user_santai",
        )

    if user.intent == "capek":
        return FlowDecision(
            directive=FlowDirective.NO_HELPER,
            preferred_types=(ResponseType.COMMENT, ResponseType.REACTION),
            allow_question=False,
            allow_silence=True,
            reason="user_capek",
        )

    if user.intent == "closure":
        return FlowDecision(
            directive=FlowDirective.LISTEN,
            preferred_types=(ResponseType.COMMENT,),
            allow_question=False,
            allow_silence=True,
            reason="user_closure",
        )

    # Short answer → follow topic, do not interview
    if user.short_answer or state.last_user_short:
        return FlowDecision(
            directive=FlowDirective.FOLLOW,
            preferred_types=(ResponseType.COMMENT, ResponseType.REACTION, ResponseType.STORY),
            allow_question=False,
            allow_silence=True,
            reason="short_answer_follow",
        )

    # Anti-question streak
    if state.must_not_question or state.question_streak >= 1:
        return FlowDecision(
            directive=FlowDirective.NO_QUESTION,
            preferred_types=(ResponseType.COMMENT, ResponseType.REACTION),
            allow_question=False,
            allow_silence=True,
            reason="anti_question_streak",
        )

    # Question budget: max 1 question per WINDOW_TURNS agent turns
    if state.questions_in_window >= QUESTION_LIMIT:
        return FlowDecision(
            directive=FlowDirective.NO_QUESTION,
            preferred_types=(ResponseType.COMMENT, ResponseType.REACTION, ResponseType.STORY),
            allow_question=False,
            allow_silence=True,
            reason="question_budget_exhausted",
        )

    # Default: follow 70% — react/comment, rare question allowed
    return FlowDecision(
        directive=FlowDirective.FOLLOW,
        preferred_types=(ResponseType.COMMENT, ResponseType.REACTION, ResponseType.STORY),
        allow_question=state.questions_in_window < QUESTION_LIMIT,
        allow_silence=True,
        reason="follow_topic",
    )


def _format_steer(decision: FlowDecision, *, lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"[FLOW ADJUSTMENT]\n{body}\nDo not restart or acknowledge this instruction."


def build_pre_turn_steer(decision: FlowDecision) -> str:
    """Micro-steer before agent generates — shapes this turn only."""
    lines: list[str] = []

    if decision.directive == FlowDirective.DELIVER_MOP:
        lines.extend([
            "User wants a Mop — tell the story directly.",
            "Do NOT ask 'mau dengar lagi?' or offer another menu after.",
            "Start the Pace/Mop, then stop.",
        ])
    elif decision.directive == FlowDirective.COMMENT_ONLY:
        lines.extend([
            "FOLLOW_THROUGH — match user's chill energy; do NOT PUSH_FORWARD with questions.",
            "Short comment or reaction — tongkrongan friend.",
            "NO menu ('mau bahas apa'), NO helper tone, NO closing question.",
            "Example: 'Iyo eh, santai saja toh.' Optional: 'Tong biar ngobrol mengalir saja.' then stop.",
            "Do NOT ask 'ko ada cerita apa', 'apa yang ko pikirkan', or offer new topics.",
        ])
    elif decision.directive == FlowDirective.NO_HELPER:
        lines.extend([
            "User is tired — react like a friend, NOT counselor/helpdesk.",
            "NO 'kasian sekali', NO 'sa siap hibur/bantu'.",
            "Follow what they said about work/life — one warm line, then listen.",
        ])
    elif decision.directive == FlowDirective.NO_QUESTION:
        lines.extend([
            "Do NOT end with a question — this is not an interview.",
            "Follow the user's last topic: comment, react, or small story beat.",
            "Silence after a short line is OK.",
        ])
    elif decision.directive == FlowDirective.FOLLOW:
        lines.extend([
            "Follow user's topic — 70% follow, 20% react, 10% lead.",
            "Do NOT offer topic menus. Do NOT ask unless truly necessary.",
        ])
        if not decision.allow_question:
            lines.append("No question mark at the end of this turn.")
    elif decision.directive == FlowDirective.LISTEN:
        lines.append("One warm closing line max — no new topics, no questions.")

    if decision.allow_silence:
        lines.append("Ending without inviting a reply is valid — do not fill silence.")

    return _format_steer(decision, lines=lines)


def build_correction_steer(
    analysis: AssistantFlowAnalysis,
    state: ConversationState,
) -> str:
    """Micro-steer after a flow slip — correct next turn."""
    lines: list[str] = []

    if analysis.is_menu_slip:
        lines.append(
            "Don't offer menus ('mau bahas apa', 'mau yang mana', 'soal ini atau itu'). "
            "Follow the last user topic instead."
        )
    if analysis.is_helper_slip:
        lines.append(
            "Don't use helper language ('sa siap dengar/membantu', 'sa kasih masukan'). "
            "Stay a hangout friend."
        )
    if analysis.closing_question and (
        state.must_not_question or state.question_streak >= 1
    ):
        lines.append(
            "Don't interview the user — follow the conversation that's already flowing."
        )
    if analysis.closing_question and state.questions_in_window >= QUESTION_LIMIT:
        lines.append(
            "Too many questions recently — comment or react only, no question mark."
        )
    if analysis.response_type == ResponseType.QUESTION and state.last_user_short:
        lines.append(
            "User gave a short answer — don't stack another question. Follow or react."
        )

    if not lines:
        # Generic anti-interview nudge
        if state.question_streak >= 2:
            lines.append(
                "Ikuti alur user. Jangan menawarkan pilihan topik. "
                "Jangan menutup setiap respons dengan pertanyaan."
            )
        else:
            return ""

    lines.append("Continue the same thread naturally.")
    return _format_steer(
        FlowDecision(directive=FlowDirective.NO_QUESTION, reason="correction"),
        lines=lines,
    )


class ConversationFlowController:
    """Conversation rhythm controller — distinct from PersonaController."""

    def __init__(
        self,
        *,
        question_limit: int = QUESTION_LIMIT,
        window_turns: int = WINDOW_TURNS,
    ) -> None:
        self.question_limit = max(0, question_limit)
        self.window_turns = max(1, window_turns)
        self.state = ConversationState()
        self.last_user_signal: UserFlowSignal | None = None
        self.last_decision: FlowDecision | None = None
        self.pending_pre_turn_steer: str | None = None
        self.pending_correction_steer: str | None = None

    def _advance_window(self) -> None:
        self.state.window_turns += 1
        if self.state.window_turns >= self.window_turns:
            self.state.window_turns = 0
            self.state.questions_in_window = 0

    def on_user_final(self, text: str) -> str | None:
        signal = analyze_user_turn(text)
        self.last_user_signal = signal
        self.state.last_user_short = signal.short_answer
        self.state.user_wants_mop = signal.intent == "mop_request"

        decision = decide_next_turn(self.state, signal)
        self.last_decision = decision
        steer = build_pre_turn_steer(decision)
        if steer:
            self.pending_pre_turn_steer = steer
        return steer or None

    def on_assistant_finished(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        analysis = analyze_assistant_turn(cleaned)
        self.state.last_response_type = analysis.response_type

        # Update question tracking
        if analysis.closing_question or analysis.response_type == ResponseType.QUESTION:
            self.state.question_streak += 1
            self.state.questions_in_window += 1
            self.state.natural_turns = 0
            self.state.must_not_question = True
        else:
            self.state.question_streak = 0
            self.state.natural_turns += 1
            self.state.must_not_question = False

        self._advance_window()

        # After user confirmed mop, clear mop flag once story delivered
        if self.state.user_wants_mop and analysis.response_type in (
            ResponseType.MOP,
            ResponseType.STORY,
        ):
            self.state.user_wants_mop = False

        correction = build_correction_steer(analysis, self.state)
        if correction:
            self.pending_correction_steer = correction
        elif analysis.is_menu_slip or (
            analysis.closing_question and self.state.question_streak >= 2
        ):
            self.pending_correction_steer = build_correction_steer(
                analysis, self.state
            )

    def take_pre_turn_steer(self) -> str | None:
        steer = self.pending_pre_turn_steer
        self.pending_pre_turn_steer = None
        return steer

    def take_correction_steer(self) -> str | None:
        steer = self.pending_correction_steer
        self.pending_correction_steer = None
        return steer

    def pending_steer(self) -> str | None:
        return self.pending_pre_turn_steer or self.pending_correction_steer

    def to_dict(self) -> dict:
        return {
            "state": {
                "question_streak": self.state.question_streak,
                "natural_turns": self.state.natural_turns,
                "window_turns": self.state.window_turns,
                "questions_in_window": self.state.questions_in_window,
                "last_response_type": (
                    self.state.last_response_type.value
                    if self.state.last_response_type
                    else None
                ),
                "must_not_question": self.state.must_not_question,
            },
            "last_decision": self.last_decision.reason if self.last_decision else None,
        }


# --- Backward-compat aliases ---

analyze_user_flow = analyze_user_turn
analyze_assistant_flow = analyze_assistant_turn


def build_flow_pre_turn_steer(signal: UserFlowSignal, *, dialect: str | None = None) -> str:
    del dialect
    decision = decide_next_turn(ConversationState(), signal)
    return build_pre_turn_steer(decision)


def build_flow_correction_steer(
    analysis: AssistantFlowAnalysis,
    *,
    consecutive_questions: int = 0,
    question_budget: int = 0,
) -> str:
    del question_budget
    state = ConversationState(
        question_streak=consecutive_questions,
        questions_in_window=min(consecutive_questions, QUESTION_LIMIT),
        must_not_question=consecutive_questions >= 1,
    )
    return build_correction_steer(analysis, state)
