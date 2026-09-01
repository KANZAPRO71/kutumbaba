"""Human blind A/B evaluation support — separate from runtime sessions."""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Preference = Literal["A", "B", "tie"]


@dataclass
class BlindPair:
    pair_id: str
    scenario_id: str
    transcript_a: str
    transcript_b: str
    a_is_treatment: bool


@dataclass
class HumanEvalScores:
    pair_id: str
    scenario_id: str
    naturalness: int
    timing: int
    intrusiveness: int
    emotional_fit: int
    preference: Preference
    reviewer_id: str = "anonymous"
    recorded_at: str = ""


def default_eval_store() -> Path:
    return Path(".persona_ai") / "eval" / "human_scores.jsonl"


def generate_blind_pairs(
    scenario_results: list[dict[str, Any]],
    *,
    rng: random.Random | None = None,
    manifest_path: str | Path | None = None,
) -> list[BlindPair]:
    """Create blind A/B transcript pairs with randomized order."""
    rng = rng or random.Random(42)
    pairs: list[BlindPair] = []
    for item in scenario_results:
        control = item.get("control_text") or ""
        treatment = item.get("treatment_text") or ""
        if not control and not treatment:
            continue
        a_is_treatment = rng.choice([True, False])
        if a_is_treatment:
            transcript_a, transcript_b = treatment, control
        else:
            transcript_a, transcript_b = control, treatment
        pairs.append(
            BlindPair(
                pair_id=str(uuid.uuid4()),
                scenario_id=item["scenario_id"],
                transcript_a=transcript_a,
                transcript_b=transcript_b,
                a_is_treatment=a_is_treatment,
            )
        )
    if manifest_path is not None:
        from persona_ai.eval.analysis import save_blind_pairs_manifest

        save_blind_pairs_manifest(pairs, manifest_path)
    return pairs


def reviewer_form(pair: BlindPair) -> dict[str, Any]:
    """Reviewer-facing form — does not reveal control vs treatment."""
    return {
        "pair_id": pair.pair_id,
        "scenario_id": pair.scenario_id,
        "transcript_a": pair.transcript_a,
        "transcript_b": pair.transcript_b,
        "instructions": (
            "Score each dimension 1-7. Choose overall preference A, B, or tie. "
            "You are not told which system produced A or B."
        ),
        "fields": [
            "naturalness",
            "timing",
            "intrusiveness",
            "emotional_fit",
            "preference",
        ],
    }


def record_human_eval(
    scores: HumanEvalScores,
    *,
    store_path: Path | None = None,
) -> None:
    path = store_path or default_eval_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(scores)
    if not payload.get("recorded_at"):
        payload["recorded_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_human_evals(store_path: Path | None = None) -> list[dict[str, Any]]:
    path = store_path or default_eval_store()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def summarize_human_evals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    metrics = ("naturalness", "timing", "intrusiveness", "emotional_fit")
    summary: dict[str, Any] = {"count": len(rows), "metrics": {}, "preference": {}}
    for metric in metrics:
        values = [row[metric] for row in rows if isinstance(row.get(metric), int)]
        summary["metrics"][metric] = {
            "mean": sum(values) / len(values) if values else None,
            "n": len(values),
        }
    prefs = [row.get("preference") for row in rows if row.get("preference")]
    summary["preference"] = {
        "A": prefs.count("A"),
        "B": prefs.count("B"),
        "tie": prefs.count("tie"),
        "n": len(prefs),
    }
    return summary
