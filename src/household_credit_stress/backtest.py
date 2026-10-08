"""The backtest harness and the two baselines in docs/eval_plan.md, "Baselines" and
"Backtest design".

At every origin month L from the expanding window, both baselines are refit on data
up to L only, under the same point-in-time rule the feature panel already applies
(see `features.build_feature_panel`). This file adds no further lag of its own: every
function here takes an already-truncated history and, as a safety net against a
caller passing in too much, raises if it finds a month after the cutoff.

The two baselines:

- Persistence: the rate stays at its last known value.
- AR(1) on the monthly change (ARIMA(1,1,0), no constant): fit by least squares on
  the history's month-to-month changes, then run forward.

`run_backtest` produces one row per origin, region, horizon and baseline, with that
baseline's own 80% prediction interval built from its past errors at the same
horizon. `summarize` pools those rows into the dev/test MAE figures in
`reports/metrics.json`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from . import arrears_model, features
from .metrics import Estimate, moving_block_bootstrap_mae

# The CBA regions scored (features.REGIONS is CA plus these seven; see
# "Metrics" in docs/eval_plan.md: CA is reported but never used for the verdict).
PRIMARY_REGIONS: Final = tuple(r for r in features.REGIONS if r != "CA")

HORIZONS: Final = (1, 3)
# The two rules from docs/eval_plan.md, "Baselines". The model (ADR 0003) is scored
# against whichever of these has the lower dev MAE at each horizon; it is never a
# candidate for "best_baseline" itself.
BASELINE_MODELS: Final = ("persistence", "ar1")
MODEL_NAME: Final = arrears_model.MODEL_NAME
MODELS: Final = (*BASELINE_MODELS, MODEL_NAME)

# "What counts as beating the baseline" in docs/eval_plan.md.
MIN_RELATIVE_GAIN: Final = 0.05
MIN_COVERAGE_80: Final = 0.70
MAX_COVERAGE_80: Final = 0.90

# Backtest design, docs/eval_plan.md.
DEV_START: Final = pd.Timestamp("2007-01-01")
DEV_END: Final = pd.Timestamp("2016-12-01")
TEST_START: Final = pd.Timestamp("2017-01-01")

# The MB/SK reporting adjustment: one monthly change is dropped when the AR(1)
# baseline fits, per "Backtest design" in docs/eval_plan.md and ADR 0002.
LEVEL_SHIFT_REGIONS: Final = ("MB", "SK")
MB_SK_LEVEL_SHIFT_MONTH: Final = pd.Timestamp("2006-11-01")

# "Intervals on the metrics" in docs/eval_plan.md.
BLOCK_MONTHS: Final = 12
N_RESAMPLES: Final = 2000
CI_LEVEL: Final = 0.95
BOOT_SEED: Final = 0

# "Baselines" in docs/eval_plan.md: an 80% central prediction interval.
PI_LEVEL: Final = 0.80

# A baseline's prediction interval needs at least this many of its own past errors at
# the same horizon, known by the origin, or it is left blank (NaN) rather than built
# from too few points. The plan does not set this threshold.
MIN_INTERVAL_ERRORS: Final = 3

DECIMALS: Final = 2

BACKTEST_COLUMNS: Final = [
    "origin_month",
    "target_month",
    "horizon",
    "region",
    "model",
    "forecast_bp",
    "lo80_bp",
    "hi80_bp",
    "actual_bp",
    "error_bp",
    "abs_error_bp",
    "period",
]


def load_panel(data_dir: Path = Path("data")) -> pd.DataFrame:
    """Load the processed CSVs `refresh.py` writes and build the feature panel.

    Falls back to an empty labour-force table (so the ATL rate falls back to the
    weighted rate average; see `features.atlantic_unemployment_rate`) if
    `labour_force.csv` does not exist yet.
    """
    processed = data_dir / "processed"
    arrears = pd.read_csv(processed / "arrears.csv", parse_dates=["month"])
    unemployment = pd.read_csv(processed / "unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(processed / "mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force_path = processed / "labour_force.csv"
    if labour_force_path.exists():
        labour_force = pd.read_csv(labour_force_path, parse_dates=["month"])
    else:
        labour_force = pd.DataFrame(
            {
                "month": pd.Series([], dtype="datetime64[ns]"),
                "region": pd.Series([], dtype=str),
                "unemployed": pd.Series([], dtype=float),
                "labour_force": pd.Series([], dtype=float),
            }
        )
    return features.build_feature_panel(arrears, unemployment, mortgage_rate, labour_force)


def _assert_no_lookahead(history: pd.Series, cutoff: pd.Timestamp) -> None:
    """Raise if `history` holds a month after `cutoff`.

    Every function below takes a history its caller has already truncated to the
    cutoff; this is the last line of defense against a bug that passes in a feature
    published after the forecast's origin month (see "Data known at each origin" in
    docs/eval_plan.md).
    """
    future = history.index[history.index > cutoff]
    if len(future) > 0:
        raise ValueError(
            f"history has a value for {future.min():%Y-%m}, after the cutoff "
            f"{cutoff:%Y-%m}; this would be look-ahead"
        )


def fit_ar1(
    history: pd.Series, cutoff: pd.Timestamp, drop_diff_month: pd.Timestamp | None = None
) -> float:
    """Fit the AR(1)-on-monthly-change baseline by least squares, no constant.

    `history` is the arrears rate (bp), indexed by month, up to and including
    `cutoff`. `drop_diff_month`, when given, excludes one monthly change from the
    fit, both as the value being predicted and as the previous value it is paired
    with: the MB/SK reporting adjustment at 2006-11 (`MB_SK_LEVEL_SHIFT_MONTH`).
    Returns 0.0 (no drift, so the AR(1) forecast equals persistence) if there are
    fewer than two usable pairs of consecutive monthly changes.
    """
    _assert_no_lookahead(history, cutoff)
    diffs = history.sort_index().diff().dropna()
    pairs = pd.DataFrame({"prev": diffs.shift(1), "curr": diffs}).dropna()
    if drop_diff_month is not None:
        excluded = {drop_diff_month, drop_diff_month + pd.DateOffset(months=1)}
        pairs = pairs[~pairs.index.isin(excluded)]
    if len(pairs) < 2:
        return 0.0
    denominator = float((pairs["prev"] ** 2).sum())
    if denominator == 0.0:
        return 0.0
    return float((pairs["prev"] * pairs["curr"]).sum() / denominator)


def forecast_persistence(history: pd.Series, cutoff: pd.Timestamp) -> float:
    """Persistence baseline: the rate at `cutoff`, unchanged at every horizon."""
    _assert_no_lookahead(history, cutoff)
    return float(history.loc[cutoff])


def forecast_ar1(history: pd.Series, cutoff: pd.Timestamp, horizon: int, phi: float) -> float:
    """AR(1)-on-monthly-change forecast `horizon` months past `cutoff`.

    `phi` is the coefficient from `fit_ar1`. The last known monthly change is run
    forward `horizon` steps and added to the level at `cutoff`: the standard
    ARIMA(1,1,0) forecast, y(L+h) = y(L) + d(L) * sum(phi**1 .. phi**h).
    """
    _assert_no_lookahead(history, cutoff)
    level = float(history.loc[cutoff])
    diffs = history.sort_index().diff().dropna()
    last_diff = float(diffs.loc[cutoff]) if cutoff in diffs.index else 0.0
    total_change = (
        last_diff * horizon if phi == 1.0 else last_diff * phi * (1 - phi**horizon) / (1 - phi)
    )
    return level + total_change


def run_backtest(
    panel: pd.DataFrame,
    origins: pd.DatetimeIndex,
    regions: tuple[str, ...] = features.REGIONS,
    horizons: tuple[int, ...] = HORIZONS,
) -> pd.DataFrame:
    """Run the expanding-window backtest in docs/eval_plan.md, "Backtest design".

    `panel` is the feature panel from `features.build_feature_panel`, with
    `arrears_rate_bp` holding the actual rate at its own month. For each origin in
    `origins` and each region, both baselines are refit on data up to that origin
    only (never later, by construction: each history is sliced with `.loc[:origin]`
    before being passed to `fit_ar1` or a forecast function) and forecast at each
    horizon. A row is written only once the target month's actual rate is already in
    `panel`, so the result holds scored backtest rows, not live forecasts.

    Each row's 80% prediction interval comes from that baseline's own forecast
    errors at earlier origins, using only errors that would have been known by this
    origin: for a row at origin L and horizon h, errors at origins t with
    t + h <= L (docs/eval_plan.md, "Baselines").
    """
    rows: list[dict[str, Any]] = []
    for region in regions:
        region_panel = panel.loc[panel["region"] == region].sort_values("month")
        history = region_panel.set_index("month")["arrears_rate_bp"].sort_index()
        if history.empty:
            continue
        drop_month = MB_SK_LEVEL_SHIFT_MONTH if region in LEVEL_SHIFT_REGIONS else None

        forecasts: dict[tuple[pd.Timestamp, int, str], float] = {}
        errors: dict[tuple[int, str], dict[pd.Timestamp, float]] = {
            (h, model): {} for h in horizons for model in MODELS
        }
        for origin in origins:
            if origin not in history.index:
                continue
            known = history.loc[:origin]
            phi = fit_ar1(known, origin, drop_month)
            persistence_forecast = forecast_persistence(known, origin)

            known_panel = region_panel.loc[region_panel["month"] <= origin]
            try:
                arx_fit: arrears_model.ArxFit | None = arrears_model.fit_arx(
                    known_panel, origin, drop_month
                )
            except ValueError:
                # Too few usable rows to fit yet (ADR 0003, MIN_FIT_ROWS); the origin
                # is skipped for this model only, not for the baselines.
                arx_fit = None

            for h in horizons:
                forecasts[(origin, h, "persistence")] = persistence_forecast
                forecasts[(origin, h, "ar1")] = forecast_ar1(known, origin, h, phi)
                if arx_fit is not None:
                    try:
                        forecasts[(origin, h, MODEL_NAME)] = arrears_model.forecast_arx(
                            known_panel, origin, h, arx_fit
                        )
                    except ValueError:
                        # The drivers needed for this horizon are not known yet.
                        pass
                target = origin + pd.DateOffset(months=h)
                if target in history.index:
                    actual = float(history.loc[target])
                    for model in MODELS:
                        key = (origin, h, model)
                        if key in forecasts:
                            errors[(h, model)][origin] = actual - forecasts[key]

        for origin in origins:
            if origin not in history.index:
                continue
            for h in horizons:
                target = origin + pd.DateOffset(months=h)
                if target not in history.index:
                    continue
                actual = float(history.loc[target])
                known_by = origin - pd.DateOffset(months=h)
                for model in MODELS:
                    key = (origin, h, model)
                    if key not in forecasts:
                        continue
                    forecast = forecasts[key]
                    prior = [e for t, e in errors[(h, model)].items() if t <= known_by]
                    if len(prior) >= MIN_INTERVAL_ERRORS:
                        lo_bp = forecast + float(np.percentile(prior, 10))
                        hi_bp = forecast + float(np.percentile(prior, 90))
                    else:
                        lo_bp = hi_bp = float("nan")
                    rows.append(
                        {
                            "origin_month": origin,
                            "target_month": target,
                            "horizon": h,
                            "region": region,
                            "model": model,
                            "forecast_bp": forecast,
                            "lo80_bp": lo_bp,
                            "hi80_bp": hi_bp,
                            "actual_bp": actual,
                            "error_bp": actual - forecast,
                            "abs_error_bp": abs(actual - forecast),
                            "period": "dev" if origin <= DEV_END else "test",
                        }
                    )
    if not rows:
        return pd.DataFrame(columns=BACKTEST_COLUMNS)
    return pd.DataFrame(rows, columns=BACKTEST_COLUMNS).sort_values(
        ["region", "model", "horizon", "origin_month"], ignore_index=True
    )


def _rounded(est: Estimate) -> dict[str, float]:
    return {
        "value": round(est.value, DECIMALS),
        "ci_low": round(est.ci_low, DECIMALS),
        "ci_high": round(est.ci_high, DECIMALS),
    }


def _region_mae(
    backtest: pd.DataFrame, model: str, horizon: int, period: str, region: str
) -> float | None:
    subset = backtest[
        (backtest["model"] == model)
        & (backtest["horizon"] == horizon)
        & (backtest["period"] == period)
        & (backtest["region"] == region)
    ]
    return float(subset["abs_error_bp"].mean()) if not subset.empty else None


def _pooled_summary(
    backtest: pd.DataFrame, model: str, horizon: int, period: str
) -> dict[str, Any] | None:
    subset = backtest[
        (backtest["model"] == model)
        & (backtest["horizon"] == horizon)
        & (backtest["period"] == period)
        & (backtest["region"].isin(PRIMARY_REGIONS))
    ]
    if subset.empty:
        return None
    errors = subset[["origin_month", "abs_error_bp"]].rename(
        columns={"origin_month": "origin", "abs_error_bp": "abs_error"}
    )
    estimate = moving_block_bootstrap_mae(errors, BLOCK_MONTHS, N_RESAMPLES, CI_LEVEL, BOOT_SEED)

    coverage: float | None = None
    width: float | None = None
    if subset["lo80_bp"].notna().all():
        inside = (subset["actual_bp"] >= subset["lo80_bp"]) & (
            subset["actual_bp"] <= subset["hi80_bp"]
        )
        coverage = round(float(inside.mean()), 3)
        width = round(float((subset["hi80_bp"] - subset["lo80_bp"]).mean()), DECIMALS)

    return {
        "mae_bp": _rounded(estimate),
        "n_origins": int(subset["origin_month"].nunique()),
        "interval_coverage_80": coverage,
        "interval_width_bp": width,
    }


def _model_vs_baseline(
    backtest: pd.DataFrame, baselines: dict[str, Any], best_baseline: dict[str, str], horizon: int
) -> dict[str, Any] | None:
    """The ADR 0003 model against the horizon's best baseline, on the test period.

    Implements "What counts as beating the baseline" in docs/eval_plan.md: the gap
    (model MAE minus the baseline's) gets its own moving-block bootstrap interval,
    built by pairing the model's and the baseline's errors at the same origin and
    region, so the same resampled months are used for both (the plan's "Pairing").
    """
    baseline_model = best_baseline.get(f"h{horizon}")
    if baseline_model is None:
        return None
    columns = ["origin_month", "region", "abs_error_bp"]
    model_errors = backtest[
        (backtest["model"] == MODEL_NAME)
        & (backtest["horizon"] == horizon)
        & (backtest["period"] == "test")
        & (backtest["region"].isin(PRIMARY_REGIONS))
    ][columns]
    baseline_errors = backtest[
        (backtest["model"] == baseline_model)
        & (backtest["horizon"] == horizon)
        & (backtest["period"] == "test")
        & (backtest["region"].isin(PRIMARY_REGIONS))
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
    gap = moving_block_bootstrap_mae(diff, BLOCK_MONTHS, N_RESAMPLES, CI_LEVEL, BOOT_SEED)

    baseline_mae = baselines[baseline_model][f"h{horizon}"]["test"]["mae_bp"]["value"]
    coverage = baselines[MODEL_NAME][f"h{horizon}"]["test"]["interval_coverage_80"]
    relative_gain = -gap.value / baseline_mae if baseline_mae else 0.0
    beats_baseline = gap.ci_high < 0.0 and relative_gain >= MIN_RELATIVE_GAIN
    intervals_ok = coverage is not None and MIN_COVERAGE_80 <= coverage <= MAX_COVERAGE_80
    if gap.ci_low > 0.0:
        verdict = "worse"
    elif beats_baseline:
        verdict = "beats_baseline"
    else:
        verdict = "no_clear_difference"

    return {
        "baseline": baseline_model,
        "gap_bp": _rounded(gap),
        "relative_gain": round(relative_gain, 3),
        "beats_baseline": beats_baseline,
        "intervals_ok": intervals_ok,
        "verdict": verdict,
    }


def coefficients_at_cutoff(
    panel: pd.DataFrame, cutoff: pd.Timestamp, regions: tuple[str, ...] = PRIMARY_REGIONS
) -> dict[str, Any]:
    """The ADR 0003 fit (phi, beta_unemployment, beta_rate) for each region at
    `cutoff`, the last origin the backtest reaches. T08's scenario engine needs the
    sign of each driver's slope; see the T04 note in `_portfolio/hcs/TASKS.md`.
    """
    coefficients: dict[str, Any] = {}
    for region in regions:
        region_panel = panel.loc[panel["region"] == region].sort_values("month")
        known_panel = region_panel.loc[region_panel["month"] <= cutoff]
        drop_month = MB_SK_LEVEL_SHIFT_MONTH if region in LEVEL_SHIFT_REGIONS else None
        try:
            fit = arrears_model.fit_arx(known_panel, cutoff, drop_month)
        except ValueError as exc:
            coefficients[region] = {"error": str(exc)}
            continue
        coefficients[region] = {
            "phi": round(fit.phi, 4),
            "beta_unemployment": round(fit.beta_unemployment, 4),
            "beta_rate": round(fit.beta_rate, 4),
            "n_obs": fit.n_obs,
        }
    return coefficients


def summarize(backtest: pd.DataFrame) -> dict[str, Any]:
    """`reports/metrics.json`: pooled MAE over the seven primary regions, by model
    and horizon, for the development and test periods in docs/eval_plan.md, with a
    moving-block bootstrap interval and the 80% interval's coverage. Also reported,
    never used for the verdict: each region's own test MAE. `best_baseline` is the
    lower-dev-MAE baseline at each horizon, chosen once from `BASELINE_MODELS`, per
    "Baselines" in docs/eval_plan.md. `model` scores the ADR 0003 model (`MODEL_NAME`)
    against that baseline, per "What counts as beating the baseline".
    """
    baselines: dict[str, Any] = {}
    for model in MODELS:
        per_horizon: dict[str, Any] = {}
        for h in HORIZONS:
            by_region_test = {
                region: (
                    round(mae, DECIMALS)
                    if (mae := _region_mae(backtest, model, h, "test", region)) is not None
                    else None
                )
                for region in (*PRIMARY_REGIONS, "CA")
            }
            per_horizon[f"h{h}"] = {
                "dev": _pooled_summary(backtest, model, h, "dev"),
                "test": _pooled_summary(backtest, model, h, "test"),
                "by_region_test_mae_bp": by_region_test,
            }
        baselines[model] = per_horizon

    best_baseline: dict[str, str] = {}
    for h in HORIZONS:
        candidates = {
            model: baselines[model][f"h{h}"]["dev"]["mae_bp"]["value"]
            for model in BASELINE_MODELS
            if baselines[model][f"h{h}"]["dev"] is not None
        }
        if candidates:
            best_baseline[f"h{h}"] = min(candidates, key=lambda model: candidates[model])

    model_summary = {
        f"h{h}": _model_vs_baseline(backtest, baselines, best_baseline, h) for h in HORIZONS
    }

    test_end = f"{backtest['origin_month'].max():%Y-%m}" if not backtest.empty else None
    return {
        "about": (
            "Backtest of the persistence and AR(1) baselines (docs/eval_plan.md, "
            "'Baselines') and the ADR 0003 arx model. Pooled MAE is averaged with "
            "equal weight over the seven CBA regions ATL, QC, ON, MB, SK, AB, BC "
            "(not CA), in basis points, with a moving-block bootstrap interval over "
            "origin months. This is a backtest on the latest published vintage of "
            "every input, not the point-in-time numbers a user would have seen "
            "then; see the single-vintage caveat in docs/eval_plan.md."
        ),
        "generated_by": "python -m household_credit_stress.evaluate",
        "regions": list(PRIMARY_REGIONS),
        "dev_period": {"start": f"{DEV_START:%Y-%m}", "end": f"{DEV_END:%Y-%m}"},
        "test_period": {"start": f"{TEST_START:%Y-%m}", "end": test_end},
        "prediction_interval_level": PI_LEVEL,
        "interval": {
            "method": "moving_block_bootstrap",
            "block_months": BLOCK_MONTHS,
            "resamples": N_RESAMPLES,
            "level": CI_LEVEL,
            "seed": BOOT_SEED,
        },
        "baselines": baselines,
        "best_baseline": best_baseline,
        "model": {"name": MODEL_NAME, **model_summary},
    }
