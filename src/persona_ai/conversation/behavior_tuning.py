"""Sprint G — explicit behavior contracts, median-based eval, one-lever experiments.

INVARIANT: This module NEVER mutates runtime config. Humans change one lever;
telemetry + eval judge keep vs revert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TuningStatus = Literal["ok", "needs_tuning", "insufficient_data"]

MIN_TURNS_FOR_CONTRACT = 3
MIN_SESSIONS_FOR_MEDIAN = 2

# Recommended tuning order (clearest contracts first).
TUNING_MODE_ORDER: tuple[str, ...] = (
    "cerita_tong",
    "teman_jalan",
    "mop",
    "teman_malam",
    "nongkrong",
)


@dataclass(frozen=True)
class ContractRule:
    metric: str
    op: str  # gte | lte | eq
    target: float
    label: str
    lever_hint: str


MODE_BEHAVIOR_CONTRACTS: dict[str, tuple[ContractRule, ...]] = {
    "cerita_tong": (
        ContractRule(
            "listening_median",
            "gte",
            60.0,
            "Listening median ≥ 60%",
            "behavior.defer_bias OR behavior.question_budget (one only)",
        ),
        ContractRule(
            "questions_median",
            "lte",
            2.0,
            "Questions median / sesi ≤ 2",
            "behavior.question_budget (e.g. 1 → 0)",
        ),
        ContractRule(
            "mop_median",
            "lte",
            5.0,
            "MOP rate median ≤ 5%",
            "verify mode + mop_frequency off",
        ),
        ContractRule(
            "assistant_median",
            "lte",
            2.0,
            "Assistant median ≤ 2.0 s",
            "live.max_response_words (lower)",
        ),
        ContractRule(
            "interruptions_total",
            "eq",
            0.0,
            "Interruptions = 0",
            "interruption_policy / BDV defer",
        ),
    ),
    "teman_jalan": (
        ContractRule(
            "assistant_median",
            "lte",
            2.0,
            "Assistant median ≤ 2.0 s",
            "live.max_response_words",
        ),
        ContractRule(
            "questions_median",
            "lte",
            1.0,
            "Questions median / sesi ≤ 1",
            "behavior.question_budget",
        ),
        ContractRule(
            "callback_surfaced_total",
            "eq",
            0.0,
            "Callback surfaced = 0",
            "callback.enabled (must stay false)",
        ),
        ContractRule(
            "mop_median",
            "eq",
            0.0,
            "MOP rate median = 0%",
            "verify experience mode id",
        ),
    ),
    "mop": (
        ContractRule(
            "mop_median",
            "gte",
            15.0,
            "MOP selection median ≥ 15%",
            "mop frequency / engagement gate (one threshold)",
        ),
        ContractRule(
            "mop_suppression_events",
            "gte",
            1.0,
            "Suppression events present",
            "do not disable cooldown — verify gate",
        ),
        ContractRule(
            "assistant_median",
            "gte",
            1.5,
            "Assistant median ≥ 1.5 s",
            "max_response_words (only if too short)",
        ),
    ),
    "teman_malam": (
        ContractRule(
            "listening_median",
            "gte",
            55.0,
            "Listening median ≥ 55%",
            "behavior.warmth_bias OR defer (one)",
        ),
        ContractRule(
            "questions_median",
            "lte",
            2.0,
            "Questions median / sesi ≤ 2",
            "behavior.question_budget",
        ),
        ContractRule(
            "mop_median",
            "lte",
            10.0,
            "MOP rate median ≤ 10%",
            "mop_frequency very_low threshold",
        ),
    ),
    "nongkrong": (
        ContractRule(
            "listening_median",
            "gte",
            40.0,
            "Listening median ≥ 40%",
            "ack_bias OR question_budget (one)",
        ),
        ContractRule(
            "listening_median",
            "lte",
            70.0,
            "Listening median ≤ 70%",
            "defer_bias (one step)",
        ),
        ContractRule(
            "mop_median",
            "lte",
            25.0,
            "MOP rate median ≤ 25%",
            "mop frequency low gate",
        ),
    ),
}


def mode_metrics_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Metrics for experiment before/after — median + p25/p75 primary."""
    dist = row.get("distributions") or {}
    sess = dist.get("sessions") or {}
    listen = sess.get("listening_percent") or {}
    questions = sess.get("questions") or {}
    mop = sess.get("mop_percent") or {}
    assistant = sess.get("avg_assistant_s") or {}
    callback = sess.get("callback_surfaced") or {}
    return {
        "session_count": int(dist.get("session_count") or 0),
        "turns": int(row.get("turns") or 0),
        "listening_median": listen.get("median"),
        "listening_p25": listen.get("p25"),
        "listening_p75": listen.get("p75"),
        "questions_median": questions.get("median"),
        "questions_p25": questions.get("p25"),
        "questions_p75": questions.get("p75"),
        "mop_median": mop.get("median"),
        "mop_p25": mop.get("p25"),
        "mop_p75": mop.get("p75"),
        "assistant_median": assistant.get("median"),
        "assistant_p25": assistant.get("p25"),
        "assistant_p75": assistant.get("p75"),
        "callback_median": callback.get("median"),
        "interruptions_total": int(row.get("interruptions") or 0),
        "callback_surfaced_total": int(row.get("callback_surfaced") or 0),
        "mop_suppression_events": int(row.get("mop_suppressed_events") or 0),
        # Averages kept for display only — not contract primary signal.
        "listening_avg": int(row.get("listening_percent") or 0),
        "questions_total": int(row.get("questions") or 0),
        "mop_avg_percent": int(row.get("mop_percent") or 0),
        "assistant_avg_s": float(row.get("avg_assistant_s") or 0),
    }


def _metric_value(snapshot: dict[str, Any], metric: str) -> float | None:
    raw = snapshot.get(metric)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _check_rule(snapshot: dict[str, Any], rule: ContractRule) -> tuple[bool, str]:
    val = _metric_value(snapshot, rule.metric)
    if val is None:
        return False, "no median data"
    if rule.op == "gte":
        passed = val >= rule.target
    elif rule.op == "lte":
        passed = val <= rule.target
    else:
        passed = val == rule.target
    band = ""
    if rule.metric == "listening_median":
        p25, p75 = snapshot.get("listening_p25"), snapshot.get("listening_p75")
        if p25 is not None and p75 is not None:
            band = f" (p25–p75: {p25}–{p75}%)"
    detail = f"{val}{band}" if "median" in rule.metric or "total" in rule.metric else str(val)
    if rule.metric == "assistant_median" and snapshot.get("assistant_p25") is not None:
        detail = (
            f"{val}s (p25–p75: {snapshot.get('assistant_p25')}–"
            f"{snapshot.get('assistant_p75')}s)"
        )
    return passed, detail


def evaluate_mode_contract(row: dict[str, Any]) -> dict[str, Any]:
    mode = str(row.get("mode") or "")
    turns = int(row.get("turns") or 0)
    snapshot = mode_metrics_snapshot(row)
    session_count = int(snapshot.get("session_count") or 0)
    rules = MODE_BEHAVIOR_CONTRACTS.get(mode, ())

    checks: list[dict[str, Any]] = []
    failed_levers: list[str] = []
    ok = True

    if turns < MIN_TURNS_FOR_CONTRACT or session_count < MIN_SESSIONS_FOR_MEDIAN:
        for rule in rules:
            checks.append(
                {
                    "label": rule.label,
                    "ok": None,
                    "detail": f"need ≥{MIN_TURNS_FOR_CONTRACT} turns & ≥{MIN_SESSIONS_FOR_MEDIAN} sesi",
                    "lever_hint": rule.lever_hint,
                }
            )
        return {
            "mode": mode,
            "display_name": row.get("display_name") or mode,
            "turns": turns,
            "session_count": session_count,
            "contract_ok": None,
            "checks": checks,
            "metrics_snapshot": snapshot,
            "signal": "median_p25_p75",
        }

    for rule in rules:
        passed, detail = _check_rule(snapshot, rule)
        if not passed:
            ok = False
            failed_levers.append(rule.lever_hint)
        checks.append(
            {
                "label": rule.label,
                "ok": passed,
                "detail": detail,
                "lever_hint": rule.lever_hint,
            }
        )

    return {
        "mode": mode,
        "display_name": row.get("display_name") or mode,
        "turns": turns,
        "session_count": session_count,
        "contract_ok": ok,
        "checks": checks,
        "metrics_snapshot": snapshot,
        "failed_lever_hints": failed_levers,
        "signal": "median_p25_p75",
    }


def tuning_status(*, turns: int, session_count: int, contract_ok: bool | None) -> TuningStatus:
    if turns < MIN_TURNS_FOR_CONTRACT or session_count < MIN_SESSIONS_FOR_MEDIAN:
        return "insufficient_data"
    if contract_ok is True:
        return "ok"
    if contract_ok is False:
        return "needs_tuning"
    return "insufficient_data"


def tuning_note(mode: str, status: TuningStatus, health: dict[str, Any] | None = None) -> str:
    if status == "ok":
        return "Kontrak terpenuhi (median sesi) — jangan disentuh."
    if status == "insufficient_data":
        return (
            f"Data belum cukup — kumpulkan ≥{MIN_TURNS_FOR_CONTRACT} turn dan "
            f"≥{MIN_SESSIONS_FOR_MEDIAN} sesi per mode."
        )
    hints = (health or {}).get("failed_lever_hints") or []
    if hints:
        return f"NEEDS_TUNING — satu lever: {hints[0]}"
    return "NEEDS_TUNING — ubah satu variabel behavior, lalu sesi baru + bandingkan distribusi."


def eval_row_with_tuning(row: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    session_count = int(health.get("session_count") or 0)
    status = tuning_status(
        turns=int(row.get("turns") or 0),
        session_count=session_count,
        contract_ok=health.get("contract_ok"),
    )
    return {
        **row,
        "tuning_status": status,
        "tuning_note": tuning_note(str(row.get("mode") or ""), status, health),
    }


def snapshot_for_mode(mode_table: list[dict[str, Any]], mode_id: str) -> dict[str, Any] | None:
    for row in mode_table:
        if row.get("mode") == mode_id:
            return mode_metrics_snapshot(row)
    return None
