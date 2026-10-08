"""The main metric and its bootstrap interval.

Mean absolute error (MAE) is the average size of a miss, in the target's own units.
A bootstrap interval shows how much that number could move with a different sample
of test rows: resample the test rows with replacement many times, compute the metric
each time, and keep the middle 95% of the results.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import Array


@dataclass(frozen=True)
class Estimate:
    """A point value with a percentile bootstrap interval."""

    value: float
    ci_low: float
    ci_high: float


def mae(y_true: Array, y_pred: Array) -> float:
    """Mean absolute error."""
    if len(y_true) != len(y_pred) or len(y_true) == 0:
        raise ValueError("y_true and y_pred must be the same, non-zero length")
    return float(np.mean(np.abs(y_true - y_pred)))


def _check_bootstrap_args(n_resamples: int, level: float) -> None:
    if n_resamples < 1:
        raise ValueError("n_resamples must be at least 1")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be between 0 and 1")


def _interval(samples: Array, value: float, level: float) -> Estimate:
    tail = (1.0 - level) / 2.0 * 100.0
    low, high = np.percentile(samples, [tail, 100.0 - tail])
    return Estimate(value=value, ci_low=float(low), ci_high=float(high))


def bootstrap_mae(
    y_true: Array, y_pred: Array, n_resamples: int, level: float, seed: int
) -> Estimate:
    """MAE with a percentile bootstrap interval over the test rows."""
    _check_bootstrap_args(n_resamples, level)
    errors = np.abs(y_true - y_pred)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(errors), size=(n_resamples, len(errors)))
    return _interval(errors[idx].mean(axis=1), mae(y_true, y_pred), level)


def bootstrap_mae_gap(
    y_true: Array,
    pred_baseline: Array,
    pred_model: Array,
    n_resamples: int,
    level: float,
    seed: int,
) -> Estimate:
    """Baseline MAE minus model MAE, with a paired bootstrap interval.

    Each resample uses the same test rows for both, so the interval is about the gap
    itself. A positive gap means the model misses by less than the baseline.
    """
    _check_bootstrap_args(n_resamples, level)
    diff = np.abs(y_true - pred_baseline) - np.abs(y_true - pred_model)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_resamples, len(diff)))
    value = mae(y_true, pred_baseline) - mae(y_true, pred_model)
    return _interval(diff[idx].mean(axis=1), value, level)
