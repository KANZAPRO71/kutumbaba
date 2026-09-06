#!/usr/bin/env python3
"""Ubah JSON persona Papua jadi dataset instruksi (SFT / LoRA).

Usage:
  python research/lora/build_sft_dataset.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "src/persona_ai/personality/data"
OUT_DIR = Path(__file__).resolve().parent
TRAIN_PATH = OUT_DIR / "sft_train.jsonl"
VAL_PATH = OUT_DIR / "sft_val.jsonl"
STATS_PATH = OUT_DIR / "sft_stats.json"

KAMUS_Q = (
    "Apa arti {w}?",
    "{w} artinya apa?",
    "Ko tau '{w}' artinya apa kah?",
    "Arti kata {w} dong.",
)
KNOWLEDGE_Q = (
    "Cerita dikit tentang {t}.",
    "{t} itu apa?",
    "Ko tau soal {t} kah?",
)
MOP_Q = (
    "Kasi sa mop satu.",
    "Cerita lucu dong.",
    "Ko ada mop kah?",
    "Bikin sa ketawa.",
)
STYLE_Q = (
    "Bilang dalam bahasa Papua: {id_}",
    "Ganti ke Melayu Papua: {id_}",
)


def _ex(instruction: str, output: str, source: str) -> dict:
    inst = " ".join(instruction.split())
    out = " ".join(output.split())
    if len(inst) < 3 or len(out) < 8:
        return {}
    return {
        "instruction": inst,
        "output": out,
        "source": source,
        "messages": [
            {"role": "user", "content": inst},
            {"role": "assistant", "content": out},
        ],
    }


def _add(bucket: list[dict], item: dict) -> None:
    if item:
        bucket.append(item)


def from_kamus(data: dict) -> list[dict]:
    out: list[dict] = []
    for entry in data.get("entries") or []:
        word = (entry.get("word") or "").strip()
        meaning = (entry.get("meaning") or "").strip()
        if not word or not meaning:
            continue
        q = KAMUS_Q[hash(word) % len(KAMUS_Q)].format(w=word)
        _add(out, _ex(q, f"{word} artinya {meaning}.", "kamus"))
    return out


def from_knowledge(data: dict) -> list[dict]:
    out: list[dict] = []
    for fact in data.get("core_facts") or []:
        _add(out, _ex("Ko tau fakta Papua kah?", fact, "knowledge"))
    for topic in data.get("topics") or []:
        title = topic.get("title") or topic.get("id") or "Papua"
        facts = [f for f in (topic.get("facts") or []) if isinstance(f, str)]
        if not facts:
            continue
        q = KNOWLEDGE_Q[hash(title) % len(KNOWLEDGE_Q)].format(t=title)
        _add(out, _ex(q, " ".join(facts[:2]), "knowledge"))
        for fact in facts:
            _add(out, _ex(f"Tentang {title}, {fact.split()[0].lower()}…", fact, "knowledge"))
    return out


def from_mops(data: dict) -> list[dict]:
    out: list[dict] = []
    for cat in data.get("categories") or []:
        title = cat.get("title") or "mop"
        items = [i for i in (cat.get("items") or []) if isinstance(i, str)]
        for i, text in enumerate(items):
            q = MOP_Q[i % len(MOP_Q)]
            _add(out, _ex(q, text, "mop"))
            if len(text) > 24:
                _add(out, _ex(f"Kasi reaksi {title.lower()}.", text, "mop"))
    for mop in data.get("classic_mops") or []:
        text = mop.get("text") or ""
        title = mop.get("title") or "mop klasik"
        _add(out, _ex(f"Cerita mop {title}.", text, "mop_classic"))
    for mop in data.get("short_mops") or []:
        _add(out, _ex("Mop pendek dong.", mop.get("text") or "", "mop_short"))
    return out


def from_gaul(data: dict) -> list[dict]:
    out: list[dict] = []
    for word in data.get("words") or []:
        w = word.get("word") or ""
        meaning = word.get("meaning") or ""
        example = word.get("example") or ""
        _add(out, _ex(f"Apa arti {w}?", f"{w} artinya {meaning}.", "gaul"))
        if example:
            _add(out, _ex(f"Pakai '{w}' dalam kalimat.", example, "gaul"))
    for note in data.get("regional_notes") or []:
        _add(out, _ex("Yombex di Jayapura artinya apa?", note, "gaul"))
    tmpl = data.get("yombex_pamer_response") or ""
    if tmpl:
        _add(out, _ex("Sa baru beli hp mahal.", tmpl.replace("{item}", "hp baru"), "gaul"))
    for row in data.get("slang_barge_in") or []:
        triggers = row.get("user_triggers") or []
        resp = row.get("response") or ""
        if triggers and resp:
            _add(out, _ex(triggers[0], resp, "gaul"))
    return out


def from_dialect(data: dict) -> list[dict]:
    out: list[dict] = []
    guide = data.get("speaking_style_guide") or {}
    for examples in guide.values():
        if not isinstance(examples, list):
            continue
        for line in examples:
            if not isinstance(line, str) or "=" not in line:
                continue
            papua, _, indo = line.partition("=")
            papua = papua.strip().rstrip("(").strip()
            indo = indo.strip().strip("()").strip()
            if papua and indo:
                q = STYLE_Q[hash(indo) % len(STYLE_Q)].format(id_=indo)
                _add(out, _ex(q, papua, "dialect"))
    phrases = data.get("papua_phrases") or {}
    for bucket, lines in phrases.items():
        if not isinstance(lines, list):
            continue
        for line in lines:
            if isinstance(line, str) and len(line) > 12:
                _add(out, _ex("Ngobrol santai dong.", line, f"dialect_{bucket}"))
    vocab = data.get("vocabulary_core") or {}
    if isinstance(vocab, dict):
        for word, meaning in vocab.items():
            if isinstance(meaning, str):
                _add(out, _ex(f"Apa arti {word}?", f"{word} artinya {meaning}.", "dialect_vocab"))
    acks = data.get("companion_ack_papua") or {}
    if isinstance(acks, dict):
        for mood, lines in acks.items():
            if not isinstance(lines, list):
                continue
            for line in lines:
                if isinstance(line, str):
                    _add(out, _ex(f"Sa lagi {mood}.", line, "ack"))
    persona = data.get("companion_voice_persona") or {}
    for line in persona.get("speak_like") or []:
        if isinstance(line, str):
            _add(out, _ex("Ko siapa?", line, "persona"))
    for line in persona.get("opening_examples") or []:
        if isinstance(line, str):
            _add(out, _ex("Halo.", line, "persona"))
    return out


def from_music(data: dict) -> list[dict]:
    out: list[dict] = []
    for fact in data.get("overview") or []:
        _add(out, _ex("Cerita musik Papua dong.", fact, "music"))
    for song in data.get("songs") or []:
        title = song.get("title") or ""
        about = song.get("about") or ""
        artists = ", ".join(song.get("artists") or [])
        if title and about:
            reply = f"{title}" + (f" — {artists}. " if artists else ". ") + about
            _add(out, _ex(f"Lagu {title} itu lagu apa?", reply, "music"))
    for topic in data.get("topics") or []:
        title = topic.get("title") or "musik"
        facts = " ".join(topic.get("facts") or [])
        _add(out, _ex(f"Tentang {title}.", facts, "music"))
    return out


def from_pantun(data: dict) -> list[dict]:
    out: list[dict] = []
    for p in data.get("pantun_timur") or []:
        lines = p.get("lines") or []
        if lines:
            _add(out, _ex("Kasi sa pantun Papua.", "\n".join(lines), "pantun"))
    for g in data.get("gombalan") or []:
        text = g.get("text") or ""
        _add(out, _ex("Gombalan Papua dong.", text, "gombalan"))
    for tip in data.get("tips_cari_maitua") or []:
        _add(out, _ex("Tips cari maitua.", tip, "gombalan"))
    return out


def from_developer(data: dict) -> list[dict]:
    out: list[dict] = []
    for q in (
        "Siapa yang buat app ini?",
        "Siapa developer Papua AI?",
        "Ko siapa pembuatnya?",
        "Posman itu siapa?",
    ):
        for tmpl in data.get("response_templates") or []:
            _add(out, _ex(q, tmpl, "developer"))
    for fact in data.get("facts") or []:
        _add(out, _ex("Siapa pengembangnya?", fact, "developer"))
    return out


def from_biak(data: dict) -> list[dict]:
    out: list[dict] = []
    for row in data.get("coastal_phrases") or []:
        phrase = row.get("phrase") or ""
        meaning = row.get("meaning") or ""
        if phrase and meaning:
            _add(out, _ex(f"Apa arti {phrase}?", f"{phrase} artinya {meaning}.", "biak"))
    for row in data.get("conversation_templates") or []:
        user = row.get("user_example") or row.get("trigger") or ""
        hint = row.get("response_hint") or ""
        _add(out, _ex(user, hint, "biak"))
    for song in data.get("songs") or []:
        title = song.get("title") or ""
        about = song.get("about") or ""
        if title and about:
            _add(out, _ex(f"Lagu {title}?", f"{title}: {about}", "biak"))
    return out


def from_tabi(data: dict) -> list[dict]:
    out: list[dict] = []
    for row in data.get("conversation_templates") or []:
        _add(out, _ex(row.get("user_example") or "", row.get("response_hint") or "", "tabi"))
    for row in data.get("localization_phrases") or []:
        phrase = row.get("phrase") or ""
        meaning = row.get("meaning") or ""
        if phrase and meaning:
            _add(out, _ex(f"Apa arti {phrase}?", f"{phrase} artinya {meaning}.", "tabi"))
    for name, hint in (data.get("marga_locale_hints") or {}).items():
        if isinstance(hint, dict):
            loc = hint.get("lokasi") or hint.get("region") or ""
            kampung = hint.get("kampung") or ""
            _add(out, _ex(f"Marga {name} dari mana?", f"Marga {name} dari {kampung} ({loc}).", "tabi"))
    return out


def from_ondo(data: dict) -> list[dict]:
    out: list[dict] = []
    for line in data.get("character_lines") or []:
        _add(out, _ex("Bicara dengan wibawa adat.", line, "ondo"))
    for fact in data.get("adat_facts") or []:
        _add(out, _ex("Cerita adat ondoafi.", fact, "ondo"))
    for h in (data.get("salutations") or {}).get("honorifics") or []:
        term = h.get("term") or ""
        meaning = h.get("meaning") or ""
        if term and meaning:
            _add(out, _ex(f"Apa arti {term}?", f"{term} artinya {meaning}.", "ondo"))
    return out


def from_landmarks(data: dict) -> list[dict]:
    out: list[dict] = []
    for region in data.get("regions") or []:
        title = region.get("title") or region.get("id") or ""
        marks = ", ".join(region.get("landmarks") or [])
        if title and marks:
            _add(out, _ex(f"Tempat terkenal di {title}?", f"Di {title} ada {marks}.", "landmark"))
    return out


LOADERS = {
    "papua_kamus.json": from_kamus,
    "papua_knowledge.json": from_knowledge,
    "papua_mops.json": from_mops,
    "papua_gaul_jalanan.json": from_gaul,
    "papua_dialect_hf_samples.json": from_dialect,
    "papua_music.json": from_music,
    "papua_pantun_gombalan.json": from_pantun,
    "papua_developer_credit.json": from_developer,
    "papua_biak_wosvyak.json": from_biak,
    "papua_tabi_jayapura_sentani.json": from_tabi,
    "papua_ondo_wibawa.json": from_ondo,
    "papua_mop_landmarks.json": from_landmarks,
}


def _dedup(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for row in rows:
        key = (row["instruction"], row["output"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def main() -> None:
    rows: list[dict] = []
    per_source: dict[str, int] = {}
    for name, loader in LOADERS.items():
        path = DATA / name
        if not path.is_file():
            print(f"lewati {name}: tidak ada")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        chunk = loader(data)
        per_source[name] = len(chunk)
        rows.extend(chunk)

    rows = _dedup(rows)
    rng = random.Random(1337)
    rng.shuffle(rows)
    n_val = max(80, int(0.08 * len(rows)))
    val, train = rows[:n_val], rows[n_val:]

    def write_jsonl(path: Path, items: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    write_jsonl(TRAIN_PATH, train)
    write_jsonl(VAL_PATH, val)
    stats = {
        "train": len(train),
        "val": len(val),
        "total": len(rows),
        "per_file": per_source,
        "sources": sorted({r["source"] for r in rows}),
    }
    STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"train={len(train)}  val={len(val)}  total={len(rows)}")
    for name, count in per_source.items():
        print(f"  {name:<42} {count:>5}")
    print(f"Ditulis ke {TRAIN_PATH} dan {VAL_PATH}")


if __name__ == "__main__":
    main()
