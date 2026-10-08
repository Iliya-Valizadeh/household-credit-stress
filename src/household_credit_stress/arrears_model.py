"""The arrears model in ADR 0003 (docs/decisions/0003-arrears-model.md).

The AR(1)-on-monthly-change baseline plus two lagged driver terms, fitted by least
squares for one region at a time, with no constant:

    d(t)   = y(t) - y(t-1)
    x_u(t) = (u(t-LAG) - u(t-LAG-WINDOW)) / WINDOW
    x_m(t) = (m(t-LAG) - m(t-LAG-WINDOW)) / WINDOW
    d(t)   = phi * d(t-1) + b_u * x_u(t) + b_m * x_m(t) + error

y is the arrears rate (bp), u the region's unemployment rate and m the national posted
5-year mortgage rate, each by the calendar month it describes. With both slopes at zero
this is exactly the AR(1) baseline in `backtest`.

Every function takes the feature-panel rows for one region up to the origin L
(`features.build_feature_panel`). In those rows, the row at month L holds the drivers
for calendar month L+1 (the one-month lead in docs/eval_plan.md). `calendar_drivers`
undoes that lead, so the drivers are known through L+1 and the driver terms reach
L+1+LAG = L+3. A forecast past that horizon raises instead of guessing the drivers.

The drivers are rebuilt from the panel rows only, so a fit starts LAG+WINDOW+1 months
after the first arrears month, even though the source data on unemployment goes back
further. This keeps every input on the same point-in-time footing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from . import features

MODEL_NAME: Final = "arx"

# ADR 0003, "Decision". Fixed before any model result; never tuned.
LAG_MONTHS: Final = 2
WINDOW_MONTHS: Final = 12

# A fit with fewer usable rows than this raises rather than return weak slopes.
MIN_FIT_ROWS: Final = 24

DRIVER_COLUMNS: Final = ("unemployment_rate", "mortgage_rate_5y")
TERM_COLUMNS: Final = ("x_u", "x_m")

# Both drivers carry the same lead in the panel (docs/eval_plan.md).
assert features.UNEMPLOYMENT_LEAD_MONTHS == features.MORTGAGE_RATE_LEAD_MONTHS
DRIVER_LEAD_MONTHS: Final = features.UNEMPLOYMENT_LEAD_MONTHS


@dataclass(frozen=True)
class ArxFit:
    """The fitted slopes for one region at one origin."""

    phi: float
    beta_unemployment: float
    beta_rate: float
    n_obs: int
    cutoff: pd.Timestamp


def _check_history(history: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    """Raise if the panel rows run past the cutoff (look-ahead) or miss it."""
    months = pd.to_datetime(history["month"])
    future = months[months > cutoff]
    if len(future) > 0:
        raise ValueError(
            f"history has a row for {future.min():%Y-%m}, after the cutoff "
            f"{cutoff:%Y-%m}; this would be look-ahead"
        )
    if not (months == cutoff).any():
        raise ValueError(f"history has no row for the cutoff {cutoff:%Y-%m}")


def _monthly(series: pd.Series) -> pd.Series:
    """Sort by month and fill gaps with NaN, so a shift is always one calendar month."""
    series = series.sort_index()
    return series.asfreq("MS")


def calendar_drivers(history: pd.DataFrame) -> pd.DataFrame:
    """The drivers by the calendar month they describe.

    `history` holds panel rows (columns month, unemployment_rate, mortgage_rate_5y).
    The row at month L holds the values for month L + `DRIVER_LEAD_MONTHS`, so the
    result is indexed by month + lead.
    """
    months = pd.DatetimeIndex(pd.to_datetime(history["month"]))
    index = months + pd.DateOffset(months=DRIVER_LEAD_MONTHS)
    drivers = pd.DataFrame(
        {col: history[col].to_numpy(dtype=float) for col in DRIVER_COLUMNS}, index=index
    )
    return drivers.sort_index().asfreq("MS")


def driver_terms(drivers: pd.DataFrame) -> pd.DataFrame:
    """The ADR 0003 driver terms x_u and x_m, indexed by target month.

    `drivers` is indexed by calendar month (see `calendar_drivers`). The term for
    target month t is the average monthly change of each driver over `WINDOW_MONTHS`
    months, ending `LAG_MONTHS` before t. The result reaches `LAG_MONTHS` past the
    last driver month; terms that need a missing month are NaN.
    """
    drivers = drivers.sort_index().asfreq("MS")
    last = drivers.index.max() + pd.DateOffset(months=LAG_MONTHS)
    full_index = pd.date_range(drivers.index.min(), last, freq="MS")
    drivers = drivers.reindex(full_index)
    terms = pd.DataFrame(index=full_index)
    for driver, term in zip(DRIVER_COLUMNS, TERM_COLUMNS, strict=True):
        values = drivers[driver]
        terms[term] = (
            values.shift(LAG_MONTHS) - values.shift(LAG_MONTHS + WINDOW_MONTHS)
        ) / WINDOW_MONTHS
    return terms


def _design(
    history: pd.DataFrame, drop_diff_month: pd.Timestamp | None
) -> tuple[pd.DataFrame, pd.Series]:
    """Rows of the least-squares fit: the target d(t) and the columns d(t-1), x_u, x_m."""
    rate = _monthly(history.set_index(pd.to_datetime(history["month"]))["arrears_rate_bp"])
    change = rate.diff()
    terms = driver_terms(calendar_drivers(history))
    frame = pd.DataFrame(
        {
            "d": change,
            "d_prev": change.shift(1),
            "x_u": terms["x_u"].reindex(change.index),
            "x_m": terms["x_m"].reindex(change.index),
        }
    ).dropna()
    if drop_diff_month is not None:
        excluded = {drop_diff_month, drop_diff_month + pd.DateOffset(months=1)}
        frame = frame[~frame.index.isin(excluded)]
    return frame[["d_prev", "x_u", "x_m"]], frame["d"]


def fit_arx(
    history: pd.DataFrame, cutoff: pd.Timestamp, drop_diff_month: pd.Timestamp | None = None
) -> ArxFit:
    """Fit the ADR 0003 equation by least squares on the panel rows up to `cutoff`.

    `drop_diff_month`, when given, drops the rows whose d(t) or d(t-1) is the change
    into that month: the MB/SK reporting adjustment at 2006-11, the same rule
    `backtest.fit_ar1` applies. Raises if `history` runs past `cutoff`, or if fewer
    than `MIN_FIT_ROWS` rows can be used.
    """
    _check_history(history, cutoff)
    x, y = _design(history, drop_diff_month)
    if len(y) < MIN_FIT_ROWS:
        raise ValueError(
            f"too few rows to fit at {cutoff:%Y-%m}: {len(y)} usable, need {MIN_FIT_ROWS}"
        )
    coef, *_ = np.linalg.lstsq(x.to_numpy(dtype=float), y.to_numpy(dtype=float), rcond=None)
    return ArxFit(
        phi=float(coef[0]),
        beta_unemployment=float(coef[1]),
        beta_rate=float(coef[2]),
        n_obs=len(y),
        cutoff=cutoff,
    )


def run_forward(
    level: float,
    last_change: float,
    phi: float,
    beta_unemployment: float,
    beta_rate: float,
    x_u: Sequence[float],
    x_m: Sequence[float],
) -> list[float]:
    """Run the equation forward one month at a time and return the level path.

    `level` and `last_change` are y and d at the start month. `x_u` and `x_m` are the
    driver terms for each following month. The scenario engine can call this with
    terms built from a user's paths.
    """
    if len(x_u) != len(x_m):
        raise ValueError("x_u and x_m must have the same length")
    path: list[float] = []
    change = last_change
    for term_u, term_m in zip(x_u, x_m, strict=True):
        change = phi * change + beta_unemployment * term_u + beta_rate * term_m
        level += change
        path.append(level)
    return path


def forecast_arx(history: pd.DataFrame, cutoff: pd.Timestamp, horizon: int, fit: ArxFit) -> float:
    """Forecast the arrears rate (bp) `horizon` months past `cutoff`.

    Uses only the panel rows up to `cutoff` (raises otherwise). Raises if a driver
    term the forecast needs is not known at `cutoff`, which is the case for any
    horizon past `LAG_MONTHS` + `DRIVER_LEAD_MONTHS`.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1, got {horizon}")
    _check_history(history, cutoff)
    rate = _monthly(history.set_index(pd.to_datetime(history["month"]))["arrears_rate_bp"])
    level = float(rate.loc[cutoff])
    last_change = rate.diff().get(cutoff, np.nan)
    last_change = 0.0 if pd.isna(last_change) else float(last_change)

    targets = pd.date_range(cutoff + pd.DateOffset(months=1), periods=horizon, freq="MS")
    terms = driver_terms(calendar_drivers(history)).reindex(targets)
    if terms.isna().to_numpy().any():
        missing = terms.index[terms.isna().any(axis=1)].min()
        raise ValueError(
            f"driver terms for {missing:%Y-%m} are not known at {cutoff:%Y-%m}; "
            f"the drivers reach only {LAG_MONTHS + DRIVER_LEAD_MONTHS} months past the cutoff"
        )
    path = run_forward(
        level,
        last_change,
        fit.phi,
        fit.beta_unemployment,
        fit.beta_rate,
        terms["x_u"].tolist(),
        terms["x_m"].tolist(),
    )
    return path[-1]
