"""Parse persona-chat live log into timeline / incidents / RMS / transcript artifacts."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

SRC = Path(r"C:\Users\msi-u\.cursor\projects\f-Persona-Ai\terminals\412739.txt")
OUT = Path(__file__).resolve().parent

CHUNK_RE = re.compile(
    r"(client mic|gemini mic sent) chunk #(\d+) \((\d+) bytes, rms=([0-9.]+)\)"
)
FWD_RE = re.compile(r"forward model audio #(\d+) (\d+) bytes \(mode=(\w+)\)")
SUP_RE = re.compile(r"suppressed ungoverned model audio chunks=(\d+) total=(\d+) mode=(\w+)")
PARTIAL_RE = re.compile(r"user transcript (partial|final): ['\"](.+)['\"]")
MISSING_RE = re.compile(r"final transcript missing")
MISSING_DETAIL_RE = re.compile(r"governance \(([^)]+)\): ['\"](.+)['\"]")
GOV_RE = re.compile(
    r"governance applied raw_bdv=(\S+) effective_bdv=(\S+) steer=(\S+) llm=(\S+) play_steered=(\S+)"
)
GATE_RE = re.compile(
    r"keeping audio gate open after turn_complete \(awaiting steered audio, seen=(\S+)\)"
)


def stats(pairs: list[tuple[int, int, float]], label: str) -> dict:
    vals = [p[2] for p in pairs]
    if not vals:
        return {"label": label, "n": 0}
    sv = sorted(vals)
    n = len(sv)
    mean = sum(sv) / n
    med = sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2
    return {
        "label": label,
        "n": n,
        "mean": round(mean, 4),
        "median": round(med, 4),
        "min": round(sv[0], 4),
        "max": round(sv[-1], 4),
        "p90": round(sv[int(0.9 * (n - 1))], 4),
        "gt_0.08": sum(1 for v in sv if v > 0.08),
        "gt_0.10": sum(1 for v in sv if v > 0.10),
    }


def main() -> None:
    lines = SRC.read_text(encoding="utf-8", errors="replace").splitlines()
    timeline: list[dict] = []
    incidents: list[dict] = []
    rms_client: list[tuple[int, int, float]] = []
    rms_gemini: list[tuple[int, int, float]] = []
    transcripts: list[dict] = []
    turns: list[dict] = []
    current_turn: dict | None = None

    def add_inc(line_no: int, kind: str, note: str, extra: str = "") -> None:
        incidents.append(
            {"line_no": line_no, "kind": kind, "note": note, "extra": extra}
        )

    for i, line in enumerate(lines, 1):
        m = CHUNK_RE.search(line)
        if m:
            direction = "client" if m.group(1).startswith("client") else "gemini"
            chunk_id = int(m.group(2))
            nbytes = int(m.group(3))
            rms = float(m.group(4))
            note = "rms_spike" if direction == "client" and rms > 0.08 else ""
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": chunk_id,
                    "direction": direction,
                    "bytes": nbytes,
                    "rms": rms,
                    "event_note": note,
                }
            )
            (rms_client if direction == "client" else rms_gemini).append(
                (i, chunk_id, rms)
            )
            continue

        m = FWD_RE.search(line)
        if m:
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": int(m.group(1)),
                    "direction": "model_out",
                    "bytes": int(m.group(2)),
                    "rms": "",
                    "event_note": f"forward mode={m.group(3)}",
                }
            )
            continue

        m = SUP_RE.search(line)
        if m:
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": int(m.group(2)),
                    "direction": "model_out",
                    "bytes": "",
                    "rms": "",
                    "event_note": (
                        f"suppress chunks={m.group(1)} total={m.group(2)} mode={m.group(3)}"
                    ),
                }
            )
            add_inc(
                i,
                "SUPPRESS",
                f"chunks={m.group(1)} total={m.group(2)} mode={m.group(3)}",
            )
            continue

        m = PARTIAL_RE.search(line)
        if m:
            state, text = m.group(1), m.group(2)
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "asr",
                    "bytes": "",
                    "rms": "",
                    "event_note": f"transcript_{state}:{text}",
                }
            )
            transcripts.append({"line_no": i, "state": state, "text": text})
            current_turn = {
                "partial_line": i,
                "text": text,
                "bdv": None,
                "fallback": False,
                "interrupt": False,
                "gate_seen": None,
            }
            continue

        if MISSING_RE.search(line):
            rm = MISSING_DETAIL_RE.search(line)
            reason = rm.group(1) if rm else "?"
            text = rm.group(2) if rm else ""
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "asr",
                    "bytes": "",
                    "rms": "",
                    "event_note": f"FINAL_MISSING reason={reason} text={text}",
                }
            )
            add_inc(i, "FINAL_TRANSCRIPT_MISSING", reason, text)
            if current_turn:
                current_turn["fallback"] = True
                current_turn["fallback_reason"] = reason
            continue

        m = GOV_RE.search(line)
        if m:
            note = (
                f"gov raw={m.group(1)} eff={m.group(2)} steer={m.group(3)} "
                f"llm={m.group(4)} play={m.group(5)}"
            )
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "gov",
                    "bytes": "",
                    "rms": "",
                    "event_note": note,
                }
            )
            add_inc(i, "GOVERNANCE", note)
            if current_turn:
                current_turn["bdv"] = m.group(2)
                current_turn["steer"] = m.group(3)
                current_turn["play_steered"] = m.group(5)
                turns.append(current_turn)
            continue

        if "gemini interrupted flag" in line:
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "gemini",
                    "bytes": "",
                    "rms": "",
                    "event_note": "interrupted_flag keep_playback",
                }
            )
            add_inc(i, "GEMINI_INTERRUPTED", "keeping playback")
            if current_turn:
                current_turn["interrupt"] = True
            continue

        m = GATE_RE.search(line)
        if m:
            seen = m.group(1)
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "gate",
                    "bytes": "",
                    "rms": "",
                    "event_note": f"gate_hold seen={seen}",
                }
            )
            add_inc(i, "AUDIOGATE_HOLD", f"seen={seen}")
            if current_turn:
                current_turn["gate_seen"] = seen
            continue

        if "greeting turn_complete" in line:
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "gate",
                    "bytes": "",
                    "rms": "",
                    "event_note": "greeting_complete gate_closed",
                }
            )
            continue

        if "live session" in line:
            timeline.append(
                {
                    "line_no": i,
                    "chunk_id": "",
                    "direction": "session",
                    "bytes": "",
                    "rms": "",
                    "event_note": line.split("gemini_live_bridge: ", 1)[-1],
                }
            )

    with (OUT / "timeline.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["line_no", "chunk_id", "direction", "bytes", "rms", "event_note"]
        )
        writer.writeheader()
        writer.writerows(timeline)

    with (OUT / "incidents.tsv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["line_no", "kind", "note", "extra"], delimiter="\t"
        )
        writer.writeheader()
        writer.writerows(incidents)

    spikes = [p for p in rms_client if p[2] > 0.08]
    windows: list[list[tuple[int, int, float]]] = []
    if spikes:
        group = [spikes[0]]
        for prev, cur in zip(spikes, spikes[1:]):
            if cur[1] - prev[1] <= 8:
                group.append(cur)
            else:
                windows.append(group)
                group = [cur]
        windows.append(group)

    with (OUT / "transcript.txt").open("w", encoding="utf-8") as f:
        f.write("session=web-97421f04\n")
        f.write("source=terminals/412739.txt\n")
        f.write("final ASR lines=0 (none logged)\n\n")
        for idx, turn in enumerate(turns, 1):
            f.write(
                f"{idx:02d}. L{turn['partial_line']} PARTIAL  {turn['text']!r}\n"
                f"    bdv={turn.get('bdv')} fallback={turn.get('fallback')} "
                f"reason={turn.get('fallback_reason')} interrupt={turn.get('interrupt')} "
                f"gate_seen={turn.get('gate_seen')}\n"
            )
        leftover = [t for t in transcripts if t["text"] not in {x["text"] for x in turns}]
        if leftover:
            f.write("\n# transcripts without governance line\n")
            for t in leftover:
                f.write(f"L{t['line_no']} {t['state']}: {t['text']}\n")

    with (OUT / "rms-stats.txt").open("w", encoding="utf-8") as f:
        f.write("NOTE: client/gemini chunks are sampled in logs, not every 100ms frame.\n")
        f.write("Client lines tend to appear when RMS is interesting or at cadence.\n\n")
        for block in (stats(rms_client, "client_logged"), stats(rms_gemini, "gemini_sent_logged")):
            f.write(json.dumps(block) + "\n")
        f.write(f"\nspikes_client_rms>0.08: {len(spikes)}\n")
        for line_no, chunk_id, rms in spikes:
            f.write(f"  L{line_no} chunk#{chunk_id} rms={rms:.4f}\n")
        f.write("\nspike windows (chunk gap <= 8):\n")
        for group in windows:
            ids = [x[1] for x in group]
            rms = [x[2] for x in group]
            f.write(
                f"  chunks {ids[0]}-{ids[-1]} n={len(group)} "
                f"max={max(rms):.4f} mean={sum(rms)/len(rms):.4f}\n"
            )

    meta = {
        "session": "web-97421f04",
        "source": str(SRC),
        "timeline_rows": len(timeline),
        "client_stats": stats(rms_client, "client_logged"),
        "gemini_stats": stats(rms_gemini, "gemini_sent_logged"),
        "spikes": [{"line": a, "chunk": b, "rms": c} for a, b, c in spikes],
        "spike_windows": [
            {
                "start": w[0][1],
                "end": w[-1][1],
                "n": len(w),
                "max": max(x[2] for x in w),
            }
            for w in windows
        ],
        "turns": turns,
        "transcripts": transcripts,
        "incident_counts": {
            kind: sum(1 for x in incidents if x["kind"] == kind)
            for kind in (
                "FINAL_TRANSCRIPT_MISSING",
                "SUPPRESS",
                "GOVERNANCE",
                "GEMINI_INTERRUPTED",
                "AUDIOGATE_HOLD",
            )
        },
    }
    (OUT / "analysis.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(meta["incident_counts"], indent=2))
    print("turns", len(turns), "timeline", len(timeline), "spikes", len(spikes))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
