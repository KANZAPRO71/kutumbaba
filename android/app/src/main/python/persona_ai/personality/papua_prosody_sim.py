"""Simulator logat Papua — tempo, pitch, frekuensi mop untuk UI HP."""

from __future__ import annotations

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect


def normalize_prosody_sim(raw: dict | None) -> dict[str, float]:
    data = raw if isinstance(raw, dict) else {}
    tempo = float(data.get("speech_tempo", 1.0))
    pitch = float(data.get("tone_pitch", 1.0))
    mop_freq = float(data.get("mop_frequency", 0.6))
    return {
        "speech_tempo": max(0.5, min(1.5, tempo)),
        "tone_pitch": max(0.5, min(1.5, pitch)),
        "mop_frequency": max(0.0, min(1.0, mop_freq)),
    }


def prosody_sim_prompt_lines(
    dialect: str | None,
    sim: dict | None,
) -> list[str]:
    if not is_papua_dialect(dialect):
        return []
    cfg = normalize_prosody_sim(sim)
    tempo = cfg["speech_tempo"]
    pitch = cfg["tone_pitch"]
    mop = cfg["mop_frequency"]

    tempo_hint = "normal"
    if tempo >= 1.15:
        tempo_hint = "agak cepat & enerjik"
    elif tempo <= 0.85:
        tempo_hint = "pelan & santai"

    pitch_hint = "nada natural"
    if pitch >= 1.15:
        pitch_hint = "nada lebih tinggi & ceria"
    elif pitch <= 0.85:
        pitch_hint = "nada lebih rendah & hangat"

    mop_hint = "sesekali"
    if mop >= 0.75:
        mop_hint = "sering (Raja Mop aktif)"
    elif mop <= 0.35:
        mop_hint = "jarang — fokus obrolan dulu"

    return [
        "SIMULATOR LOGAT PAPUA (dari pengatur HP user):",
        f"- Tempo bicara: {tempo_hint} (skala {tempo:.2f}).",
        f"- Ayunan nada: {pitch_hint} (skala {pitch:.2f}).",
        f"- Frekuensi mop: tawarin/ceritakan mop {mop_hint} (skala {mop:.2f}).",
    ]
