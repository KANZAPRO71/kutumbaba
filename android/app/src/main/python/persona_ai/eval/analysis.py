"""Post-experiment analysis — per-scenario scores and governance win rate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

Preference = Literal["A", "B", "tie"]

GOVERNANCE_BDV = frozenset({"SILENCE", "DEFER", "ACK_ONLY"})
METRICS = ("naturalness", "timing", "intrusiveness", "emotional_fit")


def load_scenario_results(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("scenario results must be a JSON array")
    return data


def load_blind_pairs_manifest(path: str | Path) -> dict[str, dict[str, Any]]:
    """Analyst-only mapping: pair_id -> {scenario_id, a_is_treatment, ...}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {row["pair_id"]: row for row in data}
    if isinstance(data, dict) and "pairs" in data:
        return {row["pair_id"]: row for row in data["pairs"]}
    raise ValueError("blind pairs manifest must be a list or {pairs: [...]}")


def save_blind_pairs_manifest(pairs: list[Any], path: str | Path) -> Path:
    """Persist analyst manifest — never share with reviewers."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = []
    for pair in pairs:
        payload.append(
            {
                "pair_id": pair.pair_id,
                "scenario_id": pair.scenario_id,
                "a_is_treatment": pair.a_is_treatment,
            }
        )
    out.write_text(json.dumps({"pairs": payload}, indent=2), encoding="utf-8")
    return out


def persona_governance_applied(scenario_row: dict[str, Any]) -> bool:
    """True when Persona BDV materially differs from control (always RESPOND+LLM)."""
    bdv = (scenario_row.get("bdv") or "").upper()
    if bdv in GOVERNANCE_BDV:
        return True
    if scenario_row.get("treatment_llm_called") is False and scenario_row.get("control_text"):
        return True
    treatment = scenario_row.get("treatment_text")
    control = scenario_row.get("control_text")
    if treatment != control and (treatment is None or control is None):
        return True
    return False


def reviewer_prefers_treatment(
    preference: Preference,
    *,
    a_is_treatment: bool,
) -> bool:
    if preference == "tie":
        return False
    if preference == "A":
        return a_is_treatment
    if preference == "B":
        return not a_is_treatment
    return False


def treatment_score_delta(
    score_row: dict[str, Any],
    *,
    a_is_treatment: bool,
    metric: str,
) -> int | None:
    """Positive => reviewer scored treatment higher on this metric."""
    value = score_row.get(metric)
    if not isinstance(value, int):
        return None
    other_key = f"{metric}_b" if metric in score_row else None
    if other_key and isinstance(score_row.get(other_key), int):
        a_val = value
        b_val = score_row[other_key]
    else:
        return None
    if a_is_treatment:
        return a_val - b_val
    return b_val - a_val


def _resolve_preference(score_row: dict[str, Any], pair_manifest: dict[str, Any]) -> Preference | None:
    pref = score_row.get("preference")
    if pref not in ("A", "B", "tie"):
        return None
    return pref


def analyze_experiment(
    scenario_results: list[dict[str, Any]],
    human_scores: list[dict[str, Any]],
    pair_manifest: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Per-scenario breakdown + governance win rate."""
    scenario_by_id = {row["scenario_id"]: row for row in scenario_results}
    per_scenario: dict[str, Any] = {}

    for scenario_id, scenario_row in scenario_by_id.items():
        scenario_scores = [s for s in human_scores if s.get("scenario_id") == scenario_id]
        prefs = {"treatment": 0, "control": 0, "tie": 0}
        metric_deltas: dict[str, list[float]] = {m: [] for m in METRICS}

        for score_row in scenario_scores:
            pair_id = score_row.get("pair_id")
            if not pair_id or pair_id not in pair_manifest:
                continue
            manifest = pair_manifest[pair_id]
            a_is_treatment = bool(manifest.get("a_is_treatment"))
            pref = _resolve_preference(score_row, manifest)
            if pref == "tie":
                prefs["tie"] += 1
            elif reviewer_prefers_treatment(pref, a_is_treatment=a_is_treatment):
                prefs["treatment"] += 1
            elif pref in ("A", "B"):
                prefs["control"] += 1

        per_scenario[scenario_id] = {
            "governance_applied": persona_governance_applied(scenario_row),
            "bdv": scenario_row.get("bdv"),
            "reviewer_count": len(scenario_scores),
            "preference": prefs,
            "metrics": {},
        }

    governance_wins = 0
    governance_total = 0
    overall_wins = 0
    overall_total = 0
    for scenario_id, scenario_row in scenario_by_id.items():
        if not persona_governance_applied(scenario_row):
            continue
        scenario_scores = [s for s in human_scores if s.get("scenario_id") == scenario_id]
        for score_row in scenario_scores:
            pair_id = score_row.get("pair_id")
            if not pair_id or pair_id not in pair_manifest:
                continue
            manifest = pair_manifest[pair_id]
            pref = _resolve_preference(score_row, manifest)
            if pref is None or pref == "tie":
                continue
            governance_total += 1
            if reviewer_prefers_treatment(pref, a_is_treatment=bool(manifest.get("a_is_treatment"))):
                governance_wins += 1

    for score_row in human_scores:
        pair_id = score_row.get("pair_id")
        if not pair_id or pair_id not in pair_manifest:
            continue
        pref = _resolve_preference(score_row, pair_manifest[pair_id])
        if pref is None or pref == "tie":
            continue
        overall_total += 1
        manifest = pair_manifest[pair_id]
        if reviewer_prefers_treatment(pref, a_is_treatment=bool(manifest.get("a_is_treatment"))):
            overall_wins += 1

    return {
        "per_scenario": per_scenario,
        "governance_win_rate": {
            "wins": governance_wins,
            "total_judgments": governance_total,
            "rate": governance_wins / governance_total if governance_total else None,
            "description": "Persona preferred / non-tie judgments when governance differs (SILENCE, DEFER, ACK_ONLY)",
        },
        "overall_preference": {
            "wins": overall_wins,
            "total_judgments": overall_total,
            "rate": overall_wins / overall_total if overall_total else None,
            "description": "Persona preferred / all non-tie judgments",
        },
        "total_human_judgments": len(human_scores),
        "target_judgments": len(scenario_results) * 5,
    }


def format_analysis_report(analysis: dict[str, Any]) -> str:
    lines = ["# Persona A/B Analysis", ""]
    gwr = analysis.get("governance_win_rate", {})
    rate = gwr.get("rate")
    lines.append("## Primary: Governance Win Rate")
    lines.append(gwr.get("description", ""))
    lines.append(
        f"  {gwr.get('wins', 0)}/{gwr.get('total_judgments', 0)}"
        + (f" ({rate:.1%})" if rate is not None else " (n/a)")
    )
    lines.append("")
    ovr = analysis.get("overall_preference", {})
    o_rate = ovr.get("rate")
    lines.append("## Secondary: Overall Preference")
    lines.append(
        f"  {ovr.get('wins', 0)}/{ovr.get('total_judgments', 0)}"
        + (f" ({o_rate:.1%})" if o_rate is not None else " (n/a)")
    )
    lines.append(
        f"\nHuman judgments: {analysis.get('total_human_judgments', 0)}"
        f" / target {analysis.get('target_judgments', 0)}"
    )
    lines.append("")
    for scenario_id, row in analysis.get("per_scenario", {}).items():
        lines.append(f"## {scenario_id}")
        lines.append(f"  governance_applied: {row.get('governance_applied')}  bdv: {row.get('bdv')}")
        pref = row.get("preference", {})
        lines.append(
            f"  preference: Persona {pref.get('treatment', 0)} / "
            f"Control {pref.get('control', 0)} / Tie {pref.get('tie', 0)}"
        )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Analyze Persona blind A/B human evaluation")
    parser.add_argument(
        "--results",
        default=".persona_ai/eval/ab_results.json",
        help="Scenario control/treatment outputs",
    )
    parser.add_argument(
        "--scores",
        default=".persona_ai/eval/human_scores.jsonl",
        help="Human reviewer scores",
    )
    parser.add_argument(
        "--pairs",
        default=".persona_ai/eval/blind_pairs_manifest.json",
        help="Analyst-only A/B mapping",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text report")
    args = parser.parse_args()

    from persona_ai.eval.human_eval import load_human_evals

    scenario_results = load_scenario_results(args.results)
    human_scores = load_human_evals(Path(args.scores))
    pair_manifest = load_blind_pairs_manifest(args.pairs)
    analysis = analyze_experiment(scenario_results, human_scores, pair_manifest)

    if args.json:
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
    else:
        print(format_analysis_report(analysis))


if __name__ == "__main__":
    main()
