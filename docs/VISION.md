# Persona AI — Vision

**Status:** Draft v0.2  
**Terakhir diperbarui:** 2026-08-26

---

## One sentence truth

> **Persona AI adalah sistem percakapan yang membuat interaksi manusia dengan AI terasa seperti berbicara dengan teman yang memahami konteks — bukan mesin yang selalu merespons.**

Kalau semua detail dokumen ini dilupakan, balik ke kalimat itu.

---

## Core vision

Persona AI bukan chatbot dengan prompt bagus. Ini **otak perilaku** — sistem yang memutuskan *apakah* AI harus bicara, *bagaimana* bicara, dan *kapan* berhenti — sebelum teks dihasilkan.

| Chatbot | Persona AI |
|---------|------------|
| LLM = otak + suara | Behavior Engine = otak sosial; LLM = mulut |
| Setiap input → generate | Setiap input → **putuskan dulu** → baru generate (atau diam) |
| Personality = teks di prompt | Personality = profil terstruktur |
| Model terikat arsitektur | Model swappable (Gemini / GPT / Claude) |

**Implikasi:** Speech-to-speech, domain plugin, dan model AI apapun jadi lapisan bawah. Persona AI mengontrol *feel* percakapan — bukan *pengetahuan*.

---

## Behavior Engine — definisi inti

Behavior Engine **bukan prompt system**. Ini **decision system**.

Satu pertanyaan yang dijawab setiap turn:

> *"Haruskah AI berbicara sekarang — dan jika ya, bagaimana?"*

### Dimensi keputusan (v1)

| Dimensi | Pilihan | Arti |
|---------|---------|------|
| **Speak** | `RESPOND` · `SILENCE` · `DEFER` · `ACK_ONLY` | Bicara atau tidak |
| **Length** | `MINIMAL` · `NORMAL` · `EXPAND` | Singkat vs panjang |
| **Questions** | `NONE` · `CLARIFY_ONLY` · `ALLOWED` | Tanya balik atau tidak |
| **Interrupt** | `FORBIDDEN` · `BACKCHANNEL_OK` · `ALLOWED` | Boleh potong / "hm" / nyelip |
| **Tone shift** | `STABLE` · `WARMER` · `SOFTER` · `MATCH_USER` | Perubahan emosi situasional |
| **Stop rule** | `ONE_TURN` · `UNTIL_RESOLVED` | Kapan berhenti bicara |

Keputusan diambil **sebelum LLM dipanggil**. LLM hanya mengisi konten di bawah constraint keputusan ini.

### Contoh (mengapa ini bukan prompt)

| Input user | Keputusan | Hasil |
|------------|-----------|-------|
| "Ah capek banget hari ini..." | `ACK_ONLY` · `MINIMAL` · `NONE` | "Iya, berat ya." — bukan 3 pertanyaan |
| "Oke" (setelah penjelasan panjang) | `SILENCE` | Diam — bukan "Ada lagi?" |
| Pause mid-sentence (voice) | `DEFER` · `FORBIDDEN` | Tunggu — bukan interrupt |
| User marah | `RESPOND` · `MINIMAL` · `SOFTER` | Acknowledgment hangat, tidak debat |

---

## Behavior Decision Schema (v1)

```
INPUT                          DECISION                      OUTPUT BEHAVIOR
─────                          ────────                      ───────────────
                               ┌─────────────────┐
UserMessage ──────────────────►│                 │
                               │  Behavior       │──────────► speak: RESPOND | SILENCE | ...
TurnHistory ──────────────────►│  Engine         │──────────► length: MINIMAL | NORMAL | ...
SessionState ─────────────────►│  (rule engine)  │──────────► questions: NONE | ...
PolicySignals ────────────────►│                 │──────────► interrupt: FORBIDDEN | ...
PluginSignals ────────────────►│                 │──────────► tone_shift: STABLE | ...
ChannelMeta ──────────────────►└─────────────────┘──────────► stop_rule: ONE_TURN | ...
                               │
                               └──► BehaviorDecision (structured, logged)
                                         │
                                         ▼
                                    LLM / Speech / Silence
```

### Input schema

```yaml
BehaviorInput:
  message:
    text: string
    type: statement | question | ack | vent | command
    length: short | medium | long
  history:
    last_speaker: user | assistant
    turns_since_assistant: int
    last_assistant_verbosity: MINIMAL | NORMAL | EXPAND
  session:
    turn_index: int
    channel: text | voice
    elapsed_ms_since_last: int
  signals:
    policy: []        # e.g. must_respond
    plugin: []        # e.g. intake_mode_active
  channel_meta:
    voice_pause_ms: int | null   # voice only
    stt_confidence: float | null
```

### Decision schema

```yaml
BehaviorDecision:
  speak: RESPOND | SILENCE | DEFER | ACK_ONLY
  length: MINIMAL | NORMAL | EXPAND
  questions: NONE | CLARIFY_ONLY | ALLOWED
  interrupt: FORBIDDEN | BACKCHANNEL_OK | ALLOWED
  tone_shift: STABLE | WARMER | SOFTER | MATCH_USER
  stop_rule: ONE_TURN | UNTIL_RESOLVED
  timing:
    delay_ms: int              # 0 = immediate
  confidence: float            # 0.0–1.0, for logging & fallback
  reason_codes: string[]       # e.g. ["user_venting", "assistant_spoke_last"]
```

### Output behavior (eksekusi)

| `speak` | LLM dipanggil? | Output |
|---------|----------------|--------|
| `SILENCE` | ❌ | Tidak ada respons |
| `DEFER` | ❌ | Tunggu input lanjutan |
| `ACK_ONLY` | ✅ (constrained) | Backchannel singkat, no questions |
| `RESPOND` | ✅ | Full generation under length/tone/stop constraints |

---

## Prinsip (5 saja)

1. **Behavior-first** — keputusan perilaku sebelum LLM
2. **LLM = mulut, bukan otak** — generate teks, bukan putuskan bicara/tidak
3. **Model-agnostic** — ganti provider tanpa rombak pipeline
4. **Observable** — setiap `BehaviorDecision` ter-log
5. **Plugin untuk domain** — core domain-agnostic, scale ke banyak vertical

---

## Non-goals (v1 — 3 saja)

| Non-goal | Alasan singkat |
|----------|----------------|
| **No UI complexity** | Platform layer dulu, product UI nanti |
| **No fine-tuning awal** | LLM via adapter cukup buktikan behavior |
| **No multi-agent system** | Satu persona, satu pipeline — agent swarm defer |

Sisanya (voice, i18n, production scaling, multi-modal) → **ROADMAP.md**.

---

## North star question

> *"Apakah ini bikin AI terasa seperti teman yang paham konteks — atau mesin yang selalu merespons?"*

Always respond · always ask · always long = **salah arah**.

---

## Dokumentasi fondasi

| # | Dokumen | Status |
|---|---------|--------|
| 1 | **VISION.md** (ini) | ✅ v0.2 |
| 2 | ARCHITECTURE.md | ✅ v1.1 |
| 3 | [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) | ✅ v1.3 locked |
| 4 | PERSONALITY.md | ✅ v1.0 |
| — | COHERENCE.md | ✅ v1.1 |
| 5 | CONVERSATION_POLICY.md | ✅ v1.0 |
| 6 | MEMORY.md | ✅ v1.0 |
| 7 | ROADMAP.md | ✅ v1.0 |

Schema di atas = contract v1. State machine, decision loop, context pressure, anti-chatbot rules → **[BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md)**.
