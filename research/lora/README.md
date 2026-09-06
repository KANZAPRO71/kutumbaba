# Fine-tune LoRA Melayu Papua

Dua jalur:

1. **Lokal (CPU, dijalankan di repo ini)** — LoRA di checkpoint GPT kecil hasil `research/cpu_llm`. Tidak butuh GPU atau HuggingFace.
2. **Colab / GPU** — LoRA di `Qwen2.5-0.5B-Instruct` (atau Sailor2 / Gemma) memakai dataset SFT yang sama.

HuggingFace diblokir di VM cloud, jadi jalur 2 tidak bisa dijalankan di sini. Dataset dan skripnya sudah siap.

## Dataset SFT

```bash
python research/lora/build_sft_dataset.py
```

Mengubah JSON persona (kamus, mop, pengetahuan, gaul, dialek, musik, pantun, kredit developer, Biak, Tabi) jadi pasangan instruksi di `sft_train.jsonl` / `sft_val.jsonl`.

Format tiap baris:

```json
{
  "instruction": "Apa arti tra?",
  "output": "tra artinya tidak.",
  "source": "kamus",
  "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
}
```

## Jalur 1 — LoRA di CPU (bukti di repo ini)

Butuh checkpoint `research/cpu_llm/papua_lm.pt` (hasil `python research/cpu_llm/train.py`).

```bash
python research/lora/build_sft_dataset.py
python research/lora/train_lora.py
python research/lora/generate_lora.py
```

Hanya bobot `lora_A` / `lora_B` yang dilatih (~beberapa persen parameter). Dasar dibekukan.

### Hasil run CPU (4 thread, 0 GPU)

| Metrik | Nilai |
|---|---|
| Modul LoRA | 16 (rank 8 / alpha 16) |
| Trainable | 98.304 / 1.912.896 (**5,14%**) |
| Val loss | **1,82 → 0,82** |
| Durasi | **4,5 menit** |

Loss turun tanpa overfitting. Generate char-level tetap berantakan — model 1,8 juta parameter tidak cukup untuk ikut instruksi. LoRA di sini membuktikan adapter + dataset; percakapan yang layak butuh jalur Qwen di Colab.

## Jalur 2 — LoRA di Qwen (Colab)

Buka `Papua_LoRA_Colab.ipynb` di Google Colab (GPU T4), atau:

```bash
pip install transformers peft datasets accelerate
python research/lora/train_lora_hf.py --model Qwen/Qwen2.5-0.5B-Instruct
```

Ini jalur yang menghasilkan model percakapan yang lebih masuk akal. Checkpoint GPT char-level tetap mainan; Qwen 0.5B–1.5B yang sudah bisa bahasa Indonesia + LoRA data Papua jauh lebih dekat ke tujuan aplikasi.
