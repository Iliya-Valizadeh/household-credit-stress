"""Tests for the generic metric helpers in `metrics.py`: plain MAE and its
percentile bootstrap interval, the paired bootstrap gap, and the package version.
The moving-block bootstrap used by the real backtest has its own tests in
`test_backtest.py`.
"""

from __future__ import annotations

import numpy as np
import pytest

from household_credit_stress import __version__, metrics


def test_version_is_set() -> None:
    assert __version__


def test_mae_by_hand() -> None:
    assert metrics.mae(np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 1.0])) == 1.0
    with pytest.raises(ValueError):
        metrics.mae(np.array([]), np.array([]))


def test_bootstrap_interval_contains_the_value() -> None:
    rng = np.random.default_rng(0)
    y, pred = rng.normal(size=300), rng.normal(size=300)
    est = metrics.bootstrap_mae(y, pred, n_resamples=500, level=0.95, seed=0)
    assert est.ci_low < est.value < est.ci_high
    gap = metrics.bootstrap_mae_gap(y, pred, y, n_resamples=500, level=0.95, seed=0)
    assert gap.value == pytest.approx(est.value)


@pytest.mark.parametrize(("n_resamples", "level"), [(0, 0.95), (100, 1.0)])
def test_bootstrap_rejects_bad_settings(n_resamples: int, level: float) -> None:
    y = np.ones(5)
    with pytest.raises(ValueError):
        metrics.bootstrap_mae(y, y, n_resamples, level, seed=0)
