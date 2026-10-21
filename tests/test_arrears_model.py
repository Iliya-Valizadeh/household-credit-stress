"""Tests for the arrears model in ADR 0003 (docs/decisions/0003-arrears-model.md).

The model is the AR(1) baseline plus two lagged driver terms. The tests check that it
nests the baseline, recovers known slopes, applies the point-in-time data rule
(drivers through L+1 only) and the MB/SK level-shift rule. No test touches the network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from household_credit_stress import arrears_model, backtest


def _panel(
    months: pd.DatetimeIndex,
    rate_bp: np.ndarray,
    unemployment_by_calendar: pd.Series,
    mortgage_by_calendar: pd.Series,
) -> pd.DataFrame:
    """Panel rows for one region, laid out like `features.build_feature_panel`.

    The row at month L holds the drivers for calendar month L+1 (the one-month lead).
    """
    next_month = months + pd.DateOffset(months=1)
    return pd.DataFrame(
        {
            "month": months,
            "region": "ON",
            "arrears_rate_bp": rate_bp,
            "unemployment_rate": unemployment_by_calendar.reindex(next_month).to_numpy(),
            "mortgage_rate_5y": mortgage_by_calendar.reindex(next_month).to_numpy(),
        }
    )


def _simulate(
    n_months: int,
    phi: float,
    b_u: float,
    b_m: float,
    noise_sd: float,
    seed: int = 0,
    jump_month: pd.Timestamp | None = None,
    jump_bp: float = 0.0,
) -> pd.DataFrame:
    """A region whose arrears follow the ADR 0003 equation exactly, plus noise."""
    rng = np.random.default_rng(seed)
    lead_in = arrears_model.LAG_MONTHS + arrears_model.WINDOW_MONTHS
    calendar = pd.date_range("1990-01-01", periods=n_months + lead_in + 1, freq="MS")
    u = pd.Series(7.0 + np.cumsum(rng.normal(0, 0.15, len(calendar))), index=calendar)
    m = pd.Series(6.0 + np.cumsum(rng.normal(0, 0.10, len(calendar))), index=calendar)
    drivers = pd.DataFrame({"unemployment_rate": u, "mortgage_rate_5y": m})
    terms = arrears_model.driver_terms(drivers)

    months = calendar[lead_in : lead_in + n_months]
    x_u = terms["x_u"].reindex(months).to_numpy(dtype=float)
    x_m = terms["x_m"].reindex(months).to_numpy(dtype=float)
    level = 50.0
    change = 0.0
    levels = []
    for i, t in enumerate(months):
        change = phi * change + b_u * x_u[i] + b_m * x_m[i] + rng.normal(0, noise_sd)
        level += change
        if jump_month is not None and t == jump_month:
            level += jump_bp
        levels.append(level)
    return _panel(months, np.array(levels), u, m)


# Rebuilding the drivers by calendar month ------------------------------------------


def test_calendar_drivers_undo_the_one_month_lead() -> None:
    months = pd.date_range("2020-01-01", periods=3, freq="MS")
    panel = pd.DataFrame(
        {
            "month": months,
            "arrears_rate_bp": [20.0, 21.0, 22.0],
            "unemployment_rate": [5.0, 6.0, 7.0],
            "mortgage_rate_5y": [4.0, 4.5, 5.0],
        }
    )
    drivers = arrears_model.calendar_drivers(panel)
    assert list(drivers.index) == list(months + pd.DateOffset(months=1))
    assert drivers.loc[pd.Timestamp("2020-04-01"), "unemployment_rate"] == 7.0
    assert drivers.loc[pd.Timestamp("2020-02-01"), "mortgage_rate_5y"] == 4.0


def test_driver_terms_average_change_over_window_ending_two_months_back() -> None:
    calendar = pd.date_range("2000-01-01", periods=20, freq="MS")
    drivers = pd.DataFrame(
        {"unemployment_rate": np.arange(20, dtype=float), "mortgage_rate_5y": 2.0 * np.arange(20)},
        index=calendar,
    )
    terms = arrears_model.driver_terms(drivers)
    # x(t) = (v(t-2) - v(t-14)) / 12. With v rising by 1 a month, x is 1 wherever defined.
    first = calendar[0] + pd.DateOffset(months=14)
    assert terms.loc[first, "x_u"] == pytest.approx(1.0)
    assert terms.loc[first, "x_m"] == pytest.approx(2.0)
    assert bool(terms["x_u"].isna().loc[first - pd.DateOffset(months=1)])
    # Terms reach two months past the last driver month, and no further.
    assert terms.index.max() == calendar[-1] + pd.DateOffset(months=2)


# Fitting -----------------------------------------------------------------------------


def test_fit_recovers_known_slopes() -> None:
    panel = _simulate(n_months=300, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    cutoff = panel["month"].max()
    fit = arrears_model.fit_arx(panel, cutoff)
    assert fit.phi == pytest.approx(0.3, abs=0.05)
    assert fit.beta_unemployment == pytest.approx(4.0, abs=0.3)
    assert fit.beta_rate == pytest.approx(2.0, abs=0.3)
    assert fit.cutoff == cutoff
    assert fit.n_obs > arrears_model.MIN_FIT_ROWS


def test_flat_drivers_give_the_ar1_baseline() -> None:
    """With unemployment and the mortgage rate flat, both slopes are zero and the
    model is exactly the AR(1) baseline (ADR 0003, "Decision")."""
    rng = np.random.default_rng(1)
    calendar = pd.date_range("1990-01-01", periods=140, freq="MS")
    flat = pd.Series(6.0, index=calendar)
    months = calendar[20:139]
    rate = 40.0 + np.cumsum(rng.normal(0, 1.0, len(months)))
    panel = _panel(months, rate, flat, flat)
    cutoff = months[-1]

    fit = arrears_model.fit_arx(panel, cutoff)
    # The first driver term exists at months[0] + 1 + 14 (the lead, then the lag and
    # window). The baseline sees the same rows if its history starts two months earlier.
    first_term = months[0] + pd.DateOffset(months=1 + 14)
    history = panel.set_index("month")["arrears_rate_bp"]
    history = history.loc[first_term - pd.DateOffset(months=2) :]
    assert fit.beta_unemployment == pytest.approx(0.0, abs=1e-12)
    assert fit.beta_rate == pytest.approx(0.0, abs=1e-12)
    assert fit.phi == pytest.approx(backtest.fit_ar1(history, cutoff))
    for h in (1, 3):
        assert arrears_model.forecast_arx(panel, cutoff, h, fit) == pytest.approx(
            backtest.forecast_ar1(history, cutoff, h, fit.phi)
        )


def test_level_shift_month_is_dropped_from_the_fit() -> None:
    jump = pd.Timestamp("2006-11-01")
    panel = _simulate(
        n_months=300, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05, jump_month=jump, jump_bp=40.0
    )
    cutoff = panel["month"].max()
    with_drop = arrears_model.fit_arx(panel, cutoff, drop_diff_month=jump)
    without_drop = arrears_model.fit_arx(panel, cutoff)
    assert with_drop.phi == pytest.approx(0.3, abs=0.05)
    assert with_drop.beta_unemployment == pytest.approx(4.0, abs=0.3)
    assert with_drop.n_obs == without_drop.n_obs - 2
    assert abs(without_drop.phi - 0.3) > abs(with_drop.phi - 0.3)


def test_fit_with_too_few_rows_raises() -> None:
    panel = _simulate(n_months=300, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    short = panel.iloc[: arrears_model.MIN_FIT_ROWS]
    with pytest.raises(ValueError, match="too few"):
        arrears_model.fit_arx(short, short["month"].max())


def test_fit_without_a_row_at_the_cutoff_raises() -> None:
    panel = _simulate(n_months=120, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    with pytest.raises(ValueError, match="no row"):
        arrears_model.fit_arx(panel.iloc[:-1], panel["month"].max())


# No look-ahead -----------------------------------------------------------------------


def test_fit_raises_on_rows_after_the_cutoff() -> None:
    panel = _simulate(n_months=120, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    cutoff = panel["month"].iloc[-2]
    with pytest.raises(ValueError, match="look-ahead"):
        arrears_model.fit_arx(panel, cutoff)


def test_forecast_raises_on_rows_after_the_cutoff() -> None:
    panel = _simulate(n_months=120, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    cutoff = panel["month"].iloc[-2]
    fit = arrears_model.fit_arx(panel.iloc[:-1], cutoff)
    with pytest.raises(ValueError, match="look-ahead"):
        arrears_model.forecast_arx(panel, cutoff, 1, fit)


def test_forecast_ignores_everything_after_the_origin() -> None:
    """Truncating at L gives the same forecast whatever the full panel holds later."""
    panel = _simulate(n_months=200, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    origin = panel["month"].iloc[150]
    known = panel[panel["month"] <= origin]
    altered = panel.copy()
    later = altered["month"] > origin
    altered.loc[later, ["arrears_rate_bp", "unemployment_rate", "mortgage_rate_5y"]] = 999.0
    known_altered = altered[altered["month"] <= origin]
    fit_a = arrears_model.fit_arx(known, origin)
    fit_b = arrears_model.fit_arx(known_altered, origin)
    assert fit_a == fit_b
    for h in (1, 3):
        assert arrears_model.forecast_arx(known, origin, h, fit_a) == arrears_model.forecast_arx(
            known_altered, origin, h, fit_b
        )


def test_horizon_past_the_known_drivers_raises() -> None:
    """At L the drivers are known through L+1, so the terms reach L+3 and no further."""
    panel = _simulate(n_months=120, phi=0.3, b_u=4.0, b_m=2.0, noise_sd=0.05)
    cutoff = panel["month"].max()
    fit = arrears_model.fit_arx(panel, cutoff)
    assert np.isfinite(arrears_model.forecast_arx(panel, cutoff, 3, fit))
    with pytest.raises(ValueError, match="driver"):
        arrears_model.forecast_arx(panel, cutoff, 4, fit)
    with pytest.raises(ValueError, match="horizon"):
        arrears_model.forecast_arx(panel, cutoff, 0, fit)


# Running forward ---------------------------------------------------------------------


def test_run_forward_by_hand() -> None:
    path = arrears_model.run_forward(
        level=30.0,
        last_change=2.0,
        phi=0.5,
        beta_unemployment=10.0,
        beta_rate=-4.0,
        x_u=[0.1, 0.0],
        x_m=[0.5, 0.25],
    )
    # d1 = 0.5*2 + 10*0.1 - 4*0.5 = 0.0; d2 = 0.5*0 + 0 - 4*0.25 = -1.0
    assert path == pytest.approx([30.0, 29.0])


def test_run_forward_needs_equal_paths() -> None:
    with pytest.raises(ValueError, match="same length"):
        arrears_model.run_forward(30.0, 0.0, 0.5, 1.0, 1.0, x_u=[0.1], x_m=[0.1, 0.2])
