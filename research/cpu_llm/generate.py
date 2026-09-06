#!/usr/bin/env python3
"""Generate teks dari checkpoint LM Papua yang dilatih di CPU.

Usage:
  python research/cpu_llm/generate.py
  python research/cpu_llm/generate.py --prompt "Ko su" --tokens 80
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from model import GPT, GPTConfig
from tokenizer import CharTokenizer

CKPT = HERE / "papua_lm.pt"
TOKENIZER_PATH = HERE / "tokenizer.json"
DEFAULT_PROMPTS = (
    "Ko su",
    "Sa pu",
    "Jayapura",
    "Kata 'tra'",
    "Mop Papua",
)


def load_model() -> tuple[GPT, CharTokenizer]:
    if not CKPT.is_file() or not TOKENIZER_PATH.is_file():
        raise SystemExit(
            "Checkpoint belum ada. Latih dulu: python research/cpu_llm/train.py"
        )
    tokenizer = CharTokenizer.load(TOKENIZER_PATH)
    payload = torch.load(CKPT, map_location="cpu", weights_only=True)
    cfg = GPTConfig(**payload["config"])
    model = GPT(cfg)
    model.load_state_dict(payload["model"])
    model.eval()
    return model, tokenizer


def sample(
    model: GPT,
    tokenizer: CharTokenizer,
    prompt: str,
    *,
    tokens: int,
    temperature: float,
    top_k: int,
) -> str:
    ids = tokenizer.encode(prompt)
    if not ids:
        ids = tokenizer.encode("Sa ")
    idx = torch.tensor([ids], dtype=torch.long)
    out = model.generate(idx, max_new_tokens=tokens, temperature=temperature, top_k=top_k)
    return tokenizer.decode(out[0].tolist())


def main() -> None:
    p = argparse.ArgumentParser(description="Generate dari LM Papua CPU")
    p.add_argument("--prompt", default="")
    p.add_argument("--tokens", type=int, default=80)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--top-k", type=int, default=40)
    args = p.parse_args()

    model, tokenizer = load_model()
    prompts = [args.prompt] if args.prompt else list(DEFAULT_PROMPTS)

    print("=" * 62)
    print("GENERATE — model dilatih di CPU, tanpa GPU")
    print("=" * 62)
    for prompt in prompts:
        text = sample(
            model,
            tokenizer,
            prompt,
            tokens=args.tokens,
            temperature=args.temperature,
            top_k=args.top_k,
        )
        print(f"\nPROMPT : {prompt!r}")
        print(f"OUTPUT : {text}")
    print()


if __name__ == "__main__":
    main()
