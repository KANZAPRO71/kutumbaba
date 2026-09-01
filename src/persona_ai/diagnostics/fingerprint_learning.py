"""Fingerprint-aware patch learning v1.2 — decay + (fingerprint_id, patch_id) memory."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

DEFAULT_STORE_PATH = Path(".persona_ai/fingerprint_learning.json")
DEFAULT_HALF_LIFE_DAYS = 10.0
REGRESSION_SPIKE = 0.2


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def decay_factor(
    last_updated: str,
    *,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Exponential decay weight; half-life ~= half_life_days."""
    if not last_updated:
        return 1.0
    now = now or _utc_now()
    then = _parse_ts(last_updated)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    delta_s = max(0.0, (now - then).total_seconds())
    tau = (half_life_days * 86400.0) / math.log(2)
    return math.exp(-delta_s / tau)


@dataclass
class FingerprintPatchStats:
    attempts: int = 0
    success: int = 0
    regressions: int = 0
    last_updated: str = ""

    @property
    def success_rate(self) -> float:
        return self.success / max(self.attempts, 1)

    @property
    def regression_penalty(self) -> float:
        return self.regressions / max(self.attempts, 1)

    @property
    def score(self) -> float:
        return round(self.success_rate - 0.5 * self.regression_penalty, 3)

    @property
    def confidence(self) -> float:
        return round(self.attempts / (self.attempts + 2), 3)

    def touch(self, now: datetime | None = None) -> None:
        ts = now or _utc_now()
        self.last_updated = ts.isoformat()


@dataclass
class DecayedPatchView:
    decay_factor: float
    effective_attempts: float
    effective_success: float
    effective_regressions: float
    raw_score: float
    decayed_score: float
    decayed_confidence: float

    @classmethod
    def from_stats(
        cls,
        stats: FingerprintPatchStats,
        *,
        now: datetime | None = None,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> DecayedPatchView:
        df = decay_factor(stats.last_updated, now=now, half_life_days=half_life_days)
        eff_a = stats.attempts * df
        eff_s = stats.success * df
        eff_r = stats.regressions * df
        raw_score = stats.score

        if eff_a < 1e-9:
            return cls(
                decay_factor=round(df, 3),
                effective_attempts=round(eff_a, 3),
                effective_success=round(eff_s, 3),
                effective_regressions=round(eff_r, 3),
                raw_score=raw_score,
                decayed_score=0.5,
                decayed_confidence=0.0,
            )

        sr = eff_s / eff_a
        rp = eff_r / eff_a
        decayed = sr - 0.5 * rp
        if stats.regressions > 0:
            decayed -= REGRESSION_SPIKE * df

        return cls(
            decay_factor=round(df, 3),
            effective_attempts=round(eff_a, 3),
            effective_success=round(eff_s, 3),
            effective_regressions=round(eff_r, 3),
            raw_score=raw_score,
            decayed_score=round(max(0.0, decayed), 3),
            decayed_confidence=round(eff_a / (eff_a + 2), 3),
        )


@dataclass
class FingerprintPatchPrediction:
    fingerprint_id: str
    patch_id: str
    success_rate: float
    score: float
    raw_score: float
    decayed_score: float
    decay_factor: float
    confidence: float
    attempts: int
    effective_attempts: float
    regressions: int
    reason: str


class FingerprintPatchLearner:
    """Learns which patches work for specific fingerprint identities."""

    SCORE_THRESHOLD = 0.7
    MIN_EFFECTIVE_ATTEMPTS = 2.0

    def __init__(
        self,
        store_path: Path | None = None,
        *,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store_path = store_path or DEFAULT_STORE_PATH
        self.half_life_days = half_life_days
        self._clock = clock or _utc_now
        self._store: dict[str, dict[str, FingerprintPatchStats]] = {}
        if self.store_path.exists():
            self._load()

    def _now(self) -> datetime:
        return self._clock()

    def _stats(self, fingerprint_id: str, patch_id: str) -> FingerprintPatchStats:
        if fingerprint_id not in self._store:
            self._store[fingerprint_id] = {}
        if patch_id not in self._store[fingerprint_id]:
            row = FingerprintPatchStats()
            row.touch(self._now())
            self._store[fingerprint_id][patch_id] = row
        return self._store[fingerprint_id][patch_id]

    def _touch(self, stats: FingerprintPatchStats) -> None:
        stats.touch(self._now())

    def _decayed(self, stats: FingerprintPatchStats) -> DecayedPatchView:
        return DecayedPatchView.from_stats(
            stats,
            now=self._now(),
            half_life_days=self.half_life_days,
        )

    def record_attempt(self, fingerprint_id: str, patch_id: str) -> None:
        stats = self._stats(fingerprint_id, patch_id)
        stats.attempts += 1
        self._touch(stats)

    def record_simulation(self, fingerprint_id: str, patch_id: str, *, fixes_failure: bool) -> None:
        stats = self._stats(fingerprint_id, patch_id)
        stats.attempts += 1
        if fixes_failure:
            stats.success += 1
        self._touch(stats)

    def record_success(self, fingerprint_id: str, patch_id: str) -> None:
        stats = self._stats(fingerprint_id, patch_id)
        stats.success += 1
        self._touch(stats)

    def record_regression(self, fingerprint_id: str, patch_id: str) -> None:
        stats = self._stats(fingerprint_id, patch_id)
        stats.regressions += 1
        self._touch(stats)

    def predict_best(
        self,
        fingerprint_id: str,
        patch_ids: list[str],
    ) -> list[FingerprintPatchPrediction]:
        preds: list[FingerprintPatchPrediction] = []
        fp_stats = self._store.get(fingerprint_id, {})
        for patch_id in patch_ids:
            stats = fp_stats.get(patch_id)
            if stats is None:
                preds.append(
                    FingerprintPatchPrediction(
                        fingerprint_id=fingerprint_id,
                        patch_id=patch_id,
                        success_rate=0.5,
                        score=0.5,
                        raw_score=0.5,
                        decayed_score=0.5,
                        decay_factor=1.0,
                        confidence=0.0,
                        attempts=0,
                        effective_attempts=0.0,
                        regressions=0,
                        reason="no fingerprint history",
                    )
                )
                continue
            view = self._decayed(stats)
            preds.append(
                FingerprintPatchPrediction(
                    fingerprint_id=fingerprint_id,
                    patch_id=patch_id,
                    success_rate=round(view.effective_success / max(view.effective_attempts, 1e-9), 3),
                    score=view.decayed_score,
                    raw_score=view.raw_score,
                    decayed_score=view.decayed_score,
                    decay_factor=view.decay_factor,
                    confidence=view.decayed_confidence,
                    attempts=stats.attempts,
                    effective_attempts=view.effective_attempts,
                    regressions=stats.regressions,
                    reason=(
                        f"raw={stats.success}/{stats.attempts} score={view.raw_score:.2f} "
                        f"decayed={view.decayed_score:.2f} eff={view.effective_attempts:.2f} df={view.decay_factor:.2f}"
                    ),
                )
            )
        preds.sort(key=lambda p: (-p.decayed_score, -p.effective_attempts, -p.confidence))
        return preds

    def fast_path_eligible(self, prediction: FingerprintPatchPrediction | None) -> bool:
        if prediction is None:
            return False
        return (
            prediction.effective_attempts >= self.MIN_EFFECTIVE_ATTEMPTS
            and prediction.decayed_score >= self.SCORE_THRESHOLD
        )

    def leaderboard(self, fingerprint_id: str, limit: int = 5) -> list[FingerprintPatchPrediction]:
        fp_stats = self._store.get(fingerprint_id, {})
        patch_ids = sorted(fp_stats.keys())
        return self.predict_best(fingerprint_id, patch_ids)[:limit]

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            fp_id: {patch_id: asdict(stats) for patch_id, stats in patches.items()}
            for fp_id, patches in self._store.items()
        }
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        now = self._now().isoformat()
        for fp_id, patches in raw.items():
            self._store[fp_id] = {}
            for patch_id, stats in patches.items():
                if "last_updated" not in stats or not stats["last_updated"]:
                    stats["last_updated"] = now
                self._store[fp_id][patch_id] = FingerprintPatchStats(**stats)

    @property
    def store_size(self) -> int:
        return sum(len(p) for p in self._store.values())


_default_fp_learner: FingerprintPatchLearner | None = None


def get_fp_learner(store_path: Path | None = None) -> FingerprintPatchLearner:
    global _default_fp_learner
    if _default_fp_learner is None:
        path = store_path or DEFAULT_STORE_PATH
        _default_fp_learner = FingerprintPatchLearner(path)
    return _default_fp_learner


def ingest_lifecycle_outcomes(
    learner: FingerprintPatchLearner,
    *,
    lifecycle,
    previous_recommended: dict[str, str] | None,
) -> int:
    """Credit success/regression to patches tied to closed/reopened fingerprints."""
    count = 0
    prev = previous_recommended or {}
    for fp_id in lifecycle.closed:
        patch_id = prev.get(fp_id)
        if patch_id:
            learner.record_success(fp_id, patch_id)
            count += 1
    for fp_id in lifecycle.regressions:
        patch_id = prev.get(fp_id)
        if patch_id:
            learner.record_regression(fp_id, patch_id)
            count += 1
    if count:
        learner.save()
    return count
