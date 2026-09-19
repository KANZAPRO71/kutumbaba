"""Behavior config revision tagging."""

from __future__ import annotations

import pytest

from persona_ai.conversation.behavior_config_revision import (
    bump_revision,
    current_revision,
    next_experiment_id,
    stamp_metrics,
)
from persona_ai.conversation.behavior_experiment_store import (
    BehaviorExperimentStore,
    reset_behavior_experiment_store,
)


@pytest.fixture
def rev_db(tmp_path, monkeypatch):
    db = tmp_path / "rev.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_behavior_experiment_store()
    yield db
    reset_behavior_experiment_store()


def test_revision_bump_and_stamp(rev_db):
    assert current_revision(rev_db) == "g.001"
    assert bump_revision(rev_db) == "g.002"
    assert current_revision(rev_db) == "g.002"
    m = stamp_metrics({"listening_median": 70}, "g.002")
    assert m["config_revision"] == "g.002"


def test_experiment_carries_revisions(rev_db):
    store = BehaviorExperimentStore(rev_db)
    exp = store.create(
        mode="cerita_tong",
        lever="question_budget",
        before_value="1",
        after_value="0",
        hypothesis="Less questions",
        before_metrics={"listening_median": 61},
    )
    assert exp["id"].startswith("exp_")
    assert exp["config_revision_before"] == "g.001"
    assert exp["before_metrics"]["config_revision"] == "g.001"
    bump_revision(rev_db)
    done = store.complete(
        exp["id"],
        after_metrics={"listening_median": 76},
        config_revision_after="g.002",
    )
    assert done["config_revision_after"] == "g.002"
    assert done["after_metrics"]["config_revision"] == "g.002"


def test_experiment_ids_increment(rev_db):
    assert next_experiment_id(rev_db) == "exp_001"
    assert next_experiment_id(rev_db) == "exp_002"
