"""A simple baseline and a linear model with the same small interface.

The baseline ignores the features and always predicts the mean of the training
target. Any model worth using must beat it on the test rows.

This is template code. Keep the baseline idea and replace the model with your own.
"""

from __future__ import annotations

import numpy as np

from .data import Array


class MeanBaseline:
    """Predicts the training mean for every row."""

    name = "train_mean"

    def __init__(self) -> None:
        self.mean_: float | None = None

    def fit(self, x: Array, y: Array) -> MeanBaseline:
        del x  # the baseline does not look at the features
        self.mean_ = float(np.mean(y))
        return self

    def predict(self, x: Array) -> Array:
        if self.mean_ is None:
            raise RuntimeError("call fit before predict")
        return np.full(len(x), self.mean_, dtype=np.float64)


class LinearModel:
    """Ordinary least squares with an intercept, solved with numpy."""

    name = "linear_least_squares"

    def __init__(self) -> None:
        self.coef_: Array | None = None

    @staticmethod
    def _with_intercept(x: Array) -> Array:
        return np.column_stack([np.ones(len(x)), x])

    def fit(self, x: Array, y: Array) -> LinearModel:
        coef, *_ = np.linalg.lstsq(self._with_intercept(x), y, rcond=None)
        self.coef_ = np.asarray(coef, dtype=np.float64)
        return self

    def predict(self, x: Array) -> Array:
        if self.coef_ is None:
            raise RuntimeError("call fit before predict")
        return self._with_intercept(x) @ self.coef_
