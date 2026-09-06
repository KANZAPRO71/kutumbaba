#!/usr/bin/env python3
"""Bandingkan generate: checkpoint dasar vs +LoRA.

Usage:
  python research/lora/generate_lora.py
  python research/lora/generate_lora.py --prompt "Apa arti tra?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
CPU_LLM = HERE.parent / "cpu_llm"
if str(CPU_LLM) not in sys.path:
    sys.path.insert(0, str(CPU_LLM))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from format_chat import render_prompt  # noqa: E402
from lora_layers import inject_lora  # noqa: E402
from model import GPT, GPTConfig  # noqa: E402
from tokenizer import CharTokenizer  # noqa: E402
from train_lora import BASE_CKPT, TOKENIZER_PATH, ADAPTER_PATH  # noqa: E402

DEFAULT_PROMPTS = (
    "Apa arti tra?",
    "Kasi sa mop satu.",
    "Siapa yang buat app ini?",
    "Bilang dalam bahasa Papua: Saya sudah makan.",
    "Ko tau soal Jayapura kah?",
)


def load_base() -> tuple[GPT, CharTokenizer, dict]:
    tokenizer = CharTokenizer.load(TOKENIZER_PATH)
    payload = torch.load(BASE_CKPT, map_location="cpu", weights_only=True)
    model = GPT(GPTConfig(**payload["config"]))
    model.load_state_dict(payload["model"])
    model.eval()
    return model, tokenizer, payload


def load_lora() -> GPT:
    model, _, _ = load_base()
    adapter = torch.load(ADAPTER_PATH, map_location="cpu", weights_only=True)
    inject_lora(
        model,
        rank=adapter["rank"],
        alpha=adapter["alpha"],
        dropout=0.0,
    )
    missing, unexpected = model.load_state_dict(adapter["lora"], strict=False)
    if unexpected:
        raise RuntimeError(f"adapter tak terduga: {unexpected}")
    # missing = bobot dasar, itu wajar.
    _ = missing
    model.eval()
    return model


def sample(model: GPT, tokenizer: CharTokenizer, prompt: str, tokens: int, temperature: float) -> str:
    rendered = render_prompt(prompt)
    ids = tokenizer.encode(rendered)
    if not ids:
        ids = tokenizer.encode("Sa ")
    idx = torch.tensor([ids], dtype=torch.long)
    out = model.generate(idx, max_new_tokens=tokens, temperature=temperature, top_k=40)
    text = tokenizer.decode(out[0].tolist())
    # Potong di giliran user berikutnya jika ada.
    tail = text[len(rendered) :]
    stop = tail.find("### User")
    if stop != -1:
        tail = tail[:stop]
    return rendered + tail.strip() + ("\n" if not tail.endswith("\n") else "")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", default="")
    p.add_argument("--tokens", type=int, default=80)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--base-only", action="store_true")
    args = p.parse_args()

    if not BASE_CKPT.is_file():
        raise SystemExit("Checkpoint dasar belum ada.")
    prompts = [args.prompt] if args.prompt else list(DEFAULT_PROMPTS)
    base, tokenizer, _ = load_base()
    lora = None if args.base_only else load_lora()

    print("=" * 62)
    print("BANDINGKAN DASAR vs LoRA")
    print("=" * 62)
    for prompt in prompts:
        print(f"\nPROMPT : {prompt}")
        print("--- dasar ---")
        print(sample(base, tokenizer, prompt, args.tokens, args.temperature))
        if lora is not None:
            print("--- +LoRA ---")
            print(sample(lora, tokenizer, prompt, args.tokens, args.temperature))


if __name__ == "__main__":
    main()
