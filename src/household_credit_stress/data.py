"""Make a small synthetic dataset, so the demo needs no downloads.

The data is a toy regression problem. Each row has a few numeric features drawn from
a normal distribution. The target is a fixed linear mix of the features plus random
noise. A fixed seed makes every run produce the same rows.

This is template code. Replace it with the loader for your real data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

# The rule that makes the target. Feature 2 has no effect on purpose.
TRUE_INTERCEPT = 3.0
TRUE_COEFFICIENTS = (1.5, -2.0, 0.0, 0.5, 1.0)
NOISE_SD = 1.0


@dataclass(frozen=True)
class Split:
    """Train and test rows. The test rows are only used for the final numbers."""

    x_train: Array
    y_train: Array
    x_test: Array
    y_test: Array


def make_dataset(n_rows: int, seed: int) -> tuple[Array, Array]:
    """Return features `x` (n_rows by 5) and target `y` (n_rows)."""
    if n_rows < 2:
        raise ValueError("n_rows must be at least 2")
    rng = np.random.default_rng(seed)
    coef = np.asarray(TRUE_COEFFICIENTS, dtype=np.float64)
    x = rng.normal(size=(n_rows, coef.size))
    y = TRUE_INTERCEPT + x @ coef + rng.normal(scale=NOISE_SD, size=n_rows)
    return x, y


def train_test_split(x: Array, y: Array, test_fraction: float, seed: int) -> Split:
    """Shuffle the rows with `seed`, then hold out `test_fraction` of them for testing."""
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")
    if len(x) != len(y):
        raise ValueError("x and y must have the same number of rows")
    n_test = round(len(y) * test_fraction)
    if n_test < 1 or n_test >= len(y):
        raise ValueError("the split leaves no rows for training or for testing")
    order = np.random.default_rng(seed).permutation(len(y))
    test, train = order[:n_test], order[n_test:]
    return Split(x_train=x[train], y_train=y[train], x_test=x[test], y_test=y[test])
