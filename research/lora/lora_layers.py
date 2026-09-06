"""LoRA murni (tanpa peft) untuk Linear di GPT lokal."""

from __future__ import annotations

import math
from typing import Iterable

import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    def __init__(self, base: nn.Linear, rank: int = 8, alpha: int = 16, dropout: float = 0.05) -> None:
        super().__init__()
        if rank < 1:
            raise ValueError("rank LoRA harus >= 1")
        self.base = base
        for param in self.base.parameters():
            param.requires_grad = False
        self.rank = rank
        self.alpha = alpha
        self.scaling = alpha / rank
        self.lora_A = nn.Parameter(torch.empty(rank, base.in_features))
        self.lora_B = nn.Parameter(torch.zeros(base.out_features, rank))
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))
        self.drop = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        adapt = self.drop(x) @ self.lora_A.T @ self.lora_B.T
        return self.base(x) + adapt * self.scaling


def inject_lora(
    model: nn.Module,
    *,
    rank: int = 8,
    alpha: int = 16,
    dropout: float = 0.05,
    target_suffixes: Iterable[str] = ("c_attn", "c_proj", "c_fc"),
) -> int:
    """Ganti Linear target dengan LoRALinear. Kembalikan jumlah modul yang diubah."""
    targets = tuple(target_suffixes)
    modules = dict(model.named_modules())
    to_swap: list[tuple[str, nn.Linear]] = []
    for name, module in modules.items():
        if name == "lm_head" or not isinstance(module, nn.Linear):
            continue
        if name.rsplit(".", 1)[-1] in targets:
            to_swap.append((name, module))

    for name, module in to_swap:
        if "." in name:
            parent_name, child = name.rsplit(".", 1)
            parent = modules[parent_name]
        else:
            parent, child = model, name
        setattr(parent, child, LoRALinear(module, rank=rank, alpha=alpha, dropout=dropout))

    for name, param in model.named_parameters():
        param.requires_grad = "lora_" in name
    return len(to_swap)


def lora_state_dict(model: nn.Module) -> dict[str, torch.Tensor]:
    return {k: v.detach().cpu() for k, v in model.state_dict().items() if "lora_" in k}


def trainable_param_count(model: nn.Module) -> tuple[int, int]:
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    return trainable, total
