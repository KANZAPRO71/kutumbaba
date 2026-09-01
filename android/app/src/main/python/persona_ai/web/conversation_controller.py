"""Unified sidecar controller — observes transcripts only, steers at safe boundaries.

Does NOT touch audio/VAD/full-duplex. Hooks:
  1. observe_response(text) on model turn complete
  2. take_pending_steer() + mark_steer_sent() on safe turn boundary
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DriftCategory(StrEnum):
    CHATBOT = "chatbot"
    MENU_LOOP = "menu_loop"
    QUESTION_LOOP = "question_loop"
    PUSH_FORWARD = "push_forward"
    REPETITION = "repetition"
    TOO_LONG = "too_long"
    TOPIC_ESCAPE = "topic_escape"


_REPEAT_OPENER = re.compile(
    r"^(adooh+|adoh+h*|aduh+|wah+|halo+|hai+|iyaa?,?\s*(sa|ko)?)\b",
    re.I,
)
_FILLER_ADOH = re.compile(r"\badoh+h*\b", re.I)
_NORMALIZE_RE = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass
class ControllerState:
    chatbot_score: int = 0
    offering_question_streak: int = 0
    invitation_streak: int = 0
    natural_turns: int = 0
    last_steer_time: float = 0.0
    pending_steer: str | None = None
    recent_steers: list[str] = field(default_factory=list)
    last_category: str | None = None
    last_steer_category: str | None = None
    recent_responses: list[str] = field(default_factory=list)
    filler_opener_streak: int = 0
    last_user_follow_through: bool = False


class ConversationController:
    """Persona + flow observer — transcript in, pending steer out."""

    STEER_COOLDOWN = 30.0

    MENU_SELECTION_SCORE = 3
    TOPIC_OFFERING_SCORE = 1
    REPEATED_INVITATION_SCORE = 1
    HELPER_SCORE = 3
    CS_SCORE = 3
    TOPIC_ESCAPE_SCORE = 3

    COOLDOWNS: dict[str, float] = {
        DriftCategory.REPETITION: 45.0,
        DriftCategory.MENU_LOOP: 25.0,
        DriftCategory.QUESTION_LOOP: 30.0,
        DriftCategory.PUSH_FORWARD: 25.0,
        DriftCategory.CHATBOT: 30.0,
        DriftCategory.TOPIC_ESCAPE: 45.0,
        DriftCategory.TOO_LONG: 30.0,
    }

    HELPER_PATTERNS: tuple[str, ...] = (
        "sa siap membantu",
        "sa siap bantu",
        "sa siap mendengar",
        "sa siap dengar",
        "sa siap hibur",
        "sa siap kasih masukan",
        "sa kasih masukan",
        "saya siap membantu",
        "saya siap mendengar",
    )

    CS_PATTERNS: tuple[str, ...] = (
        "ada yang bisa saya bantu",
        "ada yang mau ditanyakan",
        "ada lagi yang ingin ditanyakan",
        "ada lagi yang bisa",
        "ada lagi yang mau",
        "silakan tanyakan",
        "saya di sini untuk membantu",
        "saya mengerti perasaan",
        "saya paham perasaan",
        "perasaan ko",
        "kasian sekali",
        "butuh bantuan",
        "semoga membantu",
        "tentu saja",
    )

    # Score once per group — no literal overlap inflation.
    MENU_SELECTION_PATTERNS: tuple[str, ...] = (
        "mau bahas apa",
        "mau cerita tentang apa",
        "mau yang mana",
        "mau mulai dari mana",
        "mau cerita apa",
    )

    TOPIC_OFFERING_PATTERNS: tuple[str, ...] = (
        "mau cerita tentang",
        "soal cuaca",
        "tentang perjalanan",
        "mau dengar mop atau",
        "mau dengar mop kah",
        "mau dengar mop",
        "mau cerita mop",
    )

    REPEATED_INVITATION_PATTERNS: tuple[str, ...] = (
        "mau dengar yang lain lagi",
        "mau dengar yang lain",
        "ko mau dengar",
        "mau lagi kah",
        "mau lagi ga",
        "mau cerita apa",
        "mau ngobrol apa",
    )

    OFFERING_QUESTION_PATTERNS: tuple[str, ...] = (
        "mau bahas",
        "mau cerita",
        "mau dengar",
        "mau yang mana",
        "ko mau",
        "ada yang mau",
        "mau lagi kah",
        "mau lagi ga",
        "tadi lagu apa",
        "lagu apa yang ko",
        "ko suka lagu",
        "ko suka genre",
        "cerita apa lagi",
        "mau ngobrol apa",
        "apa yang ko dengar",
        "mau bahas apa lagi",
    )

    TOPIC_ESCAPE_REFUSAL_PATTERNS: tuple[str, ...] = (
        "itu sensitif",
        "topik sensitif",
        "terlalu sensitif",
        "tra bisa bicara",
        "tidak bisa bicara",
        "nggak bisa bahas",
        "gak bisa bahas",
        "jangan bahas",
    )

    TOPIC_ESCAPE_REDIRECT_PATTERNS: tuple[str, ...] = (
        "lebih baik cerita lucu",
        "cerita lucu-lucu saja",
        "cerita lucu saja",
        "alihkan ke mop",
        "mau dengar mop aja",
        "bahas yang lain saja",
        "kitong bahas yang lain",
    )

    STEERS: dict[str, tuple[str, ...]] = {
        DriftCategory.CHATBOT: (
            "Jangan menawarkan bantuan atau bertindak sebagai fasilitator. "
            "Jadi teman tongkrongan dan ikuti alur percakapan tanpa mengakui arahan ini.",
        ),
        DriftCategory.MENU_LOOP: (
            "Ikuti topik yang sedang berjalan. Jangan menawarkan menu, pilihan topik, "
            "atau tanya 'mau bahas apa'. Reaksi singkat sudah cukup.",
        ),
        DriftCategory.QUESTION_LOOP: (
            "Jangan interview user atau menutup setiap respons dengan pertanyaan penawaran. "
            "Komentar atau reaksi singkat sudah cukup — biarkan user yang memimpin. "
            "Kalau ko baru saja ucapkan terima kasih atau pamit, jangan buka topik baru."
        ),
        DriftCategory.PUSH_FORWARD: (
            "User bilang short/chill — satu reaksi hangat yang BEDA dari giliran sebelumnya. "
            "Lanjut ke isi topik, tanpa pertanyaan penutup atau menu."
        ),
        DriftCategory.REPETITION: (
            "Jangan mengulang kalimat, sapaan, atau filler yang sama dari giliran sebelumnya. "
            "Lanjutkan percakapan dengan respons baru dan alami.",
        ),
        DriftCategory.TOPIC_ESCAPE: (
            "Jangan otomatis mengalihkan topik user ke mop atau hiburan. "
            "Ikuti topik yang sedang dibicarakan secara natural — bisa santai tapi tetap on-topic.",
        ),
        DriftCategory.TOO_LONG: (
            "Untuk obrolan santai, jawab lebih singkat dan spontan.",
        ),
    }

    RECENT_RESPONSES_MAX = 4
    SIMILARITY_STRONG = 0.58
    SIMILARITY_MILD = 0.38

    def __init__(
        self,
        *,
        steer_cooldown: float = STEER_COOLDOWN,
        deliver_steer: bool = True,
    ) -> None:
        self.steer_cooldown = max(0.0, steer_cooldown)
        self.deliver_steer = deliver_steer
        self.state = ControllerState()

    @classmethod
    def from_live_mode(cls, live_mode: Any) -> ConversationController:
        cooldown = float(getattr(live_mode, "slip_nudge_cooldown_s", cls.STEER_COOLDOWN))
        if getattr(live_mode, "is_natural", False):
            return cls(steer_cooldown=cooldown, deliver_steer=False)
        deliver = bool(
            getattr(live_mode, "slip_nudge", False)
            or getattr(live_mode, "flow_steer", True)
        )
        return cls(steer_cooldown=cooldown, deliver_steer=deliver)

    @staticmethod
    def _matches_any(text_lower: str, patterns: tuple[str, ...]) -> bool:
        return any(phrase in text_lower for phrase in patterns)

    def _cooldown_for(self, category: str | None) -> float:
        if category:
            return self.COOLDOWNS.get(category, self.steer_cooldown)
        return self.steer_cooldown

    @staticmethod
    def _normalize_for_similarity(text: str) -> str:
        lowered = text.lower().strip()
        cleaned = _NORMALIZE_RE.sub(" ", lowered)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _word_similarity(a: str, b: str) -> float:
        wa = set(a.split())
        wb = set(b.split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    def _opener_key(self, text: str) -> str:
        words = text.lower().split()[:4]
        return " ".join(words)

    def _is_offering_question(self, text_lower: str) -> bool:
        if "?" not in text_lower:
            return False
        groups = (
            self.MENU_SELECTION_PATTERNS,
            self.TOPIC_OFFERING_PATTERNS,
            self.REPEATED_INVITATION_PATTERNS,
            self.OFFERING_QUESTION_PATTERNS,
        )
        return any(self._matches_any(text_lower, group) for group in groups)

    def _score_menu(self, text_lower: str) -> int:
        if self._matches_any(text_lower, self.MENU_SELECTION_PATTERNS):
            return self.MENU_SELECTION_SCORE
        score = 0
        if self._matches_any(text_lower, self.TOPIC_OFFERING_PATTERNS):
            score += self.TOPIC_OFFERING_SCORE
        if self._matches_any(text_lower, self.REPEATED_INVITATION_PATTERNS):
            score += self.REPEATED_INVITATION_SCORE
        return score

    def _score_chatbot(self, text_lower: str) -> int:
        score = 0
        if self._matches_any(text_lower, self.HELPER_PATTERNS):
            score += self.HELPER_SCORE
        if self._matches_any(text_lower, self.CS_PATTERNS):
            score += self.CS_SCORE
        return score

    def _score_topic_escape(self, text_lower: str) -> int:
        refused = self._matches_any(text_lower, self.TOPIC_ESCAPE_REFUSAL_PATTERNS)
        redirected = self._matches_any(text_lower, self.TOPIC_ESCAPE_REDIRECT_PATTERNS)
        if refused and redirected:
            return self.TOPIC_ESCAPE_SCORE
        return 0

    def _score_repetition(self, text: str) -> int:
        """Near-repeat vs recent responses, filler streaks, and opener reuse."""
        cleaned = text.strip()
        if not cleaned:
            return 0

        score = 0
        lower = cleaned.lower()
        recent = self.state.recent_responses
        norm = self._normalize_for_similarity(cleaned)

        similarity_score = 0
        for prev in recent[-3:]:
            sim = self._word_similarity(norm, self._normalize_for_similarity(prev))
            if sim >= self.SIMILARITY_STRONG:
                similarity_score = 3
                break
            if sim >= self.SIMILARITY_MILD:
                similarity_score = max(similarity_score, 2)
        score += similarity_score

        adoh_count = len(_FILLER_ADOH.findall(lower))
        if adoh_count >= 2:
            score += 2

        if _REPEAT_OPENER.search(lower):
            if self.state.filler_opener_streak >= 1:
                score += 3
            matches = sum(
                1 for prev in recent[-3:] if _REPEAT_OPENER.search(prev.lower())
            )
            if matches >= 2:
                score += 3

        opener = self._opener_key(cleaned)
        if opener and len(recent) >= 2:
            same = sum(1 for prev in recent[-3:] if self._opener_key(prev) == opener)
            if same >= 2:
                score += 2

        if len(cleaned) >= 20:
            snippet = norm[:40]
            for prev in recent[-2:]:
                prev_norm = self._normalize_for_similarity(prev)
                if snippet and snippet in prev_norm[:60]:
                    score += 3
                    break

        return score

    def observe_user_turn(self, text: str) -> None:
        """Remember low-energy user turns — next assistant reply should follow, not push."""
        from persona_ai.web.conversation_flow_controller import analyze_user_turn

        signal = analyze_user_turn(text)
        lowered = text.lower()
        chill_embedded = any(
            phrase in lowered
            for phrase in (
                "santai aja",
                "santai saja",
                "tenang aja",
                "tenang saja",
                "tra usah serius",
            )
        )
        self.state.last_user_follow_through = (
            signal.intent in ("santai", "short", "closure", "capek")
            or signal.short_answer
            or chill_embedded
        )

    def analyze(self, text: str) -> dict[str, int]:
        text_lower = text.lower().strip()

        menu_score = self._score_menu(text_lower)
        chatbot_score = self._score_chatbot(text_lower)
        topic_escape_score = self._score_topic_escape(text_lower)
        word_count = len(text.split())
        repetition_score = self._score_repetition(text)
        question_count = text.count("?")
        offering_question = int(self._is_offering_question(text_lower))
        closing_question = int(text_lower.rstrip().endswith("?"))

        return {
            "menu_score": menu_score,
            "chatbot_score": chatbot_score,
            "topic_escape_score": topic_escape_score,
            "repetition_score": repetition_score,
            "question_count": question_count,
            "offering_question": offering_question,
            "closing_question": closing_question,
            "word_count": word_count,
        }

    def observe_response(self, text: str) -> dict[str, int]:
        """Hook 1 — called when model turn completes. Does not send steer."""
        analysis = self.analyze(text)

        if analysis["offering_question"] > 0:
            self.state.offering_question_streak += 1
        else:
            self.state.offering_question_streak = 0

        invitation_only = (
            analysis["menu_score"] == 1 and analysis["offering_question"] > 0
        )
        if invitation_only:
            self.state.invitation_streak += 1
        else:
            self.state.invitation_streak = 0

        if analysis["chatbot_score"] > 0:
            self.state.chatbot_score += analysis["chatbot_score"]
        else:
            self.state.chatbot_score = max(0, self.state.chatbot_score - 1)

        drifted = (
            analysis["chatbot_score"] > 0
            or analysis["menu_score"] > 0
            or analysis["topic_escape_score"] > 0
            or analysis["repetition_score"] > 0
        )
        if not drifted:
            self.state.natural_turns += 1
        else:
            self.state.natural_turns = 0

        if _REPEAT_OPENER.search(text.lower()):
            self.state.filler_opener_streak += 1
        else:
            self.state.filler_opener_streak = 0

        recent = list(self.state.recent_responses)
        recent.append(text.strip())
        self.state.recent_responses = recent[-self.RECENT_RESPONSES_MAX :]

        return analysis

    def decide(self, analysis: dict[str, int]) -> str | None:
        if self.state.last_user_follow_through:
            pushed = (
                analysis.get("offering_question", 0) > 0
                or (
                    analysis.get("closing_question", 0) > 0
                    and analysis.get("question_count", 0) >= 1
                )
            )
            if pushed:
                return DriftCategory.PUSH_FORWARD
        if analysis.get("repetition_score", 0) >= 3:
            return DriftCategory.REPETITION
        if self.state.filler_opener_streak >= 2:
            return DriftCategory.REPETITION
        if analysis.get("menu_score", 0) >= 3:
            return DriftCategory.MENU_LOOP
        if self.state.invitation_streak >= 2:
            return DriftCategory.QUESTION_LOOP
        if self.state.offering_question_streak >= 2:
            return DriftCategory.QUESTION_LOOP
        if (
            analysis.get("chatbot_score", 0) >= 3
            or self.state.chatbot_score >= 3
        ):
            return DriftCategory.CHATBOT
        if analysis.get("topic_escape_score", 0) >= 3:
            return DriftCategory.TOPIC_ESCAPE
        if analysis.get("word_count", 0) > 140:
            return DriftCategory.TOO_LONG
        return None

    def choose_steer(self, category: str) -> str:
        options = list(
            self.STEERS.get(category, self.STEERS[DriftCategory.MENU_LOOP])
        )
        available = [item for item in options if item not in self.state.recent_steers]
        if not available:
            available = options
        steer = available[0]
        recent = list(self.state.recent_steers)
        recent.append(steer)
        self.state.recent_steers = recent[-3:]
        return steer

    def can_steer(
        self,
        category: str | None = None,
        *,
        now: float | None = None,
    ) -> bool:
        if not self.deliver_steer:
            return False
        ts = now if now is not None else time.monotonic()
        if self.state.last_steer_time <= 0:
            return True
        elapsed = ts - self.state.last_steer_time
        if not category:
            return elapsed >= self.steer_cooldown
        if category != self.state.last_steer_category:
            return True
        return elapsed >= self._cooldown_for(category)

    def request_steer(
        self,
        category: str | None,
        *,
        now: float | None = None,
    ) -> None:
        """Queue steer only — never sends to Gemini."""
        if not category:
            return
        if not self.can_steer(category, now=now):
            return
        self.state.pending_steer = self.choose_steer(category)
        self.state.last_category = category

    def on_model_turn_complete(self, text: str, *, now: float | None = None) -> str | None:
        """Combined hook: observe → decide → request."""
        cleaned = text.strip()
        if not cleaned:
            return None
        analysis = self.observe_response(cleaned)
        category = self.decide(analysis)
        self.state.last_user_follow_through = False
        self.request_steer(category, now=now)
        return category

    def take_pending_steer(self) -> str | None:
        """Hook 2a — read queued steer at safe boundary."""
        steer = self.state.pending_steer
        self.state.pending_steer = None
        return steer

    def mark_steer_sent(self, *, now: float | None = None) -> None:
        """Hook 2b — after steer successfully delivered."""
        self.state.last_steer_time = now if now is not None else time.monotonic()
        self.state.last_steer_category = self.state.last_category
        self.state.offering_question_streak = 0
        self.state.invitation_streak = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatbot_score": self.state.chatbot_score,
            "offering_question_streak": self.state.offering_question_streak,
            "invitation_streak": self.state.invitation_streak,
            "natural_turns": self.state.natural_turns,
            "pending": bool(self.state.pending_steer),
            "last_category": self.state.last_category,
            "last_steer_category": self.state.last_steer_category,
            "filler_opener_streak": self.state.filler_opener_streak,
        }
