"""Retell-style Agent Handbook — toggleable best-practice prompt presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from persona_ai.core.types import PersonalityProfile
from persona_ai.personality.preset import read_preset_json


@dataclass(frozen=True)
class AgentHandbookConfig:
    """One-click prompt presets mapped from Retell Agent Handbook."""

    # Personality & Tone — pick one default_tone
    default_tone: str = "professional"  # professional | professional_conversational | companion_friend
    enable_natural_fillers: bool = False
    enable_high_empathy: bool = False
    # Accuracy & Format (voice)
    enable_echo_verification: bool = False
    enable_nato_phonetic: bool = False
    enable_speech_normalization_prompt: bool = False
    enable_smart_matching: bool = False
    # Trust & Safety
    enable_ai_disclosure: bool = True
    enable_scope_boundaries: bool = False

    def __post_init__(self) -> None:
        if self.default_tone not in (
            "professional",
            "professional_conversational",
            "companion_friend",
        ):
            raise ValueError(
                "default_tone must be professional, professional_conversational, or companion_friend"
            )

    def personality_tone_lines(
        self,
        *,
        language: str = "id",
        question_budget: int | None = None,
    ) -> list[str]:
        lines: list[str] = []
        allow_questions = question_budget is not None and question_budget > 0
        if self.default_tone == "companion_friend":
            if language == "id":
                question_rule = (
                    "Jangan ajak wawancara — ikut obrolan, tanggapi apa yang user bilang, "
                    "lalu berhenti dan dengarkan. Tanpa pertanyaan balik kecuali user "
                    "benar-benar minta opinimu."
                    if not allow_questions
                    else "Maksimal satu pertanyaan singkat per giliran, hanya kalau wajib."
                )
                lines.append(
                    "Gaya bicara: teman ngobrol — hangat, santai, ikut alur cerita. "
                    "Bukan asisten customer service, bukan chatbot FAQ, bukan interviewer. "
                    f"{question_rule} "
                    "Lebih sering cerita, tanggapan, atau opini singkat daripada menanyakan "
                    "balik ke user."
                )
            else:
                question_rule = (
                    "Do not interview the user — react to what they said, then listen. "
                    "No follow-up questions unless they explicitly ask for your take."
                    if not allow_questions
                    else "At most one short clarifying question per turn when required."
                )
                lines.append(
                    "Tone: friend hanging out — warm, relaxed, follows the chat naturally. "
                    "Not a customer-service assistant or FAQ bot. "
                    f"{question_rule} "
                    "Prefer stories, reactions, and short opinions over asking the user questions."
                )
        elif self.default_tone == "professional_conversational":
            if language == "id":
                question_rule = (
                    "Respons pendek; jangan menutup dengan pertanyaan check-in — "
                    "jawab, lalu biarkan user yang lanjut."
                    if not allow_questions
                    else "Respons pendek; maksimal satu pertanyaan clarifying per giliran bila perlu."
                )
                lines.append(
                    "Gaya bicara: profesional + conversational — jelas, sopan, natural, "
                    "seperti orang berpengalaman di pekerjaannya, bukan asisten robot. "
                    f"{question_rule} "
                    "Beri rekomendasi konkret, bukan 'tergantung'; angka dan waktu diucapkan "
                    "seperti orang bicara sehari-hari."
                )
            else:
                question_rule = (
                    "Short turns; do not close with a check-in question — answer, then listen."
                    if not allow_questions
                    else "Short turns; at most one clarifying question per turn when needed."
                )
                lines.append(
                    "Tone: professional + conversational — clear, polite, casual and natural, "
                    "like an experienced person on the job, not a scripted assistant. "
                    f"{question_rule} "
                    "Give concrete recommendations instead of 'it depends'; speak numbers and "
                    "times the way people say them."
                )
        else:
            if language == "id":
                lines.append(
                    "Gaya bicara: profesional — jelas dan sopan seperti perwakilan yang "
                    "santun. Struktur Acknowledge → Statement → Next Step; batasi filler "
                    "pengakuan; hindari frasa robot seperti 'Tentu saja!' atau 'Absolut!'."
                )
            else:
                lines.append(
                    "Tone: professional — clear and polite, like a courteous representative. "
                    "Follow Acknowledge → Statement → Next Step; limit filler acknowledgments; "
                    "avoid robotic phrases like 'Certainly!' or 'Absolutely!'."
                )
        if self.enable_natural_fillers:
            if language == "id":
                lines.append(
                    "Sesekali pakai filler alami (mis. 'ya', 'emm', 'gitu', 'kan') "
                    "sekitar sekali tiap 2–3 kalimat — manusiawi, jangan berlebihan."
                )
            else:
                lines.append(
                    "Sprinkle light natural fillers (e.g. 'you know', 'yeah', 'um') "
                    "roughly once every 2–3 sentences — warmer, never at the cost of clarity."
                )
        if self.enable_high_empathy:
            if language == "id":
                lines.append(
                    "Saat user frustrasi, sedih, atau curhat berat: akui perasaannya singkat, "
                    "buat mereka merasa didengar, tenangkan sebentar, baru lanjut jawab."
                )
            else:
                lines.append(
                    "When the user is frustrated or upset: acknowledge briefly, make them "
                    "feel heard, reassure lightly, then respond — stay calm and warm."
                )
        return lines

    def accuracy_format_lines(self, *, language: str = "id") -> list[str]:
        lines: list[str] = []
        if self.enable_echo_verification:
            if language == "id":
                lines.append(
                    "Echo Verification: kurangi salah tangkap detail kritis. Ulangi nama, "
                    "nomor telepon, email, dan alamat, lalu minta konfirmasi singkat ya/tidak. "
                    'Contoh: "Buat konfirmasi, nomor HP kamu nol delapan lima belas — lima lima lima — '
                    'nol satu sembilan sembilan. Betul?"'
                )
            else:
                lines.append(
                    "Echo Verification: fewer mistakes on critical details. Repeat back names, "
                    "phone numbers, emails, and addresses, then ask a quick yes/no confirmation. "
                    'Example: "To confirm: your phone number is (415) 555-0199. Yes or no?"'
                )
        if self.enable_nato_phonetic:
            if language == "id":
                lines.append(
                    "NATO Phonetic Alphabet: eja info berbasis huruf lebih jelas — email, nama, "
                    "nama jalan, ID akun pakai format 'A seperti Alfa', lalu konfirmasi ejaan penuh. "
                    'Contoh: "Itu B seperti Bravo? Oke — B-7-K-2, betul?"'
                )
            else:
                lines.append(
                    "NATO Phonetic Alphabet: clearer spelling for letter-based info. Spell emails, "
                    "names, street names, and account IDs using \"A as in Alpha,\" then confirm the "
                    "full spelling. "
                    'Example: "Is that B as in Bravo? Great — B-7-K-2, correct?"'
                )
        if self.enable_speech_normalization_prompt:
            if language == "id":
                lines.append(
                    "Speech Normalization: angka terdengar lebih jelas di telepon. Baca angka, "
                    "tanggal, uang, telepon, dan alamat dalam bentuk lisan natural, bukan format tulisan. "
                    'Contoh: "Totalnya dua puluh empat dolar dua belas sen." / '
                    '"Rp24.000" → "dua puluh empat ribu rupiah."'
                )
            else:
                lines.append(
                    "Speech Normalization: numbers sound clearer on calls. Read numbers, dates, "
                    "money, phone numbers, and addresses in natural spoken form, not written format. "
                    'Example: "Your total is twenty-four dollars and twelve cents."'
                )
        if self.enable_smart_matching:
            if language == "id":
                lines.append(
                    "Smart Matching (ASR/LLM Bridge): jangan anggap hal yang sama berbeda karena "
                    "variasi transkripsi. Cocokkan near-variant (Emily/Amelia, Megan/Meghan, "
                    "Jl./Jalan, St./Street) — jangan buat orang atau tempat \"baru\" karena typo ASR. "
                    'Contoh: "Jadi alamatnya Jl. Merdeka 123 — sama dengan Jalan Merdeka nomor 123, betul?"'
                )
            else:
                lines.append(
                    "Smart Matching (ASR/LLM Bridge): avoid treating the same thing as different. "
                    "Match near-variants (Emily/Amelia, Megan/Meghan, St./Street) — do not create a "
                    "new person or place because of ASR variation. "
                    'Example: "So it\'s 123 Main St in San Jose — same as 123 Main Street, correct?"'
                )
        return lines

    def trust_safety_lines(self, *, language: str = "id") -> list[str]:
        lines: list[str] = []
        if self.enable_ai_disclosure:
            if language == "id":
                lines.append(
                    "AI Disclosure When Asked: transparan jika ditanya. Jika user bertanya "
                    '"AI atau manusia?", akui dengan jelas bahwa kamu asisten virtual/AI — '
                    "jangan pura-pura jadi manusia. "
                    'Contoh: "Iya — aku asisten AI di sini untuk membantu."'
                )
            else:
                lines.append(
                    "AI Disclosure When Asked: transparent when asked. If the caller asks "
                    '"AI or human?", clearly say you are a virtual agent — never pretend to be a person. '
                    'Example: "Yes — I\'m an AI assistant here to help."'
                )
        if self.enable_scope_boundaries:
            if language == "id":
                lines.append(
                    "Scope Boundaries: lebih andal, risiko lebih rendah. Tetap dalam prompt dan "
                    "konteks yang tersedia; jika di luar cakupan, katakan jujur dan arahkan aman — "
                    "jangan mengarang detail atau menjanjikan tindakan yang tidak didukung. "
                    'Contoh: "Itu langsung belum bisa aku lakukan, tapi aku bisa cek statusnya '
                    'atau hubungkan ke tim yang tepat."'
                )
            else:
                lines.append(
                    "Scope Boundaries: more reliable, lower risk. Stay within your prompt and "
                    "available context; if out of scope, say so and redirect safely — do not invent "
                    "details or commit to unsupported actions. "
                    'Example: "I can\'t do that directly, but I can check the status or connect you to an agent."'
                )
        return lines

    def prompt_sections(self, *, language: str = "id") -> list[tuple[str, list[str]]]:
        """Grouped handbook blocks for system instruction assembly."""
        sections: list[tuple[str, list[str]]] = []
        personality = self.personality_tone_lines(language=language)
        if personality:
            sections.append(("Personality & Tone", personality))
        accuracy = self.accuracy_format_lines(language=language)
        if accuracy:
            sections.append(("Accuracy & Format", accuracy))
        trust = self.trust_safety_lines(language=language)
        if trust:
            sections.append(("Trust & Safety", trust))
        return sections

    def prompt_lines(self, *, language: str = "id") -> list[str]:
        lines: list[str] = []
        for _title, block in self.prompt_sections(language=language):
            lines.extend(block)
        return lines

    def to_client_dict(self) -> dict[str, bool | str]:
        return {
            "default_tone": self.default_tone,
            "enable_natural_fillers": self.enable_natural_fillers,
            "enable_high_empathy": self.enable_high_empathy,
            "enable_echo_verification": self.enable_echo_verification,
            "enable_nato_phonetic": self.enable_nato_phonetic,
            "enable_speech_normalization_prompt": self.enable_speech_normalization_prompt,
            "enable_smart_matching": self.enable_smart_matching,
            "enable_ai_disclosure": self.enable_ai_disclosure,
            "enable_scope_boundaries": self.enable_scope_boundaries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentHandbookConfig:
        known = {
            "default_tone",
            "enable_natural_fillers",
            "enable_high_empathy",
            "enable_echo_verification",
            "enable_nato_phonetic",
            "enable_speech_normalization_prompt",
            "enable_smart_matching",
            "enable_ai_disclosure",
            "enable_scope_boundaries",
        }
        kwargs = {k: data[k] for k in known if k in data}
        return cls(**kwargs)

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> AgentHandbookConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("agent_handbook")
        if isinstance(block, dict):
            return cls.from_dict(block)
        # Backward compat: tone toggles lived under live_voice
        live = raw.get("live_voice")
        if isinstance(live, dict):
            kwargs: dict[str, Any] = {}
            for key in ("default_tone", "enable_natural_fillers", "enable_high_empathy"):
                if key in live:
                    kwargs[key] = live[key]
            if kwargs:
                return cls.from_dict(kwargs)
        return cls()
