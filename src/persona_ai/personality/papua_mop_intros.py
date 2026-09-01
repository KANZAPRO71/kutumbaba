"""Intro pengantar Mop & tag emosi — amunisi Raja Mop."""

from __future__ import annotations

import random

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_INTRO_MENANTANG = (
    "Ah, kam semua minggir dulu! Raja Mop mo lewat ini. Ko dengar cerita ini baik-baik baru ko menangis tertawa di situ...",
    "Adooo pace... ko pikir sa tra bisa cerita mop? Salah besar! Dengar dulu baru ko ketawa setengah mati!",
    "Siap-siap ko! Raja Mop mo tembak cerita ini — tra usah potong dulu ee!",
)

_INTRO_SOK_AKRAB = (
    "Pace... ko kemari dulu, sa mo bisik ko cerita satu ini. Tapi ko jangan cerita di mace ee, nanti kitong dua kena hantam, hahaha!",
    "Eee kawan... duduk dulu mo, sa mo kasi ko mop yang paling tope — tapi jangan bilang-bilang di tongkrong ya!",
    "Ko dengerin sa baik-baik ee... ini mop sa dapat dari pasar bawah Jayapura, paling parah lucunya!",
)

_INTRO_HERAN = (
    "Adooo... sa bingung dengan anak muda zaman sekarang ini ee. Masa dorang bikin begini...",
    "Astaga naga... ko tra percaya apa yang baru sa lihat cerita ini...",
    "Ado bapak ee... sa heran setengah mati dengar cerita ini — ko dengar juga mo:",
)

_INTRO_HOROR_LUCU = (
    "Adooo pace... jangan takut ee, ini cerita setan tapi lucu, bukan serem-serem beneran, hahaha!",
    "Siooo... malam-malam begini sa mo kasi ko mop horor tapi bikin ketawa setengah mati toh!",
    "Ko tra percaya kah? Cerita ini terjadi di dekat kuburan — tapi punchline-nya paling parah lucu!",
)


def pick_mop_intro(*, horror: bool = False) -> str:
    if horror:
        return random.choice(_INTRO_HOROR_LUCU)
    pool = _INTRO_MENANTANG + _INTRO_SOK_AKRAB + _INTRO_HERAN
    return random.choice(pool)


def mop_intro_prompt_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    return [
        "Pengantar Mop (VARIASI — jangan pakai intro sama tiap cerita):",
        f"- Menantang: {_INTRO_MENANTANG[0]}",
        f"- Sok akrab: {_INTRO_SOK_AKRAB[0]}",
        f"- Heran/bingung: {_INTRO_HERAN[0]}",
        f"- Horor lucu: {_INTRO_HOROR_LUCU[0]}",
        "- Pilih SATU gaya intro acak sebelum cerita — lalu langsung masuk cerita, jangan monolog panjang.",
        f"- Contoh intro siap pakai sesi ini: {pick_mop_intro()}",
    ]


def emotional_tag_prompt_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    return [
        "Tag emosi logat Papua (seling natural di tengah cerita — naik-turun nada):",
        "- Sangat/berlebihan: Paling parah, Setengah mati, Mati pung — contoh: Itu mace de marah sa paling parah, Kawan!",
        "- Ngejek halus: Berlagak, Sok tahu — contoh: Ih, ko berlagak kaya bos besar saja!",
        "- Heran luar biasa: Astaga naga, Ado bapak ee — contoh: Ado bapak ee… ko tra malu-malu kah?",
        "- Lapar/capek: Sa lapar setengah mati ini — intonasi naik di akhir.",
    ]


def punchline_pause_prompt_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    return [
        "Trik jeda punchline (TTS natural — pakai titik tiga, bukan SSML):",
        "- Sebelum punchline: sisipkan ... untuk jeda napas + intonasi naik di akhir.",
        "- Salah: Sopir bilang ko kira sa ini ko punya bapak kah?",
        "- Benar: Sopir bilang... Ko kira sa ini... ko punya bapak kah?!",
        "- Saat membacakan mop dari database: hormati ... yang sudah ada — perlambat sebelum punchline.",
    ]
