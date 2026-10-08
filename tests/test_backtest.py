"""Tests for the backtest harness and the two baselines (docs/eval_plan.md,
"Baselines" and "Backtest design"). No test touches the network.

The central property is no look-ahead: every baseline fit or forecast must raise if
it is given a feature dated after its cutoff, and the full backtest loop must give
the same forecast for an origin whether or not the input panel holds data past it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from household_credit_stress import backtest, evaluate

REPO = Path(__file__).resolve().parent.parent


def _series(pairs: list[tuple[str, float]]) -> pd.Series:
    index = pd.to_datetime([m for m, _ in pairs])
    return pd.Series([v for _, v in pairs], index=index)


# No look-ahead -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda history, cutoff: backtest.fit_ar1(history, cutoff),
        lambda history, cutoff: backtest.forecast_persistence(history, cutoff),
        lambda history, cutoff: backtest.forecast_ar1(history, cutoff, horizon=1, phi=0.0),
    ],
)
def test_a_feature_from_after_the_cutoff_raises(call: object) -> None:
    history = _series([("2020-01-01", 10.0), ("2020-02-01", 11.0), ("2020-03-01", 12.0)])
    with pytest.raises(ValueError, match="look-ahead"):
        call(history, pd.Timestamp("2020-02-01"))  # type: ignore[operator]


def test_a_feature_exactly_at_the_cutoff_is_fine() -> None:
    history = _series([("2020-01-01", 10.0), ("2020-02-01", 11.0)])
    assert backtest.forecast_persistence(history, pd.Timestamp("2020-02-01")) == 11.0


# Persistence ---------------------------------------------------------------------------


def test_persistence_forecast_is_the_latest_known_value() -> None:
    history = _series([("2020-01-01", 10.0), ("2020-02-01", 25.0)])
    assert backtest.forecast_persistence(history, pd.Timestamp("2020-02-01")) == 25.0


# AR(1) on the monthly change -----------------------------------------------------------


def test_fit_ar1_recovers_an_exact_linear_relationship() -> None:
    # Monthly changes that exactly follow d_t = 0.5 * d_{t-1}, so least squares
    # should recover phi = 0.5 exactly.
    phi = 0.5
    diffs = [8.0]
    for _ in range(10):
        diffs.append(phi * diffs[-1])
    levels = [100.0]
    for d in diffs:
        levels.append(levels[-1] + d)
    months = pd.date_range("2020-01-01", periods=len(levels), freq="MS")
    history = pd.Series(levels, index=months)

    fitted = backtest.fit_ar1(history, months[-1])
    assert fitted == pytest.approx(phi, abs=1e-9)


def test_fit_ar1_falls_back_to_zero_with_too_little_history() -> None:
    history = _series([("2020-01-01", 10.0), ("2020-02-01", 11.0)])
    assert backtest.fit_ar1(history, pd.Timestamp("2020-02-01")) == 0.0


def test_fit_ar1_drops_the_mb_sk_level_shift_month() -> None:
    # A mild +1/month drift, except a one-off +500 jump exactly at the MB/SK
    # reporting change (2006-11): without dropping it, that outlier would dominate
    # the least-squares fit.
    months = pd.date_range("2006-06-01", periods=12, freq="MS")
    level = 100.0
    levels = {}
    for month in months:
        level += 500.0 if month == backtest.MB_SK_LEVEL_SHIFT_MONTH else 1.0
        levels[month] = level
    history = pd.Series(levels)

    with_shift = backtest.fit_ar1(history, months[-1])
    without_shift = backtest.fit_ar1(
        history, months[-1], drop_diff_month=backtest.MB_SK_LEVEL_SHIFT_MONTH
    )
    assert with_shift != pytest.approx(without_shift)

    # Hand-build the same fit: drop the pair where the jump is the predicted value,
    # and the pair where it is the previous value.
    diffs = history.diff().dropna()
    pairs = pd.DataFrame({"prev": diffs.shift(1), "curr": diffs}).dropna()
    excluded = {
        backtest.MB_SK_LEVEL_SHIFT_MONTH,
        backtest.MB_SK_LEVEL_SHIFT_MONTH + pd.DateOffset(months=1),
    }
    pairs = pairs[~pairs.index.isin(excluded)]
    expected = float((pairs["prev"] * pairs["curr"]).sum() / (pairs["prev"] ** 2).sum())
    assert without_shift == pytest.approx(expected)


def test_forecast_ar1_matches_the_hand_computed_arima_formula() -> None:
    history = _series(
        [("2020-01-01", 100.0), ("2020-02-01", 104.0), ("2020-03-01", 106.0)]
    )  # last diff d(L) = 2.0
    phi = 0.25
    cutoff = pd.Timestamp("2020-03-01")

    h1 = backtest.forecast_ar1(history, cutoff, horizon=1, phi=phi)
    assert h1 == pytest.approx(106.0 + 2.0 * phi)

    h3 = backtest.forecast_ar1(history, cutoff, horizon=3, phi=phi)
    assert h3 == pytest.approx(106.0 + 2.0 * (phi + phi**2 + phi**3))


def test_forecast_ar1_with_phi_one_is_a_straight_line() -> None:
    history = _series([("2020-01-01", 100.0), ("2020-02-01", 103.0)])
    forecast = backtest.forecast_ar1(history, pd.Timestamp("2020-02-01"), horizon=3, phi=1.0)
    assert forecast == pytest.approx(103.0 + 3 * 3.0)


# The backtest loop -----------------------------------------------------------------------


def _toy_panel(region: str, rate_by_month: dict[str, float]) -> pd.DataFrame:
    # Only the columns run_backtest actually reads: month, region, arrears_rate_bp.
    months = pd.to_datetime(list(rate_by_month))
    rates = list(rate_by_month.values())
    return pd.DataFrame({"month": months, "region": region, "arrears_rate_bp": rates})


def _flat_rate_history(
    start: str, n_months: int, start_rate: float, step: float
) -> dict[str, float]:
    months = pd.date_range(start, periods=n_months, freq="MS")
    return {f"{m:%Y-%m}-01": start_rate + step * i for i, m in enumerate(months)}


def test_backtest_rows_only_cover_origins_whose_target_is_known() -> None:
    rates = _flat_rate_history("2006-01-01", 20, 50.0, 1.0)
    panel = _toy_panel("ON", rates)
    origins = pd.date_range("2007-01-01", "2007-08-01", freq="MS")  # last month in `rates`

    rows = backtest.run_backtest(panel, origins, regions=("ON",), horizons=(1, 3))

    # 2007-08 is the last known month, so h=3 cannot be scored from 2007-06 on.
    h3 = rows[rows["horizon"] == 3]
    assert h3["origin_month"].max() == pd.Timestamp("2007-05-01")
    h1 = rows[rows["horizon"] == 1]
    assert h1["origin_month"].max() == pd.Timestamp("2007-07-01")


def test_backtest_interval_is_blank_until_enough_history_then_filled() -> None:
    rates = _flat_rate_history("2006-01-01", 24, 50.0, 1.0)
    panel = _toy_panel("ON", rates)
    origins = pd.date_range("2007-01-01", "2007-12-01", freq="MS")

    rows = backtest.run_backtest(panel, origins, regions=("ON",), horizons=(1,))
    rows = rows.sort_values("origin_month")

    assert rows.iloc[0]["lo80_bp"] != rows.iloc[0]["lo80_bp"]  # NaN: no prior errors yet
    assert rows.iloc[-1]["lo80_bp"] == rows.iloc[-1]["lo80_bp"]  # filled in by the end


def test_backtest_has_no_lookahead_when_the_panel_holds_future_months() -> None:
    # 20 months, 2006-01 to 2007-08. Origins only run to 2007-05, so the farthest
    # target needed (h=3 from 2007-05) is 2007-08: the last original month, never the
    # wild future values added below.
    rates = _flat_rate_history("2006-01-01", 20, 50.0, 1.0)
    panel = _toy_panel("ON", rates)
    origins = pd.date_range("2007-01-01", "2007-05-01", freq="MS")
    rows_short = backtest.run_backtest(panel, origins, regions=("ON",), horizons=(1, 3))

    future_rates = _flat_rate_history("2006-01-01", 40, 50.0, 1.0)
    # Months from 2007-09 on are set to a wildly different level; if they leaked into
    # any origin in `origins` (all <= 2007-05), the forecasts below would change.
    for month in list(future_rates)[20:]:
        future_rates[month] = 9_999.0
    panel_with_future = _toy_panel("ON", future_rates)
    rows_long = backtest.run_backtest(panel_with_future, origins, regions=("ON",), horizons=(1, 3))

    pd.testing.assert_frame_equal(
        rows_short.reset_index(drop=True), rows_long.reset_index(drop=True)
    )


def test_run_backtest_drops_regions_with_no_history() -> None:
    rates = _flat_rate_history("2006-01-01", 20, 50.0, 1.0)
    panel = _toy_panel("ON", rates)
    origins = pd.date_range("2007-01-01", "2007-06-01", freq="MS")
    rows = backtest.run_backtest(panel, origins, regions=("ON", "BC"), horizons=(1,))
    assert set(rows["region"]) == {"ON"}


# Summaries --------------------------------------------------------------------------------


def test_summarize_picks_the_lower_dev_mae_baseline() -> None:
    origins = pd.date_range(backtest.DEV_START, periods=24, freq="MS")
    rows = []
    for region in backtest.PRIMARY_REGIONS:
        for origin in origins:
            rows.append(
                {
                    "origin_month": origin,
                    "target_month": origin + pd.DateOffset(months=1),
                    "horizon": 1,
                    "region": region,
                    "model": "persistence",
                    "forecast_bp": 0.0,
                    "lo80_bp": -1.0,
                    "hi80_bp": 1.0,
                    "actual_bp": 0.0,
                    "error_bp": 0.0,
                    "abs_error_bp": 1.0,
                    "period": "dev",
                }
            )
            rows.append(
                {
                    "origin_month": origin,
                    "target_month": origin + pd.DateOffset(months=1),
                    "horizon": 1,
                    "region": region,
                    "model": "ar1",
                    "forecast_bp": 0.0,
                    "lo80_bp": -1.0,
                    "hi80_bp": 1.0,
                    "actual_bp": 0.0,
                    "error_bp": 0.0,
                    "abs_error_bp": 5.0,
                    "period": "dev",
                }
            )
    rows_df = pd.DataFrame(rows)

    summary = backtest.summarize(rows_df)

    assert summary["baselines"]["persistence"]["h1"]["dev"]["mae_bp"]["value"] == pytest.approx(1.0)
    assert summary["baselines"]["ar1"]["h1"]["dev"]["mae_bp"]["value"] == pytest.approx(5.0)
    assert summary["best_baseline"]["h1"] == "persistence"
    assert summary["baselines"]["persistence"]["h1"]["dev"][
        "interval_coverage_80"
    ] == pytest.approx(1.0)


def test_summarize_handles_a_horizon_with_no_rows_yet() -> None:
    summary = backtest.summarize(pd.DataFrame(columns=backtest.BACKTEST_COLUMNS))
    assert summary["best_baseline"] == {}
    for model in backtest.MODELS:
        assert summary["baselines"][model]["h1"]["dev"] is None


# Reproducibility ----------------------------------------------------------------------------


def test_committed_backtest_and_metrics_match_a_fresh_run() -> None:
    """reports/backtest.csv and reports/metrics.json must be what the code makes on
    the committed data. Run `make eval` if this fails."""
    fresh_metrics, fresh_rows = evaluate.run_evaluation(REPO / "data")

    committed_metrics = json.loads((REPO / "reports" / "metrics.json").read_text(encoding="utf-8"))
    assert committed_metrics == fresh_metrics

    committed_rows = pd.read_csv(
        REPO / "reports" / "backtest.csv", parse_dates=["origin_month", "target_month"]
    )
    pd.testing.assert_frame_equal(
        committed_rows, fresh_rows.reset_index(drop=True), check_like=False
    )
