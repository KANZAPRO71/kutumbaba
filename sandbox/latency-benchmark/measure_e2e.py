#!/usr/bin/env python3
"""Measure Persona API-level latency (reference budgets)."""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
PERSONA = "http://127.0.0.1:8765"
SAMPLES = 8
LATENCY_LOG_RE = re.compile(r"turn latency (\{.*\})")


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round((len(s) - 1) * p))
    return s[idx]


def summarize(name: str, values: list[float]) -> dict:
    if not values:
        return {"name": name, "n": 0}
    return {
        "name": name,
        "n": len(values),
        "min_ms": round(min(values), 1),
        "median_ms": round(statistics.median(values), 1),
        "mean_ms": round(statistics.mean(values), 1),
        "p90_ms": round(pct(values, 0.9), 1),
        "max_ms": round(max(values), 1),
    }


def get_json(url: str, timeout: float = 10.0) -> tuple[float, dict, int]:
    t0 = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return elapsed_ms, json.loads(raw.decode("utf-8")), resp.status


def probe_persona_health(n: int = 5) -> list[float]:
    out: list[float] = []
    for _ in range(n):
        try:
            ms, _, _ = get_json(f"{PERSONA}/api/health")
            out.append(ms)
        except Exception:
            break
        time.sleep(0.05)
    return out


def bench_persona_bdv(n: int = 5) -> list[float]:
    """Local BDV-only slice (no Gemini network)."""
    try:
        from persona_ai.runtime import PersonaRuntime
    except ImportError:
        repo = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo / "src"))
        from persona_ai.runtime import PersonaRuntime

    runtime = PersonaRuntime()
    session = f"latency-bench-{int(time.time())}"
    prompts = [
        "Halo.",
        "Jam berapa sekarang?",
        "Ceritakan singkat tentang AI.",
        "Apa kabar?",
        "M itu apa?",
    ]
    out: list[float] = []
    for i in range(n):
        text = prompts[i % len(prompts)]
        t0 = time.perf_counter()
        runtime.process_turn(
            session,
            text,
            persist=False,
            channel="voice",
            generate_text=False,
        )
        out.append((time.perf_counter() - t0) * 1000)
    return out


def parse_persona_log(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LATENCY_LOG_RE.search(line)
        if m:
            try:
                rows.append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                continue
    return rows


def persona_log_summary(rows: list[dict]) -> dict:
    by_phase: dict[str, list[dict]] = {}
    for row in rows:
        by_phase.setdefault(row.get("phase", "?"), []).append(row)

    def col(phase: str, key: str) -> list[float]:
        return [
            float(r[key])
            for r in by_phase.get(phase, [])
            if isinstance(r.get(key), (int, float))
        ]

    return {
        "connect": summarize("persona_connect", col("connect", "connect_ms")),
        "greeting": summarize("persona_greeting_to_audio", col("greeting", "greeting_to_audio_ms")),
        "turn_commit_to_audio": summarize(
            "persona_commit_to_audio", col("turn_response", "commit_to_audio_ms")
        ),
        "turn_governance": summarize(
            "persona_governance", col("turn_response", "governance_ms")
        ),
        "turn_steer_to_audio": summarize(
            "persona_steer_to_audio", col("turn_response", "steer_to_audio_ms")
        ),
        "samples": len(rows),
    }


def build_report(results: dict) -> str:
    persona_health = results["persona"]["health"]
    persona_bdv = results["persona"]["bdv_local"]
    persona_live = results["persona"].get("live_log", {})

    lines = [
        "# E2E Latency Benchmark — Persona",
        "",
        f"**Measured:** {results['measured_at']}",
        "",
        "## What we can measure without a browser",
        "",
        "| Slice | Persona | Reference budget |",
        "|-------|---------|------------------|",
        f"| WS connect | connect **{persona_live.get('connect', {}).get('median_ms', 'instrumented')} ms** | network 30–80 ms |",
        f"| BDV governance (local) | **{persona_bdv.get('median_ms', '?')} ms** | < 80 ms pre-LLM |",
        f"| Governance / orchestration | governance **{persona_live.get('turn_governance', {}).get('median_ms', 'instrumented')} ms** | turn-taking 150–300 ms |",
        f"| Commit → first steered audio | commit_to_audio **{persona_live.get('turn_commit_to_audio', {}).get('median_ms', 'instrumented')} ms** | **~600 ms** E2E target |",
        "",
        "## Persona — local probes",
        "",
        f"- `GET /api/health`: {json.dumps(persona_health)}",
        f"- `PersonaRuntime.process_turn` (voice channel, no Gemini): {json.dumps(persona_bdv)}",
        "",
    ]
    if persona_live.get("samples"):
        lines.extend(
            [
                "### Persona Live log samples",
                "",
                f"- Parsed `turn latency` lines: **{persona_live['samples']}**",
                f"- Connect: {json.dumps(persona_live.get('connect', {}))}",
                f"- Greeting → audio: {json.dumps(persona_live.get('greeting', {}))}",
                f"- Commit → audio: {json.dumps(persona_live.get('turn_commit_to_audio', {}))}",
                f"- Governance only: {json.dumps(persona_live.get('turn_governance', {}))}",
                f"- Steer → audio: {json.dumps(persona_live.get('turn_steer_to_audio', {}))}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "### Persona Live voice E2E",
                "",
                "No `turn latency` log lines yet. Start a Call after server restart; bridge now emits:",
                "",
                "```",
                'turn latency {"phase":"turn_response","commit_to_audio_ms":...,"governance_ms":...}',
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Interpretation",
            "",
            "### Persona overhead (expected)",
            "- **Persona-first pipeline**: VAD wait (~500 ms silence floor) + ASR stability (200–600 ms) + BDV + ENGINE steer + second Gemini audio pass.",
            f"- Local BDV slice ~**{persona_bdv.get('median_ms', '?')} ms** — small vs total E2E.",
            "- Main cost is **governance + steered re-generation**, not BDV CPU.",
            "",
            "### Rough E2E model (Persona voice turn)",
            "",
            "```",
            "vad_wait        ~500–850 ms   (silence + STT grace + partial stability)",
            "governance_ms   ~50–200 ms    (BDV + steer inject)",
            "steer_to_audio  ~300–800 ms   (Gemini generates steered PCM)",
            "─────────────────────────────",
            "commit_to_audio ~900–1800 ms  (typical; measure after live Call)",
            "```",
            "",
            "## Next measurement",
            "",
            "1. Restart server (`persona-chat.exe`)",
            "2. Hard refresh → one voice Call → ask 3 questions",
            "3. Re-run: `python sandbox/latency-benchmark/measure_e2e.py --log terminals/<id>.txt`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    log_path = None
    if "--log" in sys.argv:
        idx = sys.argv.index("--log")
        if idx + 1 < len(sys.argv):
            log_path = Path(sys.argv[idx + 1])

    persona_health = probe_persona_health()
    persona_bdv = bench_persona_bdv()
    live_rows = parse_persona_log(log_path) if log_path else []
    if not live_rows:
        for candidate in sorted(
            Path(r"C:\Users\msi-u\.cursor\projects\f-Persona-Ai\terminals").glob("*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:5]:
            live_rows = parse_persona_log(candidate)
            if live_rows:
                log_path = candidate
                break

    results = {
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "persona": {
            "health": summarize("persona_health", persona_health),
            "bdv_local": summarize("persona_bdv", persona_bdv),
            "live_log": persona_log_summary(live_rows),
            "live_log_path": str(log_path) if log_path else None,
        },
        "reference": {
            "voice_e2e_budget_ms": 600,
            "turn_taking_ms": "150-300",
            "llm_ttft_ms": "150-400",
            "tts_ttfa_ms": "100-200",
        },
    }

    OUT.joinpath("results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    OUT.joinpath("REPORT.md").write_text(build_report(results), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"\nWrote {OUT / 'REPORT.md'}")


if __name__ == "__main__":
    main()
