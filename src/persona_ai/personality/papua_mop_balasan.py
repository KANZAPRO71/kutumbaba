"""Mop Balasan — Raja Mop menantang user cerita balik + apresiasi tertawa."""

from __future__ import annotations

import re

_FUNNY_USER_MARKERS = (
    "hahaha",
    "haha",
    "lucu",
    "ngakak",
    "ketawa",
    "mop",
    "mob",
    "lawak",
    "gorden",
    "lampu merah",
    "obet",
    "tinus",
    "tongko",
    "toki",
    "tipu",
    "polisi",
    "angkot",
    "nokia",
    "ular",
    "helm",
    "jebakan",
    "punchline",
    "mantap",
    "parah",
)


def mop_challenge_steering_text() -> str:
    return (
        "[STEER MOP BALASAN — suara natural, dialek Papua] "
        "Baru selesai cerita mop. Tantang user balas: "
        "Hahaha! Bagaimana, lucu toh? Sekarang sa mau tes ko dulu — "
        "coba ko kasi sa mop satu kah! Kalau tra lucu, sa tra mau jawab ko lagi ee, hahaha! "
        "Singkat, ceria, lalu diam dengar user."
    )


def is_user_funny_mop(transcript: str | None) -> bool:
    """Deteksi user bercerita mop/lucu — trigger laugh track apresiasi."""
    if not transcript or not transcript.strip():
        return False
    q = re.sub(r"\s+", " ", transcript.lower().strip())
    if len(q) < 12:
        return False
    hits = sum(1 for m in _FUNNY_USER_MARKERS if m in q)
    return hits >= 1 and (len(q.split()) >= 4 or "haha" in q)
