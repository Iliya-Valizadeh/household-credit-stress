"""The main metric and its bootstrap interval.

Mean absolute error (MAE) is the average size of a miss, in the target's own units.
A bootstrap interval shows how much that number could move with a different sample
of test rows: resample the test rows with replacement many times, compute the metric
each time, and keep the middle 95% of the results.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

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


def moving_block_bootstrap_mae(
    errors: pd.DataFrame, block_months: int, n_resamples: int, level: float, seed: int
) -> Estimate:
    """MAE with a moving-block bootstrap interval over whole origin months.

    `errors` has one row per region and origin month, with columns `origin` (a
    `pandas.Timestamp`, one value per origin month) and `abs_error` (basis points).
    Each resample draws blocks of `block_months` consecutive origin months, with all
    of a month's regions kept together, until the resample has as many origin months
    as the original. This follows "Intervals on the metrics" in docs/eval_plan.md: it
    keeps the link between regions at the same origin, and keeps nearby origins (whose
    forecasts can overlap, such as two 3-month-ahead forecasts 1 month apart) together
    rather than resampling each one independently.
    """
    _check_bootstrap_args(n_resamples, level)
    origins = np.sort(errors["origin"].unique())
    n_origins = len(origins)
    if n_origins == 0:
        raise ValueError("errors must have at least one origin month")
    by_origin = [
        errors.loc[errors["origin"] == origin, "abs_error"].to_numpy() for origin in origins
    ]
    value = float(errors["abs_error"].mean())

    block = min(block_months, n_origins)
    n_blocks = -(-n_origins // block)  # ceil division: enough blocks to cover n_origins
    n_starts = n_origins - block + 1

    rng = np.random.default_rng(seed)
    samples = np.empty(n_resamples)
    for i in range(n_resamples):
        starts = rng.integers(0, n_starts, size=n_blocks)
        picked = [pos for start in starts for pos in range(start, start + block)][:n_origins]
        values = np.concatenate([by_origin[pos] for pos in picked])
        samples[i] = values.mean()
    return _interval(samples, value, level)
