"""Sprint G — behavior experiment before/after store."""

from __future__ import annotations

import pytest

from persona_ai.conversation.behavior_experiment_store import (
    BehaviorExperimentStore,
    reset_behavior_experiment_store,
)


@pytest.fixture
def exp_store(tmp_path, monkeypatch):
    db = tmp_path / "exp.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_behavior_experiment_store()
    store = BehaviorExperimentStore(db)
    yield store
    reset_behavior_experiment_store()


def test_experiment_before_after(exp_store: BehaviorExperimentStore):
    before = {"listening_median": 61, "listening_p25": 54, "questions_median": 3}
    exp = exp_store.create(
        mode="cerita_tong",
        lever="behavior.question_budget",
        before_value="1",
        after_value="0",
        hypothesis="Lower questions → more listening",
        before_metrics=before,
        config_revision_before="g.014",
    )
    assert exp["status"] == "active"
    assert exp["config_revision_before"] == "g.014"
    assert exp["before_metrics"]["config_revision"] == "g.014"
    after = {"listening_median": 76, "listening_p25": 71, "questions_median": 1}
    done = exp_store.complete(
        exp["id"],
        after_metrics=after,
        config_revision_after="g.015",
    )
    assert done["status"] == "completed"
    assert done["after_metrics"]["listening_median"] == 76
    assert done["config_revision_after"] == "g.015"
