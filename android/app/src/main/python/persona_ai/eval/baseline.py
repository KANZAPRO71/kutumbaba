"""North Star baseline workflow — prepare artifacts and track human eval progress."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_ai.eval.human_eval import generate_blind_pairs, load_human_evals, reviewer_form
from persona_ai.eval.ab_experiment import run_experiment, write_experiment_report
from persona_ai.llm.adapter import LLMAdapter
from persona_ai.personality.preset import load_preset_by_id, read_preset_json

DEFAULT_EVAL_DIR = Path(".persona_ai") / "eval"
DEFAULT_RESULTS = DEFAULT_EVAL_DIR / "ab_results.json"
DEFAULT_MANIFEST = DEFAULT_EVAL_DIR / "blind_pairs_manifest.json"
DEFAULT_FORMS = DEFAULT_EVAL_DIR / "reviewer_forms.json"
DEFAULT_SCORES = DEFAULT_EVAL_DIR / "human_scores.jsonl"
DEFAULT_METADATA = DEFAULT_EVAL_DIR / "baseline_metadata.json"

SCENARIOS_COUNT = 10
REVIEWERS_PER_SCENARIO = 5
TARGET_JUDGMENTS = SCENARIOS_COUNT * REVIEWERS_PER_SCENARIO


def default_paths() -> dict[str, Path]:
    return {
        "results": DEFAULT_RESULTS,
        "manifest": DEFAULT_MANIFEST,
        "forms": DEFAULT_FORMS,
        "scores": DEFAULT_SCORES,
        "metadata": DEFAULT_METADATA,
    }


def build_gemini_adapter():
    """Load Gemini adapter — raises if credentials missing."""
    from persona_ai.llm.gemini import DEFAULT_GEMINI_MODEL, GeminiLLMAdapter

    return GeminiLLMAdapter(), DEFAULT_GEMINI_MODEL


def write_baseline_metadata(
    path: Path,
    *,
    preset_id: str,
    model: str,
    scenario_count: int,
    seed: int,
    adapter_kind: str,
) -> dict[str, Any]:
    preset_doc = read_preset_json(f"{preset_id}.json")
    payload = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "north_star_baseline_v1",
        "preset_id": preset_id,
        "preset_version": preset_doc.get("version"),
        "preset_schema_version": preset_doc.get("schema_version"),
        "gemini_model": model,
        "adapter_kind": adapter_kind,
        "scenario_count": scenario_count,
        "target_judgments": TARGET_JUDGMENTS,
        "reviewers_per_scenario": REVIEWERS_PER_SCENARIO,
        "blind_pair_seed": seed,
        "control": "GeminiDirectClient",
        "treatment": "PersonaEvalClient",
        "frozen_fields": [
            "presets/default_companion.json",
            "behavior/decide thresholds",
            "prompt wording",
            "GEMINI_MODEL",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def prepare_baseline(
    *,
    preset_id: str = "default_companion",
    adapter: LLMAdapter | None = None,
    seed: int = 42,
    paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Run frozen A/B outputs and generate blind reviewer artifacts."""
    import random

    loc = paths or default_paths()
    if adapter is None:
        adapter, model = build_gemini_adapter()
        adapter_kind = "GeminiLLMAdapter"
    else:
        model = getattr(adapter, "model", type(adapter).__name__)
        adapter_kind = type(adapter).__name__

    # Touch preset loader so invalid preset fails early.
    load_preset_by_id(preset_id)

    results = run_experiment(
        control_adapter=adapter,
        treatment_adapter=adapter,
        preset_id=preset_id,
    )
    write_experiment_report(results, loc["results"])

    pairs = generate_blind_pairs(
        results,
        rng=random.Random(seed),
        manifest_path=loc["manifest"],
    )
    forms = [reviewer_form(pair) for pair in pairs]
    loc["forms"].parent.mkdir(parents=True, exist_ok=True)
    loc["forms"].write_text(json.dumps(forms, indent=2, ensure_ascii=False), encoding="utf-8")

    metadata = write_baseline_metadata(
        loc["metadata"],
        preset_id=preset_id,
        model=model,
        scenario_count=len(results),
        seed=seed,
        adapter_kind=adapter_kind,
    )

    governance_scenarios = [
        row["scenario_id"]
        for row in results
        if row.get("bdv") in ("SILENCE", "DEFER", "ACK_ONLY")
    ]

    return {
        "metadata": metadata,
        "scenario_count": len(results),
        "pair_count": len(pairs),
        "governance_scenario_ids": governance_scenarios,
        "paths": {key: str(path) for key, path in loc.items()},
    }


def baseline_status(
    *,
    paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Report artifact readiness and human score progress toward 50 judgments."""
    loc = paths or default_paths()
    status: dict[str, Any] = {
        "target_judgments": TARGET_JUDGMENTS,
        "artifacts": {},
        "human_scores": {"count": 0, "unique_reviewers": 0, "by_scenario": {}},
        "ready_for_analysis": False,
    }

    for key in ("metadata", "results", "manifest", "forms"):
        path = loc[key]
        status["artifacts"][key] = {"path": str(path), "exists": path.is_file()}

    scores = load_human_evals(loc["scores"])
    status["human_scores"]["count"] = len(scores)
    reviewers = {row.get("reviewer_id", "anonymous") for row in scores}
    status["human_scores"]["unique_reviewers"] = len(reviewers)

    by_scenario: dict[str, int] = {}
    for row in scores:
        sid = row.get("scenario_id")
        if sid:
            by_scenario[sid] = by_scenario.get(sid, 0) + 1
    status["human_scores"]["by_scenario"] = by_scenario

    all_artifacts = all(status["artifacts"][k]["exists"] for k in ("metadata", "results", "manifest", "forms"))
    status["ready_for_analysis"] = all_artifacts and len(scores) >= TARGET_JUDGMENTS
    status["judgments_remaining"] = max(0, TARGET_JUDGMENTS - len(scores))
    return status


def format_status_report(status: dict[str, Any]) -> str:
    lines = ["# Baseline Status", ""]
    hs = status["human_scores"]
    lines.append(f"Human judgments: {hs['count']}/{status['target_judgments']}")
    lines.append(f"Remaining: {status['judgments_remaining']}")
    lines.append(f"Unique reviewers: {hs['unique_reviewers']}")
    lines.append(f"Ready for analysis: {status['ready_for_analysis']}")
    lines.append("")
    lines.append("Artifacts:")
    for key, row in status["artifacts"].items():
        mark = "ok" if row["exists"] else "MISSING"
        lines.append(f"  [{mark}] {key}: {row['path']}")
    if hs["by_scenario"]:
        lines.append("")
        lines.append("Scores by scenario:")
        for sid, count in sorted(hs["by_scenario"].items()):
            lines.append(f"  {sid}: {count}/{REVIEWERS_PER_SCENARIO}")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="North Star baseline — prepare and track human eval")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="Run Gemini A/B and generate blind reviewer artifacts")
    prep.add_argument("--preset", default="default_companion")
    prep.add_argument("--seed", type=int, default=42, help="Blind pair order seed")
    prep.add_argument("--output-dir", default=str(DEFAULT_EVAL_DIR))

    stat = sub.add_parser("status", help="Show progress toward 50 human judgments")
    stat.add_argument("--output-dir", default=str(DEFAULT_EVAL_DIR))
    stat.add_argument("--json", action="store_true")

    args = parser.parse_args()
    base = Path(args.output_dir)
    paths = {
        "results": base / "ab_results.json",
        "manifest": base / "blind_pairs_manifest.json",
        "forms": base / "reviewer_forms.json",
        "scores": base / "human_scores.jsonl",
        "metadata": base / "baseline_metadata.json",
    }

    if args.command == "prepare":
        summary = prepare_baseline(
            preset_id=args.preset,
            seed=args.seed,
            paths=paths,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    if args.command == "status":
        result = baseline_status(paths=paths)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_status_report(result))


if __name__ == "__main__":
    main()
