"""CLI helper to append human eval scores — does not touch experiment outputs."""

from __future__ import annotations

from persona_ai.eval.human_eval import HumanEvalScores, default_eval_store, record_human_eval


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Record one human eval judgment (append-only)")
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--naturalness", type=int, required=True)
    parser.add_argument("--timing", type=int, required=True)
    parser.add_argument("--intrusiveness", type=int, required=True)
    parser.add_argument("--emotional-fit", type=int, required=True)
    parser.add_argument("--preference", choices=["A", "B", "tie"], required=True)
    parser.add_argument("--reviewer-id", default="anonymous")
    parser.add_argument("--store", default=str(default_eval_store()))
    args = parser.parse_args()

    for name, value in (
        ("naturalness", args.naturalness),
        ("timing", args.timing),
        ("intrusiveness", args.intrusiveness),
        ("emotional_fit", args.emotional_fit),
    ):
        if not 1 <= value <= 7:
            raise SystemExit(f"{name} must be 1–7, got {value}")

    record_human_eval(
        HumanEvalScores(
            pair_id=args.pair_id,
            scenario_id=args.scenario_id,
            naturalness=args.naturalness,
            timing=args.timing,
            intrusiveness=args.intrusiveness,
            emotional_fit=args.emotional_fit,
            preference=args.preference,
            reviewer_id=args.reviewer_id,
        ),
        store_path=__import__("pathlib").Path(args.store),
    )
    print(f"Recorded judgment for pair {args.pair_id} → {args.store}")


if __name__ == "__main__":
    main()
