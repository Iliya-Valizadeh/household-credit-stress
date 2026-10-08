"""The scenario engine in ADR 0004 (docs/decisions/0004-scenarios.md).

Turns a user's path for the posted 5-year mortgage rate and unemployment into an
arrears path for each region, over a 24-month horizon (`L+1` to `L+24`, where `L` is
the latest CBA month). The equation is the ADR 0003 model (`arrears_model.py`) with
one pooled pair of driver slopes (`b_u`, `b_m`) shared by all seven regions, each
region keeping its own AR(1) term `phi_r`. See the ADR for why: the per-region slopes
in ADR 0003 are noisy and some have the wrong sign.

This module also runs the conditional backtest fixed in `docs/eval_plan.md`, "Changes
to this plan" (2026-10-08), which decides whether a scenario is labelled a
"conditional forecast" or "Illustrative: not a forecast", and builds the 80% bands
each scenario path is shown with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

import numpy as np
import pandas as pd

from . import arrears_model, backtest, features
from .metrics import Estimate, moving_block_bootstrap_mae

logger = logging.getLogger(__name__)

MODEL_NAME: Final = "pooled_arx"

# The seven regions the pooled fit uses. CA is derived, never fitted (ADR 0004).
REGIONS: Final = backtest.PRIMARY_REGIONS
DRIVER_COLUMNS: Final = arrears_model.DRIVER_COLUMNS
TERM_COLUMNS: Final = arrears_model.TERM_COLUMNS

HORIZON_MONTHS: Final = 24

# The deferral months: rows whose d(t) or d(t-1) falls here are dropped from the fit
# (ADR 0004, "The scenario model"). Expressed as the single inclusive window of target
# months t for which d(t) or d(t-1) is a deferral-month change.
DEFERRAL_START: Final = pd.Timestamp("2020-03-01")
DEFERRAL_END: Final = pd.Timestamp("2021-12-01")
_DEFERRAL_DROP_END: Final = DEFERRAL_END + pd.DateOffset(months=1)

MB_SK_LEVEL_SHIFT_MONTH: Final = backtest.MB_SK_LEVEL_SHIFT_MONTH
LEVEL_SHIFT_REGIONS: Final = backtest.LEVEL_SHIFT_REGIONS

# A rise of one point in unemployment or the rate is expected to raise arrears.
EXPECTED_SIGN: Final = 1.0

# "The input range is widened by half its width on each side." (ADR 0004, "The honest
# range of inputs".) Past that the engine refuses the path.
WIDEN_FACTOR: Final = 0.5

# docs/eval_plan.md, "Changes to this plan": the horizons the pass/fail check scores,
# and the settings of its moving-block bootstrap.
CHECK_HORIZONS: Final = (12, 24)
CHECK_BLOCK_MONTHS: Final = 24
CHECK_N_RESAMPLES: Final = 2000
CHECK_CI_LEVEL: Final = 0.95
CHECK_SEED: Final = 0
MIN_RELATIVE_GAIN: Final = backtest.MIN_RELATIVE_GAIN

CONDITIONAL_FORECAST_LABEL: Final = "conditional forecast"
ILLUSTRATIVE_LABEL: Final = "Illustrative: not a forecast"
ILLUSTRATIVE_SENTENCE: Final = (
    "In a backtest on the latest vintage, this model did not forecast arrears better "
    "than a simple rule over one to two years, even when it was given the true "
    "unemployment and rate paths."
)

# The bands shown with each scenario path (ADR 0004, "Bands and the label").
BAND_LOW_PERCENTILE: Final = 10.0
BAND_HIGH_PERCENTILE: Final = 90.0

DECIMALS: Final = 2


# --- the pooled fit and its sign rule -------------------------------------------------


@dataclass(frozen=True)
class PooledFit:
    """The pooled fit at one origin: a shared (`beta_unemployment`, `beta_rate`) and
    one `phi` per region. `dropped` names the driver columns the sign rule dropped
    (zero slope, as `beta_unemployment` / `beta_rate` hold 0.0 for a dropped driver).
    `no_scenario` is true when the sign rule dropped both (ADR 0004: "If both slopes
    are wrong, no scenario is drawn.")."""

    phi: dict[str, float]
    beta_unemployment: float
    beta_rate: float
    dropped: tuple[str, ...]
    n_obs: int
    cutoff: pd.Timestamp

    @property
    def no_scenario(self) -> bool:
        return len(self.dropped) == 2


def _deferral_mask(index: pd.Index) -> np.ndarray:
    """True where a row's d(t) or d(t-1) is a deferral-month change."""
    dt_index = pd.DatetimeIndex(index)
    return (dt_index >= DEFERRAL_START) & (dt_index <= _DEFERRAL_DROP_END)


def _stacked_design(
    panel: pd.DataFrame, cutoff: pd.Timestamp, regions: tuple[str, ...]
) -> tuple[pd.DataFrame, pd.Series]:
    """The stacked rows of the pooled least-squares fit: one `phi_<region>` column
    per region (holding that region's `d(t-1)`, zero elsewhere) plus the shared
    `x_u`, `x_m` columns, and the stacked target `d(t)`. Rows are sliced to `cutoff`
    before `arrears_model.design_rows` runs, as `backtest.py` does for the per-region
    fit, and deferral-month rows are dropped (ADR 0004)."""
    frames = []
    targets = []
    for region in regions:
        region_panel = panel.loc[panel["region"] == region].sort_values("month")
        known_panel = region_panel.loc[region_panel["month"] <= cutoff]
        drop_month = MB_SK_LEVEL_SHIFT_MONTH if region in LEVEL_SHIFT_REGIONS else None
        x, y = arrears_model.design_rows(known_panel, drop_month)
        keep = ~_deferral_mask(x.index)
        x, y = x.loc[keep], y.loc[keep]
        region_cols = pd.DataFrame(0.0, index=x.index, columns=[f"phi_{r}" for r in regions])
        region_cols[f"phi_{region}"] = x["d_prev"].to_numpy()
        frames.append(pd.concat([region_cols, x[list(TERM_COLUMNS)]], axis=1))
        targets.append(y)
    design = pd.concat(frames)
    target = pd.concat(targets)
    return design, target


def fit_pooled_arx(
    panel: pd.DataFrame, cutoff: pd.Timestamp, regions: tuple[str, ...] = REGIONS
) -> PooledFit:
    """Fit the ADR 0004 pooled equation on rows up to `cutoff`, then apply the sign
    rule: a driver whose fitted slope is not positive (zero counts as wrong) is
    dropped and the model is refit without it. Raises if there are too few stacked
    rows to fit the full model (one `phi` per region plus the two shared slopes)."""
    design, target = _stacked_design(panel, cutoff, regions)
    phi_columns = [f"phi_{r}" for r in regions]
    min_rows = len(phi_columns) + len(TERM_COLUMNS) + 1
    if len(target) < min_rows:
        raise ValueError(
            f"too few rows to fit the pooled model at {cutoff:%Y-%m}: "
            f"{len(target)} usable, need at least {min_rows}"
        )

    def _solve(term_columns: list[str]) -> np.ndarray:
        columns = phi_columns + term_columns
        coef, *_ = np.linalg.lstsq(
            design[columns].to_numpy(dtype=float), target.to_numpy(dtype=float), rcond=None
        )
        return np.asarray(coef, dtype=float)

    coef = _solve(list(TERM_COLUMNS))
    phi = dict(zip(regions, (float(v) for v in coef[: len(phi_columns)]), strict=True))
    beta_unemployment_full = float(coef[-2])
    beta_rate_full = float(coef[-1])

    dropped = []
    if EXPECTED_SIGN * beta_unemployment_full <= 0.0:
        dropped.append("unemployment_rate")
    if EXPECTED_SIGN * beta_rate_full <= 0.0:
        dropped.append("mortgage_rate_5y")

    if not dropped:
        return PooledFit(phi, beta_unemployment_full, beta_rate_full, (), len(target), cutoff)

    if len(dropped) == 2:
        logger.warning(
            "pooled_arx at %s: both driver slopes have the wrong sign "
            "(b_u=%.4f, b_m=%.4f); no scenario drawn",
            f"{cutoff:%Y-%m}",
            beta_unemployment_full,
            beta_rate_full,
        )
        return PooledFit(phi, 0.0, 0.0, tuple(dropped), len(target), cutoff)

    keep_column = "x_m" if "unemployment_rate" in dropped else "x_u"
    coef = _solve([keep_column])
    phi = dict(zip(regions, (float(v) for v in coef[: len(phi_columns)]), strict=True))
    value = float(coef[-1])
    beta_unemployment = value if keep_column == "x_u" else 0.0
    beta_rate = value if keep_column == "x_m" else 0.0
    logger.warning(
        "pooled_arx at %s: driver %s has the wrong sign; refit without it",
        f"{cutoff:%Y-%m}",
        dropped[0],
    )
    return PooledFit(phi, beta_unemployment, beta_rate, tuple(dropped), len(target), cutoff)


# --- the honest range of inputs -------------------------------------------------------


@dataclass(frozen=True)
class HonestRange:
    """ADR 0004, "The honest range of inputs": the lowest and highest value a driver's
    term (`x_u`/`x_m`) took in the rows of the fit, and the lowest and highest level
    the driver itself has ever taken."""

    term_low: float
    term_high: float
    level_low: float
    level_high: float

    def widened(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """The term and level ranges, each widened by half its width on each side."""

        def _widen(low: float, high: float) -> tuple[float, float]:
            pad = WIDEN_FACTOR * (high - low)
            return low - pad, high + pad

        return _widen(self.term_low, self.term_high), _widen(self.level_low, self.level_high)


def driver_ranges(
    panel: pd.DataFrame,
    unemployment: pd.DataFrame,
    mortgage_rate: pd.DataFrame,
    labour_force: pd.DataFrame,
    cutoff: pd.Timestamp,
    regions: tuple[str, ...] = REGIONS,
) -> dict[str, HonestRange]:
    """The two drivers' honest ranges at `cutoff`: the term range pooled over the
    fit's rows, and the level range over the whole history each driver's source file
    holds (unemployment by region since 1976, the rate since the rate file's first
    month; ADR 0004)."""
    design, _ = _stacked_design(panel, cutoff, regions)
    atl = features.atlantic_unemployment_rate(unemployment, labour_force)
    all_unemployment = pd.concat(
        [unemployment[unemployment["region"].isin(regions)], atl], ignore_index=True
    )
    unemployment_level = all_unemployment.loc[
        all_unemployment["region"].isin(regions), "unemployment_rate"
    ]
    rate_level = mortgage_rate["value"]
    return {
        "unemployment_rate": HonestRange(
            term_low=float(design["x_u"].min()),
            term_high=float(design["x_u"].max()),
            level_low=float(unemployment_level.min()),
            level_high=float(unemployment_level.max()),
        ),
        "mortgage_rate_5y": HonestRange(
            term_low=float(design["x_m"].min()),
            term_high=float(design["x_m"].max()),
            level_low=float(rate_level.min()),
            level_high=float(rate_level.max()),
        ),
    }


RangeFlag = Literal["ok", "beyond_history"]


def classify(
    value: float, low: float, high: float, widened_low: float, widened_high: float
) -> RangeFlag:
    """Where `value` falls against a driver's seen range and its widened range.
    Raises if `value` is outside the widened range: the hard limit on extrapolation
    (ADR 0004, "The honest range of inputs")."""
    if widened_low <= value <= widened_high:
        return "ok" if low <= value <= high else "beyond_history"
    raise ValueError(
        f"value {value!r} is past the widened range [{widened_low!r}, {widened_high!r}]; "
        "the engine refuses to extrapolate this far"
    )


# --- turning a path into an arrears path ----------------------------------------------


def path_from_changes(
    last_value: float, change_12m: float, change_24m: float, n_months: int = HORIZON_MONTHS
) -> np.ndarray:
    """A driver's future level path from the two changes a slider sets: the change by
    12 months and by 24 months from `last_value`, joined by straight lines month by
    month (ADR 0004, "How a path becomes arrears"). Returns the levels for months
    `L+2` to `L+1+n_months`."""
    k = np.arange(1, n_months + 1, dtype=float)
    out = np.empty(n_months)
    before = k <= 12
    out[before] = last_value + change_12m * (k[before] / 12.0)
    after = ~before
    out[after] = (last_value + change_12m) + (change_24m - change_12m) * ((k[after] - 12.0) / 12.0)
    return out


def national_path_for_regions(
    last_values: dict[str, float],
    change_12m: float,
    change_24m: float,
    n_months: int = HORIZON_MONTHS,
) -> dict[str, np.ndarray]:
    """By default the same national change applies to every region (ADR 0004)."""
    return {
        region: path_from_changes(level, change_12m, change_24m, n_months)
        for region, level in last_values.items()
    }


def _region_forward(
    known_panel: pd.DataFrame,
    cutoff: pd.Timestamp,
    phi_r: float,
    beta_unemployment: float,
    beta_rate: float,
    future_unemployment: np.ndarray,
    future_rate: np.ndarray,
    n_horizons: int = HORIZON_MONTHS,
) -> list[float]:
    """Run the pooled equation forward for one region, given its future driver path,
    for `n_horizons` target months (`L+1` to `L+n_horizons`). `known_panel` holds
    that region's panel rows up to `cutoff` only."""
    if len(future_unemployment) != len(future_rate):
        raise ValueError("future_unemployment and future_rate must have the same length")
    history_drivers = arrears_model.calendar_drivers(known_panel)
    future_index = pd.date_range(
        cutoff + pd.DateOffset(months=2), periods=len(future_unemployment), freq="MS"
    )
    future = pd.DataFrame(
        {"unemployment_rate": future_unemployment, "mortgage_rate_5y": future_rate},
        index=future_index,
    )
    combined = pd.concat([history_drivers, future]).sort_index().asfreq("MS")
    terms = arrears_model.driver_terms(combined)
    targets = pd.date_range(cutoff + pd.DateOffset(months=1), periods=n_horizons, freq="MS")
    term_slice = terms.reindex(targets)
    if term_slice.isna().to_numpy().any():
        missing = term_slice.index[term_slice.isna().any(axis=1)].min()
        raise ValueError(
            f"the driver path does not reach {missing:%Y-%m}; give at least "
            f"{n_horizons - 2} months of future driver data from {cutoff:%Y-%m}"
        )

    rate = arrears_model.monthly_series(known_panel.set_index("month")["arrears_rate_bp"])
    level = float(rate.loc[cutoff])
    last_change = rate.diff().get(cutoff, np.nan)
    last_change = 0.0 if pd.isna(last_change) else float(last_change)
    return arrears_model.run_forward(
        level,
        last_change,
        phi_r,
        beta_unemployment,
        beta_rate,
        term_slice["x_u"].tolist(),
        term_slice["x_m"].tolist(),
    )


@dataclass(frozen=True)
class ScenarioResult:
    """One region's arrears path (bp), `L+1` to `L+24`, with its floor flag."""

    months: pd.DatetimeIndex
    path_bp: np.ndarray
    floored: np.ndarray  # True where the unfloored path went below zero


def run_region(
    panel: pd.DataFrame,
    region: str,
    cutoff: pd.Timestamp,
    fit: PooledFit,
    future_unemployment: np.ndarray,
    future_rate: np.ndarray,
) -> ScenarioResult:
    """One region's scenario path. The path is floored at zero; a month at the floor
    is flagged (ADR 0004, "The scenario model")."""
    region_panel = panel.loc[panel["region"] == region].sort_values("month")
    known_panel = region_panel.loc[region_panel["month"] <= cutoff]
    path = np.array(
        _region_forward(
            known_panel,
            cutoff,
            fit.phi[region],
            fit.beta_unemployment,
            fit.beta_rate,
            future_unemployment,
            future_rate,
        )
    )
    floored = path < 0.0
    months = pd.date_range(cutoff + pd.DateOffset(months=1), periods=HORIZON_MONTHS, freq="MS")
    return ScenarioResult(months=months, path_bp=np.where(floored, 0.0, path), floored=floored)


def run_ca(
    panel: pd.DataFrame, cutoff: pd.Timestamp, region_results: dict[str, ScenarioResult]
) -> ScenarioResult:
    """CA is not fitted. Its path is the CBA's CA rate at `cutoff` plus the average of
    the seven regions' changes, weighted by each region's mortgage count at `cutoff`
    (ADR 0004)."""
    ca_panel = panel.loc[panel["region"] == "CA"].sort_values("month")
    ca_known = ca_panel.loc[ca_panel["month"] <= cutoff]
    ca_level = float(ca_known.set_index("month")["arrears_rate_bp"].loc[cutoff])

    weights = {}
    for region in REGIONS:
        region_panel = panel.loc[panel["region"] == region].sort_values("month")
        known = region_panel.loc[region_panel["month"] <= cutoff]
        weights[region] = float(known.set_index("month")["mortgages"].loc[cutoff])
    total_weight = sum(weights.values())

    months = next(iter(region_results.values())).months
    change = np.zeros(HORIZON_MONTHS)
    for region, result in region_results.items():
        region_level = float(
            panel.loc[
                (panel["region"] == region) & (panel["month"] == cutoff), "arrears_rate_bp"
            ].iloc[0]
        )
        change += (weights[region] / total_weight) * (result.path_bp - region_level)
    path = ca_level + change
    floored = path < 0.0
    return ScenarioResult(months=months, path_bp=np.where(floored, 0.0, path), floored=floored)


# --- a scenario's baseline path and its linear sensitivities --------------------------


@dataclass(frozen=True)
class Sensitivities:
    """ADR 0004: "the path with both drivers held at their last known values, and the
    response of each arrears month to a one-point change in each driver month." Rows
    are the 24 target months `L+1..L+24`; columns are the 24 future driver months
    `L+2..L+1+24` the engine accepts. The model is linear, so a path's arrears equal
    `baseline_path + sensitivity_unemployment @ (u_path - last_u) +
    sensitivity_rate @ (m_path - last_m)`."""

    baseline_path: np.ndarray
    sensitivity_unemployment: np.ndarray
    sensitivity_rate: np.ndarray
    last_unemployment: float
    last_rate: float


def region_sensitivities(
    panel: pd.DataFrame, region: str, cutoff: pd.Timestamp, fit: PooledFit
) -> Sensitivities:
    """The baseline path (both drivers flat at their last known value) and the
    sensitivity of each of the 24 target months to a one-point bump of each of the 24
    future driver months, for `region`. Built by finite differences: the model is
    linear, so a unit bump gives the exact per-month response."""
    region_panel = panel.loc[panel["region"] == region].sort_values("month")
    known_panel = region_panel.loc[region_panel["month"] <= cutoff]
    history_drivers = arrears_model.calendar_drivers(known_panel)
    last_u = float(history_drivers["unemployment_rate"].iloc[-1])
    last_m = float(history_drivers["mortgage_rate_5y"].iloc[-1])
    flat_u = np.full(HORIZON_MONTHS, last_u)
    flat_m = np.full(HORIZON_MONTHS, last_m)

    def _run(u: np.ndarray, m: np.ndarray) -> np.ndarray:
        return np.array(
            _region_forward(
                known_panel, cutoff, fit.phi[region], fit.beta_unemployment, fit.beta_rate, u, m
            )
        )

    baseline = _run(flat_u, flat_m)
    sens_u = np.zeros((HORIZON_MONTHS, HORIZON_MONTHS))
    sens_m = np.zeros((HORIZON_MONTHS, HORIZON_MONTHS))
    for k in range(HORIZON_MONTHS):
        bumped_u = flat_u.copy()
        bumped_u[k] += 1.0
        sens_u[:, k] = _run(bumped_u, flat_m) - baseline
        bumped_m = flat_m.copy()
        bumped_m[k] += 1.0
        sens_m[:, k] = _run(flat_u, bumped_m) - baseline
    return Sensitivities(baseline, sens_u, sens_m, last_u, last_m)


# --- presets from history -------------------------------------------------------------


@dataclass(frozen=True)
class PresetRule:
    name: str
    driver: str  # "unemployment_rate" or "mortgage_rate_5y"
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    expected_start: pd.Timestamp


# ADR 0004, "Presets from history". `expected_start` is the month the ADR records;
# `build_presets` recomputes the rule and raises if it no longer matches (T08's note
# in _portfolio/hcs/TASKS.md: "T09 computes them again in code and fails if they
# differ").
PRESET_RULES: Final = (
    PresetRule(
        "Early 1990s recession",
        "unemployment_rate",
        pd.Timestamp("1989-01-01"),
        pd.Timestamp("1990-12-01"),
        pd.Timestamp("1989-10-01"),
    ),
    PresetRule(
        "2008-09 recession",
        "unemployment_rate",
        pd.Timestamp("2007-01-01"),
        pd.Timestamp("2008-12-01"),
        pd.Timestamp("2007-10-01"),
    ),
    PresetRule(
        "Rate rises of 2022 and 2023",
        "mortgage_rate_5y",
        pd.Timestamp("2021-01-01"),
        pd.Timestamp("2022-12-01"),
        pd.Timestamp("2022-03-01"),
    ),
)

PRESET_MONTHS: Final = HORIZON_MONTHS - 1  # k = 1 .. 23 (ADR 0004, "Presets from history")


@dataclass(frozen=True)
class Preset:
    name: str
    start_month: pd.Timestamp
    unemployment_change: dict[str, np.ndarray]  # region -> 23 values, months S+1..S+23
    rate_change: np.ndarray | None  # national, 23 values, or None if not covered
    rate_note: str | None


def _start_month(
    series: pd.Series, window_start: pd.Timestamp, window_end: pd.Timestamp
) -> pd.Timestamp:
    """The last month at the series' lowest value in [`window_start`, `window_end`]."""
    window = series.sort_index().loc[window_start:window_end].dropna()
    if window.empty:
        raise ValueError(
            f"no data in [{window_start:%Y-%m}, {window_end:%Y-%m}] to pick a start month"
        )
    lowest = window.min()
    return pd.Timestamp(window.index[window == lowest].max())


def _region_unemployment_series(
    region: str, unemployment: pd.DataFrame, labour_force: pd.DataFrame
) -> pd.Series:
    if region == "ATL":
        atl = features.atlantic_unemployment_rate(unemployment, labour_force)
        return atl.set_index("month")["unemployment_rate"].sort_index()
    return (
        unemployment.loc[unemployment["region"] == region]
        .set_index("month")["unemployment_rate"]
        .sort_index()
    )


def build_presets(
    unemployment: pd.DataFrame,
    mortgage_rate: pd.DataFrame,
    labour_force: pd.DataFrame,
    regions: tuple[str, ...] = REGIONS,
    n_months: int = PRESET_MONTHS,
) -> list[Preset]:
    """The presets in ADR 0004, "Presets from history": each preset replays a past
    *change*, not a past level, starting at a month a stated rule picks. Raises if the
    recomputed start month differs from the one the ADR records."""
    ca_unemployment = _region_unemployment_series("CA", unemployment, labour_force)
    national_rate = mortgage_rate.set_index("month")["value"].sort_index()

    presets = []
    for rule in PRESET_RULES:
        series = ca_unemployment if rule.driver == "unemployment_rate" else national_rate
        start = _start_month(series, rule.window_start, rule.window_end)
        if start != rule.expected_start:
            raise ValueError(
                f"preset '{rule.name}' recomputed start month {start:%Y-%m}, but "
                f"docs/decisions/0004-scenarios.md records {rule.expected_start:%Y-%m}; "
                "the preset table there needs updating before this can be trusted"
            )

        k_index = pd.date_range(start, periods=n_months + 1, freq="MS")[1:]
        unemployment_change: dict[str, np.ndarray] = {}
        for region in regions:
            series_r = _region_unemployment_series(region, unemployment, labour_force)
            base = series_r.get(start)
            if base is None or pd.isna(base) or series_r.reindex(k_index).isna().any():
                raise ValueError(
                    f"preset '{rule.name}' needs unemployment for {region} from "
                    f"{start:%Y-%m} to {k_index[-1]:%Y-%m}, which the data does not cover"
                )
            unemployment_change[region] = (series_r.reindex(k_index) - base).to_numpy()

        rate_change: np.ndarray | None = None
        rate_note: str | None = None
        base_rate = national_rate.get(start)
        if base_rate is not None and not national_rate.reindex(k_index).isna().any():
            rate_change = (national_rate.reindex(k_index) - base_rate).to_numpy()
        else:
            rate_note = (
                "the posted 5-year rate file does not cover this period; the rate "
                "path is held flat (no change) for this preset"
            )

        presets.append(Preset(rule.name, start, unemployment_change, rate_change, rate_note))
    return presets


def preset_to_dict(preset: Preset) -> dict[str, Any]:
    """`Preset` as JSON-safe data, for `reports/scenario_presets.json`."""
    rate_change = preset.rate_change
    return {
        "start_month": f"{preset.start_month:%Y-%m}",
        "unemployment_change": {
            region: [round(float(v), DECIMALS) for v in values]
            for region, values in preset.unemployment_change.items()
        },
        "rate_change": (
            [round(float(v), DECIMALS) for v in rate_change] if rate_change is not None else None
        ),
        "rate_note": preset.rate_note,
    }


# --- the conditional backtest, the verdict and the label ------------------------------

CONDITIONAL_BACKTEST_COLUMNS: Final = [
    "origin_month",
    "target_month",
    "horizon",
    "region",
    "model",
    "forecast_bp",
    "actual_bp",
    "error_bp",
    "abs_error_bp",
    "period",
]


def run_conditional_backtest(
    panel: pd.DataFrame,
    origins: pd.DatetimeIndex,
    regions: tuple[str, ...] = REGIONS,
    horizons: range = range(1, HORIZON_MONTHS + 1),
) -> pd.DataFrame:
    """The conditional backtest in docs/eval_plan.md, "Changes to this plan"
    (2026-10-08). At each origin the pooled model is refit on data up to that origin
    only, with its sign rule, then forecast forward using the *actual* driver values
    after the origin (breaking the point-in-time rule on purpose: a scenario is a
    forecast given a path). The two baselines (persistence, AR(1)) are run forward
    with no driver data, as in `backtest.py`. A row is written only once the target
    month's actual rate is published.

    Unlike `backtest.run_backtest`, origins whose target falls in the deferral months
    stay in (the eval-plan addendum says so); the deferral rows are already dropped
    from the pooled *fit* by `fit_pooled_arx`, which is a separate thing.
    """
    rows: list[dict[str, Any]] = []
    region_histories = {
        region: panel.loc[panel["region"] == region]
        .sort_values("month")
        .set_index("month", drop=False)
        for region in (*regions, "CA")
    }
    # Calendar-month-indexed drivers over the *whole* committed history (latest
    # vintage), for every region: this is what lets the conditional backtest use the
    # true future path on purpose (docs/eval_plan.md, "Changes to this plan").
    calendar_by_region = {
        region: arrears_model.calendar_drivers(
            panel.loc[panel["region"] == region].sort_values("month")
        )
        for region in regions
    }
    max_h = max(horizons)

    for origin in origins:
        try:
            fit = fit_pooled_arx(panel, origin, regions)
        except ValueError:
            continue  # too few rows to fit yet

        region_forecasts: dict[str, dict[int, float]] = {r: {} for r in regions}
        for region in regions:
            history = region_histories[region]
            if origin not in history.index:
                continue
            known_panel = history.loc[history.index <= origin]
            future_months = pd.date_range(
                origin + pd.DateOffset(months=2), periods=max_h, freq="MS"
            )
            full_drivers = calendar_by_region[region]
            u_path = full_drivers["unemployment_rate"].reindex(future_months)
            m_path = full_drivers["mortgage_rate_5y"].reindex(future_months)
            available = (~u_path.isna()) & (~m_path.isna())
            n_future = int(available.to_numpy().argmin()) if not available.all() else max_h
            # A target h needs future driver data only once h > LAG_MONTHS +
            # DRIVER_LEAD_MONTHS (ADR 0003); below that, history alone is enough.
            usable_h = min(
                max_h, n_future + arrears_model.LAG_MONTHS + arrears_model.DRIVER_LEAD_MONTHS
            )
            if usable_h < 1:
                continue
            try:
                path = _region_forward(
                    known_panel,
                    origin,
                    fit.phi[region],
                    fit.beta_unemployment,
                    fit.beta_rate,
                    u_path.to_numpy()[:usable_h],
                    m_path.to_numpy()[:usable_h],
                    n_horizons=usable_h,
                )
            except ValueError:
                continue
            for h in horizons:
                if h <= usable_h:
                    region_forecasts[region][h] = path[h - 1]

        for region in (*regions, "CA"):
            history = region_histories[region]
            if origin not in history.index:
                continue
            known = history.loc[history.index <= origin, "arrears_rate_bp"]
            phi_ar1 = backtest.fit_ar1(known, origin)
            persistence_forecast = backtest.forecast_persistence(known, origin)
            for h in horizons:
                target = origin + pd.DateOffset(months=h)
                if target not in history.index:
                    continue
                actual = float(history["arrears_rate_bp"].loc[target])
                forecasts = {
                    "persistence": persistence_forecast,
                    "ar1": backtest.forecast_ar1(known, origin, h, phi_ar1),
                }
                if region != "CA" and h in region_forecasts[region]:
                    forecasts[MODEL_NAME] = region_forecasts[region][h]
                for model, forecast in forecasts.items():
                    rows.append(
                        {
                            "origin_month": origin,
                            "target_month": target,
                            "horizon": h,
                            "region": region,
                            "model": model,
                            "forecast_bp": forecast,
                            "actual_bp": actual,
                            "error_bp": actual - forecast,
                            "abs_error_bp": abs(actual - forecast),
                            "period": "dev" if origin <= backtest.DEV_END else "test",
                        }
                    )
    if not rows:
        return pd.DataFrame(columns=CONDITIONAL_BACKTEST_COLUMNS)
    return pd.DataFrame(rows, columns=CONDITIONAL_BACKTEST_COLUMNS).sort_values(
        ["region", "model", "horizon", "origin_month"], ignore_index=True
    )


def _mae(
    frame: pd.DataFrame, model: str, horizon: int, period: str, regions: tuple[str, ...]
) -> float | None:
    subset = frame[
        (frame["model"] == model)
        & (frame["horizon"] == horizon)
        & (frame["period"] == period)
        & (frame["region"].isin(regions))
    ]
    return float(subset["abs_error_bp"].mean()) if not subset.empty else None


def _rounded(est: Estimate) -> dict[str, float]:
    return {
        "value": round(est.value, DECIMALS),
        "ci_low": round(est.ci_low, DECIMALS),
        "ci_high": round(est.ci_high, DECIMALS),
    }


def _check_horizon(frame: pd.DataFrame, horizon: int) -> dict[str, Any] | None:
    """docs/eval_plan.md, "Changes to this plan": the best baseline is the one with
    the lower dev MAE, chosen before the test origins are scored; the model passes if
    the 95% interval of (model MAE - best-baseline MAE) lies wholly below zero and the
    point estimate is at least 5% lower."""
    raw_dev_mae = {
        model: _mae(frame, model, horizon, "dev", REGIONS) for model in backtest.BASELINE_MODELS
    }
    dev_mae: dict[str, float] = {m: v for m, v in raw_dev_mae.items() if v is not None}
    if not dev_mae:
        return None
    best_baseline = min(dev_mae, key=lambda m: dev_mae[m])

    columns = ["origin_month", "region", "abs_error_bp"]
    model_errors = frame[
        (frame["model"] == MODEL_NAME)
        & (frame["horizon"] == horizon)
        & (frame["period"] == "test")
        & (frame["region"].isin(REGIONS))
    ][columns]
    baseline_errors = frame[
        (frame["model"] == best_baseline)
        & (frame["horizon"] == horizon)
        & (frame["period"] == "test")
        & (frame["region"].isin(REGIONS))
    ][columns]
    if model_errors.empty or baseline_errors.empty:
        return None
    paired = model_errors.merge(
        baseline_errors, on=["origin_month", "region"], suffixes=("_model", "_baseline")
    )
    diff = pd.DataFrame(
        {
            "origin": paired["origin_month"],
            "abs_error": paired["abs_error_bp_model"] - paired["abs_error_bp_baseline"],
        }
    )
    gap = moving_block_bootstrap_mae(
        diff, CHECK_BLOCK_MONTHS, CHECK_N_RESAMPLES, CHECK_CI_LEVEL, CHECK_SEED
    )
    baseline_mae = _mae(frame, best_baseline, horizon, "test", REGIONS)
    model_mae = _mae(frame, MODEL_NAME, horizon, "test", REGIONS)
    relative_gain = -gap.value / baseline_mae if baseline_mae else 0.0
    passes = gap.ci_high < 0.0 and relative_gain >= MIN_RELATIVE_GAIN

    return {
        "best_baseline": best_baseline,
        "model_mae_bp": round(model_mae, DECIMALS) if model_mae is not None else None,
        "baseline_mae_bp": round(baseline_mae, DECIMALS) if baseline_mae is not None else None,
        "gap_bp": _rounded(gap),
        "relative_gain": round(relative_gain, 3),
        "passes": passes,
    }


def summarize_check(frame: pd.DataFrame) -> dict[str, Any]:
    """The verdict at h=12 and h=24, and the label it decides (ADR 0004, "Bands and
    the label"): "conditional forecast" only if the model passes at both horizons,
    else every scenario is "Illustrative: not a forecast" with the stated sentence."""
    per_horizon = {f"h{h}": _check_horizon(frame, h) for h in CHECK_HORIZONS}
    passes_all = all(
        (result := per_horizon[f"h{h}"]) is not None and result["passes"] for h in CHECK_HORIZONS
    )
    label = CONDITIONAL_FORECAST_LABEL if passes_all else ILLUSTRATIVE_LABEL
    reason = None if passes_all else ILLUSTRATIVE_SENTENCE
    return {"check": per_horizon, "label": label, "label_reason": reason}


def bands_by_region_and_horizon(
    frame: pd.DataFrame,
    regions: tuple[str, ...] = REGIONS,
    horizons: range = range(1, HORIZON_MONTHS + 1),
) -> dict[str, dict[str, dict[str, float]]]:
    """ADR 0004, "Bands and the label": the 80% band for each region and month ahead,
    from the 10th and 90th percentiles of the model's own errors in the conditional
    backtest, using every published error (dev and test)."""
    bands: dict[str, dict[str, dict[str, float]]] = {}
    for region in regions:
        bands[region] = {}
        for h in horizons:
            errors = frame.loc[
                (frame["region"] == region)
                & (frame["model"] == MODEL_NAME)
                & (frame["horizon"] == h),
                "error_bp",
            ]
            if errors.empty:
                continue
            bands[region][f"h{h}"] = {
                "lo80_bp": round(float(np.percentile(errors, BAND_LOW_PERCENTILE)), DECIMALS),
                "hi80_bp": round(float(np.percentile(errors, BAND_HIGH_PERCENTILE)), DECIMALS),
                "n_origins": int(errors.shape[0]),
            }
    return bands
