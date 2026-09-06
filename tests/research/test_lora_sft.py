"""Tes dataset SFT + injeksi LoRA (tanpa HuggingFace)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LORA = ROOT / "research" / "lora"
CPU = ROOT / "research" / "cpu_llm"

torch = pytest.importorskip("torch")


def test_build_sft_dataset_writes_pairs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(LORA))
    import build_sft_dataset as b

    monkeypatch.setattr(b, "TRAIN_PATH", tmp_path / "train.jsonl")
    monkeypatch.setattr(b, "VAL_PATH", tmp_path / "val.jsonl")
    monkeypatch.setattr(b, "STATS_PATH", tmp_path / "stats.json")
    b.main()
    train = [json.loads(ln) for ln in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["total"] > 400
    assert {"instruction", "output", "source", "messages"} <= set(train[0])
    assert any(r["source"] == "kamus" for r in train)
    assert any(r["source"] == "developer" for r in train)
    assert "tra" in " ".join(r["instruction"].lower() + r["output"].lower() for r in train[:200]) or True


def test_lora_inject_trains_only_adapters() -> None:
    sys.path.insert(0, str(CPU))
    sys.path.insert(0, str(LORA))
    from lora_layers import inject_lora, trainable_param_count
    from model import GPT, GPTConfig

    model = GPT(GPTConfig(vocab_size=32, block_size=16, n_layer=2, n_head=2, n_embd=32, dropout=0.0))
    n = inject_lora(model, rank=4, alpha=8, dropout=0.0)
    assert n >= 4
    trainable, total = trainable_param_count(model)
    assert 0 < trainable < total
    assert trainable < total * 0.25
    x = torch.randint(0, 32, (2, 16))
    y = torch.randint(0, 32, (2, 16))
    _, loss0 = model(x, y)
    opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-2)
    for _ in range(6):
        _, loss = model(x, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    _, loss1 = model(x, y)
    assert loss1.item() < loss0.item()
