# LLM kecil Melayu Papua — dilatih di CPU, tanpa GPU

Bukti bahwa **LLM bisa dibuat tanpa GPU**. GPU mempercepat latihan, bukan syarat
keberadaan arsitektur transformer.

Pipeline ini:

1. Mengekstrak korpus dari data persona Papua yang sudah ada di repo
2. Melatih GPT decoder-only kecil **sepenuhnya di CPU**
3. Menghasilkan teks dari checkpoint

Ini **bukan** pengganti Gemini. Modelnya sengaja kecil (~1,8 juta parameter) supaya
latihan selesai di mesin 4-core tanpa kartu grafis. Hasilnya meniru logat dan
pola kata Melayu Papua, bukan menalar seperti model frontier.

## Mengapa CPU cukup di sini

| Faktor | Model frontier | Pipeline ini |
|---|---|---|
| Parameter | miliaran–triliunan | ~1 juta |
| Data | triliunan token | ~100 ribu karakter |
| Perangkat | ribuan GPU | 4 thread CPU |
| Tujuan | percakapan umum | bukti + eksperimen logat |

Aturan kasar: **ukuran model × jumlah data × jumlah langkah** menentukan apakah
CPU masih masuk akal. Turunkan ketiganya, GPU menjadi opsional.

Yang **tidak** bisa tanpa GPU (atau TPU/accelerator lain) dalam waktu wajar:

- Melatih model dari nol setara GPT/Gemini
- Fine-tune LoRA model 1B+ dalam waktu yang nyaman
- Inferensi on-device yang tetap cepat untuk voice-first (itu masalah lain: runtime HP)

## Cara pakai

```bash
# 1. Bangun korpus dari JSON persona
python research/cpu_llm/build_corpus.py

# 2. Latih di CPU (default 3000 langkah, ~beberapa menit di 4-core)
python research/cpu_llm/train.py

# 3. Generate teks
python research/cpu_llm/generate.py
python research/cpu_llm/generate.py --prompt "Ko su" --tokens 80
```

Dependensi: `torch` (CPU build cukup). Tidak perlu CUDA.

## Hasil run di mesin 4-core (tanpa GPU)

| Metrik | Nilai |
|---|---|
| Perangkat | CPU, 4 thread |
| Parameter | 1.814.592 |
| Korpus | 101.997 karakter / vocab 89 |
| Durasi | **10,3 menit** |
| Train loss | 4,54 → 0,22 |
| Val loss terbaik | **1,68** (step 1250) |

Setelah step 1250 model mulai overfitting (train turun, val naik). Checkpoint yang disimpan adalah yang val-nya terbaik.

Contoh generate (char-level, bukan percakapan penuh):

```
PROMPT : 'Ko su'
OUTPUT : Ko su mo pi?
Sa tra mo pi ke sana?
Sa pu hati.
```

Teksnya memakai pola Melayu Papua (`ko`, `sa`, `tra`, `mo`, `kah`) — bukti distribusi karakter terpelajari. Ini belum cukup untuk menggantikan Gemini.

## File

- `build_corpus.py` — ekstrak kalimat dari `src/persona_ai/personality/data/`
- `model.py` — GPT kecil (pre-norm, causal attention, weight tying)
- `tokenizer.py` — tokenizer level-karakter (cocok untuk korpus kecil)
- `train.py` — loop AdamW + cosine LR, simpan checkpoint terbaik
- `generate.py` — sampling dari checkpoint
- `corpus.txt` — korpus hasil ekstrak (bisa di-generate ulang)
