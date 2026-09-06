#!/usr/bin/env python3
"""Fine-tune LoRA model instruksi HuggingFace (Qwen/Sailor/Gemma).

Dijalankan di Colab / mesin ber-GPU + akses huggingface.co.
VM cloud ini memblokir HuggingFace, jadi skrip ini tidak dijalankan di sini.

Usage:
  python research/lora/train_lora_hf.py --model Qwen/Qwen2.5-0.5B-Instruct
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAIN_JSONL = HERE / "sft_train.jsonl"
VAL_JSONL = HERE / "sft_val.jsonl"
OUT_DIR = HERE / "hf_adapter"

from format_chat import SYSTEM_PROMPT  # noqa: E402


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    p = argparse.ArgumentParser(description="LoRA SFT via transformers+peft")
    p.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--max-len", type=int, default=512)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--grad-accum", type=int, default=8)
    args = p.parse_args()

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
    except ImportError as exc:
        raise SystemExit(
            "Butuh: pip install transformers peft datasets accelerate\n"
            f"Import gagal: {exc}"
        ) from exc

    if not TRAIN_JSONL.is_file():
        raise SystemExit("Jalankan dulu: python research/lora/build_sft_dataset.py")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def to_text(row: dict) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": row["instruction"]},
            {"role": "assistant", "content": row["output"]},
        ]
        if hasattr(tokenizer, "apply_chat_template"):
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False
            )
        return f"System: {SYSTEM_PROMPT}\nUser: {row['instruction']}\nAssistant: {row['output']}"

    def tokenize_split(path: Path) -> Dataset:
        texts = [to_text(r) for r in _rows(path)]
        ds = Dataset.from_dict({"text": texts})

        def tok(batch):
            enc = tokenizer(
                batch["text"],
                truncation=True,
                max_length=args.max_len,
                padding="max_length",
            )
            enc["labels"] = [ids[:] for ids in enc["input_ids"]]
            return enc

        return ds.map(tok, batched=True, remove_columns=["text"])

    train_ds = tokenize_split(TRAIN_JSONL)
    val_ds = tokenize_split(VAL_JSONL)

    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=dtype,
        trust_remote_code=True,
    )
    model.config.use_cache = False
    peft_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, peft_cfg)
    model.print_trainable_parameters()

    out = OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    training = TrainingArguments(
        output_dir=str(out / "runs"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        bf16=torch.cuda.is_available(),
        report_to=[],
        load_best_model_at_end=True,
    )
    trainer = Trainer(
        model=model,
        args=training,
        train_dataset=train_ds,
        eval_dataset=val_ds,
    )
    trainer.train()
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    print(f"Adapter HF disimpan di {out}")


if __name__ == "__main__":
    main()
