#!/usr/bin/env python3
"""Fine-tune LoRA di checkpoint GPT Papua — CPU, tanpa peft/HF.

Usage:
  python research/lora/train_lora.py
  python research/lora/train_lora.py --iters 800 --rank 8
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
CPU_LLM = HERE.parent / "cpu_llm"
if str(CPU_LLM) not in sys.path:
    sys.path.insert(0, str(CPU_LLM))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from format_chat import render_example  # noqa: E402
from lora_layers import inject_lora, lora_state_dict, trainable_param_count  # noqa: E402
from model import GPT, GPTConfig  # noqa: E402
from tokenizer import CharTokenizer  # noqa: E402

BASE_CKPT = CPU_LLM / "papua_lm.pt"
TOKENIZER_PATH = CPU_LLM / "tokenizer.json"
TRAIN_JSONL = HERE / "sft_train.jsonl"
VAL_JSONL = HERE / "sft_val.jsonl"
ADAPTER_PATH = HERE / "papua_lora.pt"
METRICS_PATH = HERE / "lora_metrics.json"


def _load_texts(path: Path) -> list[str]:
    texts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        texts.append(render_example(row["instruction"], row["output"]))
    return texts


def _encode_corpus(texts: list[str], tokenizer: CharTokenizer) -> torch.Tensor:
    blob = "\n".join(texts) + "\n"
    ids = tokenizer.encode(blob)
    if len(ids) < 256:
        raise SystemExit("dataset terencode terlalu pendek")
    return torch.tensor(ids, dtype=torch.long)


def get_batch(
    data: torch.Tensor, batch_size: int, block_size: int, generator: torch.Generator
) -> tuple[torch.Tensor, torch.Tensor]:
    ix = torch.randint(len(data) - block_size - 1, (batch_size,), generator=generator)
    x = torch.stack([data[i : i + block_size] for i in ix])
    y = torch.stack([data[i + 1 : i + 1 + block_size] for i in ix])
    return x, y


@torch.no_grad()
def estimate_loss(
    model: GPT,
    data: torch.Tensor,
    batch_size: int,
    block_size: int,
    eval_iters: int,
    generator: torch.Generator,
) -> float:
    model.eval()
    losses = torch.zeros(eval_iters)
    for i in range(eval_iters):
        x, y = get_batch(data, batch_size, block_size, generator)
        _, loss = model(x, y)
        losses[i] = loss.item()
    model.train()
    return losses.mean().item()


def lr_at(step: int, *, base_lr: float, warmup: int, total: int, min_lr: float) -> float:
    if step < warmup:
        return base_lr * (step + 1) / warmup
    progress = (step - warmup) / max(1, total - warmup)
    return min_lr + 0.5 * (base_lr - min_lr) * (1.0 + math.cos(math.pi * progress))


def load_base() -> tuple[GPT, CharTokenizer]:
    if not BASE_CKPT.is_file() or not TOKENIZER_PATH.is_file():
        raise SystemExit(
            "Checkpoint dasar belum ada. Jalankan dulu: python research/cpu_llm/train.py"
        )
    tokenizer = CharTokenizer.load(TOKENIZER_PATH)
    payload = torch.load(BASE_CKPT, map_location="cpu", weights_only=True)
    model = GPT(GPTConfig(**payload["config"]))
    model.load_state_dict(payload["model"])
    return model, tokenizer


def main() -> None:
    p = argparse.ArgumentParser(description="Fine-tune LoRA Papua di CPU")
    p.add_argument("--iters", type=int, default=800)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--block-size", type=int, default=128)
    p.add_argument("--rank", type=int, default=8)
    p.add_argument("--alpha", type=int, default=16)
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--eval-interval", type=int, default=100)
    p.add_argument("--eval-iters", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    if not TRAIN_JSONL.is_file():
        raise SystemExit("Dataset belum ada. Jalankan: python research/lora/build_sft_dataset.py")

    torch.manual_seed(args.seed)
    gen = torch.Generator().manual_seed(args.seed)

    model, tokenizer = load_base()
    n_modules = inject_lora(model, rank=args.rank, alpha=args.alpha, dropout=args.dropout)
    trainable, total = trainable_param_count(model)

    train_ids = _encode_corpus(_load_texts(TRAIN_JSONL), tokenizer)
    val_ids = _encode_corpus(_load_texts(VAL_JSONL), tokenizer)

    print("=" * 62, flush=True)
    print("FINE-TUNE LORA — CPU, tanpa GPU / tanpa HuggingFace", flush=True)
    print("=" * 62, flush=True)
    print(f"Perangkat      : CPU ({torch.get_num_threads()} thread)", flush=True)
    print(f"Modul LoRA     : {n_modules}", flush=True)
    print(f"Rank / alpha   : {args.rank} / {args.alpha}", flush=True)
    print(f"Trainable      : {trainable:,} / {total:,} ({100*trainable/total:.2f}%)", flush=True)
    print(f"Token SFT      : train {len(train_ids):,} | val {len(val_ids):,}", flush=True)
    print("=" * 62, flush=True)

    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=args.lr,
        betas=(0.9, 0.99),
        weight_decay=0.01,
    )

    history: list[dict[str, float]] = []
    best_val = float("inf")
    start = time.time()
    model.train()

    for step in range(args.iters):
        lr = lr_at(step, base_lr=args.lr, warmup=40, total=args.iters, min_lr=args.lr / 10)
        for group in optimizer.param_groups:
            group["lr"] = lr

        if step % args.eval_interval == 0 or step == args.iters - 1:
            train_loss = estimate_loss(
                model, train_ids, args.batch_size, args.block_size, args.eval_iters, gen
            )
            val_loss = estimate_loss(
                model, val_ids, args.batch_size, args.block_size, args.eval_iters, gen
            )
            elapsed = time.time() - start
            print(
                f"step {step:>4} | train {train_loss:.4f} | val {val_loss:.4f} | "
                f"lr {lr:.2e} | {elapsed:6.1f}s",
                flush=True,
            )
            history.append(
                {"step": step, "train": train_loss, "val": val_loss, "elapsed_s": round(elapsed, 1)}
            )
            if val_loss < best_val:
                best_val = val_loss
                torch.save(
                    {
                        "lora": lora_state_dict(model),
                        "rank": args.rank,
                        "alpha": args.alpha,
                        "dropout": args.dropout,
                        "base_config": model.cfg.__dict__,
                    },
                    ADAPTER_PATH,
                )

        x, y = get_batch(train_ids, args.batch_size, args.block_size, gen)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            (p for p in model.parameters() if p.requires_grad), 1.0
        )
        optimizer.step()

    total_s = time.time() - start
    print("=" * 62, flush=True)
    print(f"Selesai {total_s/60:.1f} menit. Val terbaik: {best_val:.4f}", flush=True)
    print(f"Adapter: {ADAPTER_PATH}", flush=True)
    METRICS_PATH.write_text(
        json.dumps(
            {
                "history": history,
                "best_val_loss": best_val,
                "total_seconds": round(total_s, 1),
                "trainable": trainable,
                "total_params": total,
                "rank": args.rank,
                "alpha": args.alpha,
                "device": "cpu",
                "threads": torch.get_num_threads(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
