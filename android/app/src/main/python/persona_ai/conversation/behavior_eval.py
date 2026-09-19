"""Sprint F — aggregate behavior telemetry into per-mode evaluation (observer-only)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from persona_ai.conversation.behavior_tuning import (
    TUNING_MODE_ORDER,
    eval_row_with_tuning,
    evaluate_mode_contract,
)
from persona_ai.conversation.experience_modes import (
    get_experience_profile,
    list_experience_modes,
    normalize_experience_mode,
)

KNOWN_MODE_IDS = [p.id for p in list_experience_modes()]
BDV_KEYS = ("RESPOND", "ACK_ONLY", "DEFER", "SILENCE")
MOP_OUTCOME_KEYS = ("laughed", "responded", "ignored", "changed_topic")
HOLD_BUCKETS_MS = (250, 300, 350, 400, 450)


def _empty_mode_row(mode_id: str) -> dict[str, Any]:
    profile = get_experience_profile(mode_id)
    return {
        "mode": mode_id,
        "display_name": profile.display_name,
        "turns": 0,
        "user_talk_ms": 0,
        "assistant_talk_ms": 0,
        "questions": 0,
        "interruptions": 0,
        "callback_surfaced": 0,
        "mop_selected_turns": 0,
        "mop_suppressed_events": 0,
        "bdv_distribution": {k: 0 for k in BDV_KEYS},
    }


def _round_s(ms: int) -> float:
    return round(max(0, ms) / 1000.0, 1)


def _pct(num: float, den: float) -> int:
    if den <= 0:
        return 0
    return int(round(100.0 * num / den))


def _normalize_bdv(raw: str | None) -> str:
    key = (raw or "UNKNOWN").strip().upper()
    if key in BDV_KEYS:
        return key
    return "OTHER"


def _nearest_hold_bucket(ms: int) -> int:
    if ms <= 0:
        return 0
    return min(HOLD_BUCKETS_MS, key=lambda b: abs(b - ms))


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _distribution_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    s = sorted(values)
    return {
        "n": len(s),
        "min": round(s[0], 2),
        "p25": round(_percentile(s, 0.25), 2),
        "median": round(_percentile(s, 0.5), 2),
        "p75": round(_percentile(s, 0.75), 2),
        "max": round(s[-1], 2),
    }


def _build_mode_distributions(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-mode session + turn distributions (consistency across sessions)."""
    session_from_summary: dict[tuple[str, str], dict[str, Any]] = {}
    session_acc: dict[tuple[str, str], dict[str, Any]] = {}

    turn_listening: dict[str, list[float]] = defaultdict(list)
    turn_assistant_s: dict[str, list[float]] = defaultdict(list)
    turn_questions: dict[str, list[float]] = defaultdict(list)

    for ev in events:
        ns = ev["namespace"]
        name = ev["event"]
        p = ev["payload"]
        if ns == "experience" and name == "session_summary":
            mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
            sid = str(p.get("session_id") or "")
            if mode in KNOWN_MODE_IDS and sid:
                session_from_summary[(mode, sid)] = p
            continue

        if ns == "experience" and name == "turn":
            mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
            if mode not in KNOWN_MODE_IDS:
                continue
            sid = str(p.get("session_id") or "").strip()
            if not sid:
                sid = ""
            key = (mode, sid) if sid else None
            user_ms = int(p.get("user_talk_duration_ms") or 0)
            asst_ms = int(p.get("assistant_duration_ms") or 0)
            if key:
                acc = session_acc.setdefault(
                    key,
                    {
                        "user_ms": 0,
                        "asst_ms": 0,
                        "questions": 0,
                        "turns": 0,
                        "mop_selected": 0,
                        "callback_surfaced": 0,
                    },
                )
                acc["user_ms"] += user_ms
                acc["asst_ms"] += asst_ms
                acc["questions"] += int(p.get("question_count") or 0)
                acc["turns"] += 1
            total = user_ms + asst_ms
            if total > 0:
                turn_listening[mode].append(100.0 * user_ms / total)
            turn_assistant_s[mode].append(asst_ms / 1000.0)
            turn_questions[mode].append(float(int(p.get("question_count") or 0)))

        if ns == "decision" and name == "turn_decision":
            mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
            sid = str(p.get("session_id") or "").strip()
            if mode in KNOWN_MODE_IDS and sid and p.get("mop_status") == "selected":
                key = (mode, sid)
                acc = session_acc.setdefault(
                    key,
                    {
                        "user_ms": 0,
                        "asst_ms": 0,
                        "questions": 0,
                        "turns": 0,
                        "mop_selected": 0,
                        "callback_surfaced": 0,
                    },
                )
                acc["mop_selected"] += 1

        if ns == "callback" and name == "callback_surfaced":
            mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
            sid = str(p.get("session_id") or "").strip()
            if mode in KNOWN_MODE_IDS and sid:
                key = (mode, sid)
                acc = session_acc.setdefault(
                    key,
                    {
                        "user_ms": 0,
                        "asst_ms": 0,
                        "questions": 0,
                        "turns": 0,
                        "mop_selected": 0,
                        "callback_surfaced": 0,
                    },
                )
                acc["callback_surfaced"] += 1

    out: dict[str, dict[str, Any]] = {}
    for mode in KNOWN_MODE_IDS:
        session_rows: list[dict[str, float]] = []
        for (m, sid), summary in session_from_summary.items():
            if m != mode:
                continue
            session_rows.append(
                {
                    "listening_percent": float(
                        summary.get("listening_percent")
                        or (float(summary.get("listening_ratio") or 0) * 100)
                    ),
                    "avg_assistant_s": float(summary.get("avg_assistant_s") or 0),
                    "questions": float(summary.get("questions") or 0),
                    "mop_percent": float(summary.get("mop_percent") or 0),
                    "callback_surfaced": float(summary.get("callback_surfaced") or 0),
                }
            )
        summarized_keys = {k for k in session_from_summary if k[0] == mode}
        for (m, sid), acc in session_acc.items():
            if m != mode or (m, sid) in summarized_keys or acc["turns"] <= 0:
                continue
            total = acc["user_ms"] + acc["asst_ms"]
            session_rows.append(
                {
                    "listening_percent": 100.0 * acc["user_ms"] / total if total else 0.0,
                    "avg_assistant_s": acc["asst_ms"] / acc["turns"] / 1000.0,
                    "questions": float(acc["questions"]),
                    "mop_percent": 100.0 * acc["mop_selected"] / acc["turns"],
                    "callback_surfaced": float(acc["callback_surfaced"]),
                }
            )

        out[mode] = {
            "session_count": len(session_rows),
            "sessions": {
                "listening_percent": _distribution_summary(
                    [r["listening_percent"] for r in session_rows]
                ),
                "avg_assistant_s": _distribution_summary(
                    [r["avg_assistant_s"] for r in session_rows]
                ),
                "questions": _distribution_summary([r["questions"] for r in session_rows]),
                "mop_percent": _distribution_summary([r["mop_percent"] for r in session_rows]),
                "callback_surfaced": _distribution_summary(
                    [r["callback_surfaced"] for r in session_rows]
                ),
            },
            "turns": {
                "listening_percent": _distribution_summary(turn_listening[mode]),
                "avg_assistant_s": _distribution_summary(turn_assistant_s[mode]),
                "questions": _distribution_summary(turn_questions[mode]),
            },
        }
    return out


def build_behavior_eval(events: list[dict[str, Any]]) -> dict[str, Any]:
    modes: dict[str, dict[str, Any]] = {m: _empty_mode_row(m) for m in KNOWN_MODE_IDS}

    global_bdv = {k: 0 for k in BDV_KEYS}
    global_bdv_followed: dict[str, int] = {k: 0 for k in BDV_KEYS}

    callback_surfaced_total = 0
    callback_engaged_total = 0
    mop_decision_selected = 0
    mop_decision_suppressed = 0
    mop_outcome_engaged = 0
    mop_outcome_total = 0

    mop_by_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "selected": 0,
            "laughed": 0,
            "responded": 0,
            "ignored": 0,
            "changed_topic": 0,
        }
    )

    hold_outcomes: dict[int, dict[str, int]] = {
        b: {"total": 0, "laughed": 0, "responded": 0, "ignored": 0, "changed_topic": 0}
        for b in HOLD_BUCKETS_MS
    }
    hold_outcomes_other: dict[str, int] = defaultdict(int)

    mop_punchlines = 0
    mop_reactions = 0
    mop_candidates = 0
    mop_suppressed_global = 0

    for ev in events:
        ns = ev["namespace"]
        name = ev["event"]
        p = ev["payload"]

        if ns == "experience" and name == "turn":
            mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
            row = modes.get(mode)
            if row is None:
                continue
            row["turns"] += 1
            user_ms = int(p.get("user_talk_duration_ms") or 0)
            asst_ms = int(p.get("assistant_duration_ms") or 0)
            row["user_talk_ms"] += user_ms
            row["assistant_talk_ms"] += asst_ms
            row["questions"] += int(p.get("question_count") or 0)
            if p.get("interruption"):
                row["interruptions"] += 1
            bdv = _normalize_bdv(str(p.get("bdv") or ""))
            if bdv in row["bdv_distribution"]:
                row["bdv_distribution"][bdv] += 1
                global_bdv[bdv] += 1
                if bdv == "RESPOND" and asst_ms > 0:
                    global_bdv_followed["RESPOND"] += 1
                elif bdv == "ACK_ONLY" and asst_ms > 0:
                    global_bdv_followed["ACK_ONLY"] += 1
                elif bdv == "DEFER" and asst_ms <= 0:
                    global_bdv_followed["DEFER"] += 1
                elif bdv == "SILENCE" and asst_ms <= 0:
                    global_bdv_followed["SILENCE"] += 1

        if ns == "callback":
            if name == "callback_surfaced":
                callback_surfaced_total += 1
                mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
                if mode in modes:
                    modes[mode]["callback_surfaced"] += 1
            elif name in ("callback_outcome", "callback_followed_up"):
                outcome = str(p.get("callback_outcome") or "")
                if outcome == "engaged":
                    callback_engaged_total += 1

        if ns == "mop":
            if name == "mop_candidate":
                mop_candidates += 1
            elif name == "mop_suppressed":
                mop_suppressed_global += 1
                mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
                if mode in modes:
                    modes[mode]["mop_suppressed_events"] += 1
            elif name == "mop_setup":
                mop_type = str(p.get("mop_type") or "unknown")
                mop_by_type[mop_type]["selected"] += 1
            elif name == "mop_punchline":
                mop_punchlines += 1
            elif name == "mop_reaction":
                if p.get("reaction") in {"laugh_short", "soft_laugh", "jedag"}:
                    mop_reactions += 1
            elif name == "mop_outcome":
                mop_outcome_total += 1
                outcome = str(p.get("outcome") or "")
                if outcome in ("laughed", "responded"):
                    mop_outcome_engaged += 1
                mop_type = str(p.get("mop_type") or "unknown")
                if outcome in MOP_OUTCOME_KEYS:
                    mop_by_type[mop_type][outcome] += 1
                planned = int(p.get("planned_hold_ms") or p.get("hold_ms") or 0)
                bucket = _nearest_hold_bucket(planned)
                if bucket in hold_outcomes and outcome in MOP_OUTCOME_KEYS:
                    hold_outcomes[bucket]["total"] += 1
                    hold_outcomes[bucket][outcome] += 1
                elif outcome:
                    hold_outcomes_other[outcome] += 1

        if ns == "decision" and name == "turn_decision":
            mode = normalize_experience_mode(str(p.get("experience_mode") or ""))
            mop_st = p.get("mop_status")
            if mop_st == "selected":
                mop_decision_selected += 1
                if mode in modes:
                    modes[mode]["mop_selected_turns"] += 1
            elif mop_st == "suppressed":
                mop_decision_suppressed += 1

    mode_table: list[dict[str, Any]] = []
    for mode_id in KNOWN_MODE_IDS:
        row = modes[mode_id]
        turns = int(row["turns"])
        user_ms = int(row["user_talk_ms"])
        asst_ms = int(row["assistant_talk_ms"])
        total_talk = user_ms + asst_ms
        listening_ratio = round(user_ms / total_talk, 4) if total_talk > 0 else 0.0
        mop_sel = int(row["mop_selected_turns"])
        mode_table.append(
            {
                "mode": mode_id,
                "display_name": row["display_name"],
                "turns": turns,
                "avg_assistant_s": round(asst_ms / turns / 1000.0, 1) if turns else 0.0,
                "avg_user_talk_s": round(user_ms / turns / 1000.0, 1) if turns else 0.0,
                "listening_percent": _pct(user_ms, total_talk),
                "listening_ratio": listening_ratio,
                "questions": int(row["questions"]),
                "questions_per_turn": round(row["questions"] / turns, 2) if turns else 0.0,
                "mop_percent": _pct(mop_sel, turns),
                "mop_selected_turns": mop_sel,
                "mop_suppressed_events": int(row["mop_suppressed_events"]),
                "callback_surfaced": int(row["callback_surfaced"]),
                "callback_surfaced_rate": _pct(row["callback_surfaced"], turns),
                "interruptions": int(row["interruptions"]),
                "bdv_distribution": dict(row["bdv_distribution"]),
            }
        )

    mode_table.sort(key=lambda r: r["turns"], reverse=True)

    decision_outcomes: list[dict[str, Any]] = []
    for key in BDV_KEYS:
        count = global_bdv[key]
        followed = global_bdv_followed[key]
        decision_outcomes.append(
            {
                "decision": key,
                "count": count,
                "followed_count": followed,
                "followed_percent": _pct(followed, count),
                "followed_label": "assistant spoke"
                if key in ("RESPOND", "ACK_ONLY")
                else "stayed quiet",
            }
        )
    decision_outcomes.append(
        {
            "decision": "CALLBACK surfaced",
            "count": callback_surfaced_total,
            "followed_count": callback_engaged_total,
            "followed_percent": _pct(callback_engaged_total, callback_surfaced_total),
            "followed_label": "engaged",
        }
    )
    decision_outcomes.append(
        {
            "decision": "MOP surfaced",
            "count": mop_decision_selected,
            "followed_count": mop_outcome_engaged,
            "followed_percent": _pct(mop_outcome_engaged, mop_decision_selected),
            "followed_label": "engaged (laughed/responded)",
        }
    )
    decision_outcomes.append(
        {
            "decision": "MOP suppressed",
            "count": max(mop_decision_suppressed, mop_suppressed_global),
            "followed_count": 0,
            "followed_percent": 0,
            "followed_label": "—",
        }
    )

    mop_type_rows: list[dict[str, Any]] = []
    for mop_type in sorted(mop_by_type.keys()):
        bucket = mop_by_type[mop_type]
        engaged = bucket["laughed"] + bucket["responded"]
        total_out = sum(bucket[k] for k in MOP_OUTCOME_KEYS)
        mop_type_rows.append(
            {
                "mop_type": mop_type,
                "selected": bucket["selected"],
                "engaged": engaged,
                "ignored": bucket["ignored"],
                "redirected": bucket["changed_topic"],
                "outcome_total": total_out,
            }
        )

    planned_hold_rows: list[dict[str, Any]] = []
    for ms in HOLD_BUCKETS_MS:
        bucket = hold_outcomes[ms]
        total = bucket["total"]
        engaged = bucket["laughed"] + bucket["responded"]
        planned_hold_rows.append(
            {
                "planned_hold_ms": ms,
                "total": total,
                "engaged_percent": _pct(engaged, total),
                "outcomes": {k: bucket[k] for k in MOP_OUTCOME_KEYS},
            }
        )

    distributions = _build_mode_distributions(events)
    for row in mode_table:
        row["distributions"] = distributions.get(row["mode"], {})

    mode_health = [evaluate_mode_contract(row) for row in mode_table]
    health_by_mode = {h["mode"]: h for h in mode_health}
    mode_table_with_tuning = [
        eval_row_with_tuning(row, health_by_mode.get(row["mode"], {})) for row in mode_table
    ]

    return {
        "mode_table": mode_table_with_tuning,
        "bdv_by_mode": {r["mode"]: r["bdv_distribution"] for r in mode_table},
        "decision_outcomes": decision_outcomes,
        "mop_by_type": mop_type_rows,
        "planned_hold_outcomes": planned_hold_rows,
        "planned_hold_label": "Planned Hold → Outcome (not actual phase duration)",
        "mode_health": mode_health,
        "tuning_mode_order": list(TUNING_MODE_ORDER),
        "mop_delivery": {
            "punchlines": mop_punchlines,
            "reactions": mop_reactions,
            "reaction_delivery_percent": _pct(mop_reactions, mop_punchlines),
        },
    }
