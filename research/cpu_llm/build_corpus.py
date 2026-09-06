#!/usr/bin/env python3
"""Ekstrak korpus teks Melayu Papua dari data JSON persona untuk latih LM kecil.

Usage:
  python research/cpu_llm/build_corpus.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "src/persona_ai/personality/data"
EXTRA_FILES = [ROOT / "database_papua.json"]
OUT = Path(__file__).resolve().parent / "corpus.txt"

# Kunci yang isinya metadata/tag, bukan kalimat alami.
SKIP_KEYS = frozenset({
    "keywords", "sources", "version", "usage_note", "description",
    "memory_rule", "keret", "tags", "id", "slug", "source", "meta",
})

# Baris yang jelas bukan bahasa alami.
_NOISE_RE = re.compile(r"^(https?://|[\w.]+\.(json|py|md)$)|^[A-Z_]{4,}$")


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_sentence(text: str) -> bool:
    """Terima string yang terlihat seperti kalimat, bukan token/kode."""
    if len(text) < 12 or len(text) > 400:
        return False
    if _NOISE_RE.search(text):
        return False
    if text.count(" ") < 2:
        return False
    # Buang string yang didominasi non-huruf.
    letters = sum(ch.isalpha() or ch.isspace() for ch in text)
    return letters / len(text) >= 0.75


def _walk(node: object, out: list[str], key: str | None = None) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, out, key=k)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out, key=key)
    elif isinstance(node, str):
        if key in SKIP_KEYS:
            return
        text = _clean(node)
        if _is_sentence(text):
            out.append(text)


def _glossary_lines(node: object, out: list[str]) -> None:
    """Ubah entri kamus {word, meaning} jadi kalimat latih."""
    if isinstance(node, dict):
        word = node.get("word") or node.get("kata")
        meaning = node.get("meaning") or node.get("arti")
        if isinstance(word, str) and isinstance(meaning, str):
            out.append(f"Kata '{_clean(word)}' artinya {_clean(meaning)}.")
        for v in node.values():
            _glossary_lines(v, out)
    elif isinstance(node, list):
        for item in node:
            _glossary_lines(item, out)


def main() -> None:
    files = sorted(DATA_DIR.glob("*.json")) + [p for p in EXTRA_FILES if p.is_file()]
    lines: list[str] = []
    per_file: list[tuple[str, int]] = []

    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  lewati {path.name}: {exc}")
            continue
        before = len(lines)
        _walk(data, lines)
        _glossary_lines(data, lines)
        per_file.append((path.name, len(lines) - before))

    # Dedup, pertahankan urutan.
    seen: set[str] = set()
    unique = [ln for ln in lines if not (ln in seen or seen.add(ln))]

    OUT.write_text("\n".join(unique) + "\n", encoding="utf-8")

    chars = sum(len(ln) for ln in unique)
    print(f"Sumber: {len(files)} file JSON")
    for name, count in per_file:
        print(f"  {name:<45} {count:>5} baris")
    print(f"\nBaris unik : {len(unique):,}")
    print(f"Karakter   : {chars:,}")
    print(f"Ditulis ke : {OUT}")


if __name__ == "__main__":
    main()
