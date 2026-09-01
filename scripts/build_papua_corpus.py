#!/usr/bin/env python3
"""Bangun korpus logat Papua bertahap: Warungfiksi, HF, frasa per kota.

Usage:
  python scripts/build_papua_corpus.py
  python scripts/build_papua_corpus.py --skip-hf
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/persona_ai/personality/data/papua_dialect_hf_samples.json"

# Parsed from warungfiksi.net/tiga-sandera-terakhir/kamus-papua.html
WARUNGFIKSI_ENTRIES: list[tuple[str, str]] = [
    ("ade", "adik"),
    ("adoh", "aduh"),
    ("afkir", "kadaluarsa"),
    ("babingung", "bingung/pusing"),
    ("baek", "baik"),
    ("bale", "balik"),
    ("bombe", "ngambek"),
    ("baru", "lho/penegas (ko laki-laki baru?)"),
    ("daranya", "ungkapan kaget/heran"),
    ("de", "dia"),
    ("deng", "dengan"),
    ("dorang", "mereka"),
    ("epen", "emang penting? (santai/cuek)"),
    ("farek", "tidak peduli"),
    ("istigafar", "astaga"),
    ("iyo", "iya"),
    ("jang", "jangan"),
    ("kabong", "kebun"),
    ("kah", "kah? / dong (jang marah kah)"),
    ("kaka", "kakak"),
    ("kamareng", "kemarin"),
    ("kamari", "kemari"),
    ("kamong", "kalian"),
    ("kampong", "kampung"),
    ("kapala", "kepala"),
    ("kas", "kasih/beri (kas tau = beritahu)"),
    ("katong", "kita"),
    ("kio", "dong/lah"),
    ("ko", "kamu"),
    ("komen", "orang asli Papua"),
    ("konci_rekeng", "akhirnya"),
    ("mace", "ibu"),
    ("maitua", "istri/pacar wanita"),
    ("mamayo", "ya ampun (kaget/simpati)"),
    ("mangarti", "mengerti"),
    ("mangkali", "barangkali"),
    ("manise", "manis/indah"),
    ("mar", "mari / tapi"),
    ("maraju", "merajuk/ngambek"),
    ("maske", "meskipun"),
    ("mo", "mau / kok (penegas)"),
    ("nan", "nanti"),
    ("nona", "sapaan gadis"),
    ("pace", "bapak/laki-laki"),
    ("paitua", "suami/pacar lelaki"),
    ("paskali", "sangat/sekali"),
    ("pica", "pecah (panas pica = panas sekali)"),
    ("pi", "pergi"),
    ("polo", "peluk"),
    ("pu", "punya (sa pu rumah)"),
    ("sa", "saya/aku"),
    ("sono", "nyenyak tidur"),
    ("su", "sudah"),
    ("tafiaro", "jalan-jalan"),
    ("tete", "kakek"),
    ("tra", "tidak"),
    ("to", "kan? (sa su bilang to?)"),
    ("tu", "itu"),
    ("yombex", "iya"),
    ("tempo", "cepat"),
    ("kapala_batu", "keras kepala"),
    ("bagitu", "begitu"),
    ("sonde", "bukan"),
    ("cupen_toh", "istirahat dulu / balasan santai"),
    ("jeskon", "ungkapan kaget/kagum"),
    ("yoksna", "ungkapan kaget/heran"),
    ("loyo", "malas/bete"),
    ("babingung", "bingung"),
    ("macang", "macam/seperti"),
    ("maniso", "sibuk/repot"),
    ("manyau", "menyahut"),
    ("koliling", "keliling"),
    ("karja", "kerja"),
    ("kanes", "kenes/genit (ringan)"),
    ("trabaik", "jelek"),
    ("tralaku", "jelek"),
    ("trapapa", "tidak apa-apa"),
    ("tramau", "tidak mau"),
    ("skali", "sekali/sangat"),
    ("lai", "lagi"),
    ("eee", "eee panjang / bujukan (kas tau sa eee)"),
    ("bar", "baru (penegas)"),
]

_COMPANION_EXCLUDE = frozenset({
    "cuki", "gae", "gosi", "bangkret", "cukimai", "kaliabo", "konto", "noge",
    "gamas", "gatotel", "napo", "yakis", "yaklep", "hop", "hantam", "pukol",
    "abuti", "kewel", "ulhat",
})

_COMPANION_EXCLUDE_RE = re.compile(
    r"makian|bersetubuh|alat kelamin|jalang|pantat|bokong|minum miras|miras",
    re.I,
)

REGIONAL_PHRASES: dict[str, list[str]] = {
    "jayapura": [
        "Ko dari Entrop kah?",
        "Sa ada di Abepura, ko mo jemput sa e?",
        "Mo ke Expo kah malam ini?",
        "Panas picah di Jayapura hari ini.",
        "Sa pu rumah dekat Stadion Mandala.",
        "Ko tra pi ke Hamadi kah?",
        "Torang ketemu di Entrop mo.",
        "Sa dari Sentani, ko dari mana?",
        "Angkot su penuh, kitong jalan kaki aja.",
        "Ko ada lihat pasar Phara kah?",
    ],
    "merauke": [
        "Ko mo pi pasar kah sore ini?",
        "Bar ko su makan, kitong jalan mo.",
        "Sa su bilang toh, jang lupa bale.",
        "Ko tra mau cerita kah?",
        "Dong su datang baru, ko lihat toh?",
        "Mo ke Pantai Tanah Merah kah?",
        "Sa tunggu ko di depan losmen e.",
        "Kah ko su siap?",
        "Trapapa ko, cerita aja mo.",
        "Merauke panas skali, ko minum air dulu.",
    ],
    "manokwari": [
        "Sa kasi tau ko dulu sebelum kitong pi.",
        "Sa bikin de senang deng cerita tu.",
        "Ko pergi ambil sa pu jaket di rumah.",
        "Nan sa kasi biar ko istirahat.",
        "Kitong tra tau, tapi sa mo dengar ko dulu.",
        "De bilang de su oke, iyo toh?",
        "Sa turun beli makan sebentar mo.",
        "Ko mo makan di pantai Mansinam kah?",
        "Manokwari angin sejuk skali malam ini.",
        "Sa pu keluarga ada di Manokwari.",
    ],
}


def _companion_vocab(entries: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for word, gloss in entries:
        key = word.strip().lower().replace(" ", "_")
        if key in _COMPANION_EXCLUDE or key in out:
            continue
        if _COMPANION_EXCLUDE_RE.search(gloss):
            continue
        if "(dialek biak)" in gloss.lower() and key not in {"iyo", "farek", "mamayo"}:
            continue
        out[key] = gloss
    return out


def _extract_short_papua_phrases(text: str) -> list[str]:
    """Ambil frasa pendek Papuan dari blob HF (quoted atau sebelum '=')."""
    found: list[str] = []
    for match in re.finditer(r"'([^']{4,90})'", text):
        phrase = match.group(1).strip()
        if any(k in phrase.lower() for k in ("sa ", " ko", "tra ", " su ", " jang", " kah")):
            if phrase not in found:
                found.append(phrase)
    for chunk in re.split(r"[;,]", text):
        if "=" not in chunk:
            continue
        left = chunk.split("=", 1)[0].strip()
        for part in re.split(r"/", left):
            part = part.strip().strip("'\"")
            if 4 <= len(part) <= 80 and re.search(r"\b(sa|ko|tra|su|jang|kah|mo|toh)\b", part, re.I):
                if part not in found:
                    found.append(part)
    return found


def _collect_hf_health() -> list[str]:
    from datasets import load_dataset

    ds = load_dataset("emylton/indonesian-regional-languages-health", split="train")
    phrases: list[str] = []
    for row in ds:
        instruction = row.get("instruction") or ""
        output = (row.get("output") or "").strip()
        if "Melayu Papua" not in instruction and "Melayu Papua" not in output:
            continue
        for raw in _extract_short_papua_phrases(output):
            text = raw.replace("Beta ", "Sa ").replace("beta ", "sa ")
            if text not in phrases:
                phrases.append(text)
    # Frasa companion dari referensi HF (kurasi manual)
    curated = [
        "Tra enak badan kah ko?",
        "Su mulai sakit dari kapan?",
        "Ada keluhan lain kah?",
        "Su minum obat apa?",
        "Jang makan yang pedas-pedas mo.",
        "Harus banyak minum air putih toh.",
        "Ko tenang dulu, sa dengerin.",
        "Tra ada tenaga — ko istirahat dulu mo.",
        "Badan panas kah ko?",
        "Ko su cape skali, minum air dulu.",
    ]
    for line in curated:
        if line not in phrases:
            phrases.append(line)
    return phrases


def _merge_phrases(existing: dict, *, health: list[str]) -> dict:
    merged = dict(existing)
    if health:
        merged["hf_melayu_papua_health"] = health
    for city, lines in REGIONAL_PHRASES.items():
        key = f"regional_{city}"
        prior = merged.get(key, [])
        seen = set(prior)
        bucket = list(prior)
        for line in lines:
            if line not in seen:
                bucket.append(line)
                seen.add(line)
        merged[key] = bucket
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Build staged Papua dialect corpus")
    parser.add_argument("--skip-hf", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    existing: dict = {}
    if args.out.is_file():
        existing = json.loads(args.out.read_text(encoding="utf-8"))

    warungfiksi = _companion_vocab(WARUNGFIKSI_ENTRIES)
    health: list[str] = []
    if not args.skip_hf:
        try:
            health = _collect_hf_health()
        except Exception as exc:
            print(f"HF skip ({exc}) — jalankan: pip install datasets")

    payload = dict(existing)
    payload["vocabulary_warungfiksi"] = warungfiksi
    payload["vocabulary_core"] = {**existing.get("vocabulary_core", {}), **warungfiksi}

    sources = list(payload.get("sources") or [])
    for src in (
        "Warungfiksi A-Z (Tiga Sandera Terakhir) — filter companion",
        "emylton/indonesian-regional-languages-health (HF)",
        "Frasa regional: Jayapura, Merauke, Manokwari",
    ):
        if src not in sources:
            sources.append(src)
    payload["sources"] = sources

    payload["papua_phrases"] = _merge_phrases(
        existing.get("papua_phrases") or {},
        health=health,
    )

    if health:
        payload["melayu_papua_health_meta"] = {
            "count": len(health),
            "note": "Frasa kesehatan HF; beta→sa jika ada.",
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    phrase_total = sum(
        len(v) for v in payload["papua_phrases"].values() if isinstance(v, list)
    )
    print(
        f"Wrote {args.out}\n"
        f"  warungfiksi vocab: {len(warungfiksi)}\n"
        f"  hf health phrases: {len(health)}\n"
        f"  regional cities: {len(REGIONAL_PHRASES)}\n"
        f"  phrase buckets total lines: {phrase_total}"
    )


if __name__ == "__main__":
    main()
