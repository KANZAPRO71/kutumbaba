# Tests

| Suite | Path | Purpose |
|-------|------|---------|
| Scenarios | `behavior/test_scenarios.py` | v0 exit criteria (vent/closure/defer/Q) |
| Ambiguity | `behavior/test_ambiguity.py` | Mixed intent, contradiction |
| LLM adapter | `llm/test_adapter.py` | Thin wire + E2E pipeline |
| **Drift** | `sim/test_drift.py` | **15–30 turn identity stability** |
| **Smoke** | `llm/test_smoke_openai.py` | **Adversarial + LLM semantic chaos** |
| **Taxonomy** | `diagnostics/test_failure_taxonomy.py` | **Failure classification + readiness** |
| **Causal** | `diagnostics/test_causal_graph.py` | **Root-cause decomposition graph** |
| **Counterfactual** | `diagnostics/test_counterfactual.py` | **Simulated minimal fix ranking** |
| **Intervention graph** | `diagnostics/test_intervention_graph.py` | **Bundle synergy/conflict + regression** |
| **Intervention policy** | `diagnostics/test_intervention_policy.py` | **Prior pruning + search reduction** |
| **Intervention learning** | `diagnostics/test_intervention_learning.py` | **Amortized prior model + fast path** |

Run: `python -m pytest tests/ -v`

OpenAI smoke (requires `OPENAI_API_KEY`):
```bash
python -m persona_ai.sim.smoke_openai semantic_chaos --openai
python -m persona_ai.sim.smoke_openai semantic_chaos --compare
```

Drift scripts: `src/persona_ai/sim/scripts.py`  
Adversarial scripts: `src/persona_ai/sim/adversarial_scripts.py`
