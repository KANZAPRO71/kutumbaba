"""Tokenizer level-karakter.

Dipilih karena korpus kecil (~100k karakter): BPE butuh data jauh lebih banyak
untuk menghasilkan subword yang berguna, sedangkan char-level langsung bekerja
dan menjaga vocab tetap kecil (~90 simbol).
"""

from __future__ import annotations

import json
from pathlib import Path


class CharTokenizer:
    def __init__(self, chars: list[str]) -> None:
        self.chars = chars
        self.stoi = {ch: i for i, ch in enumerate(chars)}
        self.itos = dict(enumerate(chars))

    @property
    def vocab_size(self) -> int:
        return len(self.chars)

    @classmethod
    def from_text(cls, text: str) -> "CharTokenizer":
        return cls(sorted(set(text)))

    def encode(self, text: str) -> list[int]:
        # Karakter di luar vocab dilewati agar prompt bebas tidak menggagalkan run.
        return [self.stoi[ch] for ch in text if ch in self.stoi]

    def decode(self, ids: list[int]) -> str:
        return "".join(self.itos[i] for i in ids)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps({"chars": self.chars}, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "CharTokenizer":
        return cls(json.loads(path.read_text(encoding="utf-8"))["chars"])
