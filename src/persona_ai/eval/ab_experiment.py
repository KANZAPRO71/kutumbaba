"""Control-group A/B experiment harness — Persona vs Gemini direct."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from persona_ai.core.types import Message, ResponseLength, TurnHistory
from persona_ai.eval.scenarios import SCENARIOS, EvalScenario
from persona_ai.integrations.gemini_direct import GeminiDirectClient
from persona_ai.integrations.persona_eval import PersonaEvalClient
from persona_ai.llm.adapter import LLMAdapter, default_adapter
from persona_ai.session.models import SessionState


class ControlClient(Protocol):
    model_name: str

    def seed_history(self, session_id: str, messages: list[Message]) -> None: ...

    def process_turn(self, session_id: str, user_text: str) -> str: ...


@dataclass
class ScenarioRunResult:
    scenario_id: str
    control_text: str | None
    treatment_text: str | None
    bdv: str | None
    control_model: str
    treatment_model: str
    persona_preset: str
    metrics: tuple[str, ...]
    treatment_llm_called: bool | None = None


def _seed_treatment_session(client: PersonaEvalClient, session_id: str, scenario: EvalScenario) -> None:
    if not scenario.seed_assistant_text:
        return
    store = client.runtime.session_store
    session = store.load(session_id) or SessionState.new(
        session_id,
        profile_warmth=client.runtime.personality_profile.warmth,
    )
    session.messages.append(Message.from_text("assistant", scenario.seed_assistant_text))
    session.turn_history = TurnHistory(
        last_speaker="assistant",
        last_assistant_word_count=len(scenario.seed_assistant_text.split()),
        last_assistant_verbosity=ResponseLength.EXPAND,
        consecutive_assistant_turns=1,
    )
    store.save(session)


def _seed_control_history(client: GeminiDirectClient, session_id: str, scenario: EvalScenario) -> None:
    if not scenario.seed_assistant_text:
        return
    client.seed_history(
        session_id,
        [
            Message.from_text("assistant", scenario.seed_assistant_text),
        ],
    )


def _treatment_kwargs(scenario: EvalScenario, user_text: str) -> dict[str, object]:
    for text, kwargs in scenario.treatment_turn_kwargs:
        if text == user_text:
            return dict(kwargs)
    return {}


def run_scenario(
    scenario: EvalScenario,
    *,
    control: ControlClient,
    treatment: PersonaEvalClient,
    session_prefix: str = "persona-ab",
) -> ScenarioRunResult:
    control_sid = f"{session_prefix}-control-{scenario.scenario_id}"
    treatment_sid = f"{session_prefix}-treatment-{scenario.scenario_id}"

    _seed_control_history(control, control_sid, scenario)
    _seed_treatment_session(treatment, treatment_sid, scenario)

    control_text: str | None = None
    treatment_text: str | None = None
    bdv_action: str | None = None
    treatment_llm_called: bool | None = None

    for index, user_text in enumerate(scenario.user_turns):
        t_kwargs = _treatment_kwargs(scenario, user_text)
        if index == len(scenario.user_turns) - 1:
            control_text = control.process_turn(control_sid, user_text)
            out = treatment.process_turn(treatment_sid, user_text, **t_kwargs)
            treatment_text = out.text
            bdv_action = out.bdv.speak.value if out.bdv else None
            treatment_llm_called = out.llm_called
        else:
            control.process_turn(control_sid, user_text)
            treatment.process_turn(treatment_sid, user_text, **t_kwargs)

    treatment_model = getattr(treatment.runtime.llm_adapter, "model", "unknown")
    return ScenarioRunResult(
        scenario_id=scenario.scenario_id,
        control_text=control_text,
        treatment_text=treatment_text,
        bdv=bdv_action,
        control_model=control.model_name,
        treatment_model=treatment_model,
        persona_preset=treatment.preset_id,
        metrics=scenario.metrics,
        treatment_llm_called=treatment_llm_called,
    )


def run_experiment(
    *,
    control_adapter: LLMAdapter | None = None,
    treatment_adapter: LLMAdapter | None = None,
    preset_id: str = "default_companion",
    scenarios: tuple[EvalScenario, ...] = SCENARIOS,
) -> list[dict[str, Any]]:
    if control_adapter is None:
        control_adapter = default_adapter()
    if treatment_adapter is None:
        treatment_adapter = control_adapter
    control = GeminiDirectClient(llm_adapter=control_adapter, model_name=_control_model_name(control_adapter))
    treatment = PersonaEvalClient(preset_id=preset_id, llm_adapter=treatment_adapter)
    results = [
        asdict(
            run_scenario(
                scenario,
                control=control,
                treatment=treatment,
            )
        )
        for scenario in scenarios
    ]
    return results


def _control_model_name(adapter: LLMAdapter) -> str:
    return getattr(adapter, "model", "unknown")


def write_experiment_report(results: list[dict[str, Any]], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Persona control-group A/B experiment")
    parser.add_argument(
        "--output",
        default=".persona_ai/eval/ab_results.json",
        help="Where to write scenario outputs",
    )
    parser.add_argument("--preset", default="default_companion", help="Treatment preset id")
    args = parser.parse_args()

    from persona_ai.llm.gemini import GeminiLLMAdapter

    adapter = GeminiLLMAdapter()

    results = run_experiment(preset_id=args.preset, control_adapter=adapter, treatment_adapter=adapter)
    path = write_experiment_report(results, args.output)
    model = getattr(adapter, "model", "unknown")
    print(f"Wrote {len(results)} scenario results to {path} (model={model})")


if __name__ == "__main__":
    main()
