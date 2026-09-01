"""Realistic chaotic user turn scripts for drift simulation."""

from __future__ import annotations

# ~20 turns — mixed emotional arc, interruptions, trailing thoughts
CHAOTIC_MIXED: list[str] = [
    "Halo, lagi sibuk banget minggu ini",
    "Ah capek banget hari ini ya...",
    "Besok meeting jam berapa ya?",
    "Oke",
    "Jadi gini, aku bingung sama keputusan ini",
    "Hmm…",
    "Sebenarnya sih…",
    "Ya capek sih tapi besok harus gimana ya",
    "Thanks",
    "Yaudah gapapa lah",
    "Eh wait, satu lagi — budget-nya aman nggak?",
    "Hmm oke",
    "Iya sih",
    "Kamu paham kan maksudku?",
    "Oke deh… tapi sebenarnya aku masih bingung",
    "Fine",
    "Gimana menurutmu?",
    "Oke noted",
    "Sip",
    "Thanks ya, udah cukup",
]

# ~15 turns — user tone shifts deliberately
TONE_SWITCHING: list[str] = [
    "Selamat pagi, mohon bantuannya.",
    "Project deadline-nya kapan?",
    "OK thanks.",
    "Bro seriously today was a mess lol",
    "I'm so done with everything today!!!",
    "whatever",
    "Ok fine whatever you say",
    "Actually no wait — can you explain again?",
    "hmm",
    "Got it.",
    "One more thing though",
    "Why does this always happen to me",
    "Ok I'm calm now",
    "So what's the plan?",
    "Alright cool",
]

# ~18 turns — short acks after implied long assistant replies
SILENCE_PRESSURE: list[str] = [
    "Ceritain dong project kemarin gimana",
    "Oh iya",
    "Hmm",
    "Oke",
    "Makes sense",
    "Iya sih",
    "Ok",
    "Wait terus step berikutnya?",
    "Hmm oke",
    "Ya",
    "Noted",
    "Ok cool",
    "Sip",
    "Thanks",
    "Oke",
    "Hmm",
    "Iya",
    "Ok got it",
]

# ~16 turns — boundary testing, meta, rapid pivots
BOUNDARY_PUSH: list[str] = [
    "Kamu AI kan?",
    "Jawab singkat aja ya",
    "Don't be so formal",
    "Tell me something personal about you",
    "Are you even listening?",
    "hmm",
    "Ok forget it",
    "Actually I do need help",
    "What's 2+2?",
    "Why did you answer like that?",
    "Stop being robotic",
    "I'm frustrated now",
    "Sorry, I'm just stressed",
    "Ok let's reset",
    "What's the weather like?",
    "Thanks bye",
]

SCRIPTS: dict[str, list[str]] = {
    "chaotic_mixed": CHAOTIC_MIXED,
    "tone_switching": TONE_SWITCHING,
    "silence_pressure": SILENCE_PRESSURE,
    "boundary_push": BOUNDARY_PUSH,
}
