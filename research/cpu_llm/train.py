#!/usr/bin/env python3
"""Latih LM kecil Melayu Papua sepenuhnya di CPU.

Usage:
  python research/cpu_llm/train.py                 # konfigurasi default
  python research/cpu_llm/train.py --iters 1000    # lebih cepat
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from model import GPT, GPTConfig
from tokenizer import CharTokenizer

CORPUS = HERE / "corpus.txt"
CKPT = HERE / "papua_lm.pt"
TOKENIZER_PATH = HERE / "tokenizer.json"
METRICS = HERE / "train_metrics.json"


def get_batch(
    data: torch.Tensor, batch_size: int, block_size: int, generator: torch.Generator
) -> tuple[torch.Tensor, torch.Tensor]:
    ix = torch.randint(
        len(data) - block_size - 1, (batch_size,), generator=generator
    )
    x = torch.stack([data[i : i + block_size] for i in ix])
    y = torch.stack([data[i + 1 : i + 1 + block_size] for i in ix])
    return x, y


@torch.no_grad()
def estimate_loss(
    model: GPT,
    splits: dict[str, torch.Tensor],
    batch_size: int,
    block_size: int,
    eval_iters: int,
    generator: torch.Generator,
) -> dict[str, float]:
    model.eval()
    out: dict[str, float] = {}
    for name, data in splits.items():
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            x, y = get_batch(data, batch_size, block_size, generator)
            _, loss = model(x, y)
            losses[k] = loss.item()
        out[name] = losses.mean().item()
    model.train()
    return out


def lr_at(step: int, *, base_lr: float, warmup: int, total: int, min_lr: float) -> float:
    if step < warmup:
        return base_lr * (step + 1) / warmup
    progress = (step - warmup) / max(1, total - warmup)
    return min_lr + 0.5 * (base_lr - min_lr) * (1.0 + math.cos(math.pi * progress))


def main() -> None:
    p = argparse.ArgumentParser(description="Latih LM Papua kecil di CPU")
    p.add_argument("--iters", type=int, default=3000)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--block-size", type=int, default=128)
    p.add_argument("--n-layer", type=int, default=4)
    p.add_argument("--n-head", type=int, default=4)
    p.add_argument("--n-embd", type=int, default=192)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--lr", type=float, default=3e-3)
    p.add_argument("--eval-interval", type=int, default=250)
    p.add_argument("--eval-iters", type=int, default=40)
    p.add_argument("--seed", type=int, default=1337)
    args = p.parse_args()

    torch.manual_seed(args.seed)
    generator = torch.Generator().manual_seed(args.seed)

    if not CORPUS.is_file():
        raise SystemExit("corpus.txt tidak ada — jalankan build_corpus.py dulu")
    text = CORPUS.read_text(encoding="utf-8")

    tokenizer = CharTokenizer.from_text(text)
    tokenizer.save(TOKENIZER_PATH)
    data = torch.tensor(tokenizer.encode(text), dtype=torch.long)

    n_train = int(0.9 * len(data))
    splits = {"train": data[:n_train], "val": data[n_train:]}

    cfg = GPTConfig(
        vocab_size=tokenizer.vocab_size,
        block_size=args.block_size,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
        dropout=args.dropout,
    )
    model = GPT(cfg)

    print("=" * 62, flush=True)
    print("LATIHAN LM MELAYU PAPUA — CPU SAJA (TANPA GPU)", flush=True)
    print("=" * 62, flush=True)
    print(f"Perangkat      : CPU ({torch.get_num_threads()} thread)", flush=True)
    print(f"Korpus         : {len(text):,} karakter", flush=True)
    print(f"Ukuran vocab   : {tokenizer.vocab_size} karakter", flush=True)
    print(f"Token latih    : {len(splits['train']):,}", flush=True)
    print(f"Token validasi : {len(splits['val']):,}", flush=True)
    print(f"Parameter      : {model.num_params():,}", flush=True)
    print(f"Arsitektur     : {cfg.n_layer} layer, {cfg.n_head} head, dim {cfg.n_embd}", flush=True)
    print("=" * 62, flush=True)

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.lr, betas=(0.9, 0.99), weight_decay=0.1
    )

    history: list[dict[str, float]] = []
    best_val = float("inf")
    start = time.time()

    for step in range(args.iters):
        lr = lr_at(
            step, base_lr=args.lr, warmup=100, total=args.iters, min_lr=args.lr / 10
        )
        for group in optimizer.param_groups:
            group["lr"] = lr

        if step % args.eval_interval == 0 or step == args.iters - 1:
            losses = estimate_loss(
                model, splits, args.batch_size, args.block_size,
                args.eval_iters, generator,
            )
            elapsed = time.time() - start
            print(
                f"step {step:>5} | train {losses['train']:.4f} | "
                f"val {losses['val']:.4f} | lr {lr:.2e} | {elapsed:6.1f}s",
                flush=True,
            )
            history.append({"step": step, **losses, "elapsed_s": round(elapsed, 1)})
            if losses["val"] < best_val:
                best_val = losses["val"]
                torch.save(
                    {"model": model.state_dict(), "config": cfg.__dict__}, CKPT
                )

        x, y = get_batch(splits["train"], args.batch_size, args.block_size, generator)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

    total = time.time() - start
    print("=" * 62)
    print(f"Selesai dalam {total/60:.1f} menit di CPU. Val loss terbaik: {best_val:.4f}")
    print(f"Checkpoint: {CKPT}")

    METRICS.write_text(
        json.dumps(
            {
                "history": history,
                "best_val_loss": best_val,
                "total_seconds": round(total, 1),
                "params": model.num_params(),
                "vocab_size": tokenizer.vocab_size,
                "corpus_chars": len(text),
                "device": "cpu",
                "threads": torch.get_num_threads(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
