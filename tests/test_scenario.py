"""Tests for the ADR 0004 scenario engine (docs/decisions/0004-scenarios.md). No test
touches the network; the real-data tests below read the committed CSVs under
`data/processed`, exactly as `tests/test_backtest.py` already does for the backtest.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from household_credit_stress import arrears_model, backtest, evaluate_scenario, scenario

REPO = Path(__file__).resolve().parent.parent


# --- helpers for a synthetic multi-region panel ---------------------------------------


def _region_rows(
    months: pd.DatetimeIndex,
    region: str,
    rate_bp: np.ndarray,
    unemployment_by_calendar: pd.Series,
    mortgage_by_calendar: pd.Series,
    mortgages: float = 1_000.0,
) -> pd.DataFrame:
    """Panel rows for one region, laid out like `features.build_feature_panel`: the
    row at month L holds the drivers for calendar month L+1."""
    next_month = months + pd.DateOffset(months=1)
    return pd.DataFrame(
        {
            "month": months,
            "region": region,
            "mortgages": mortgages,
            "arrears_rate_bp": rate_bp,
            "unemployment_rate": unemployment_by_calendar.reindex(next_month).to_numpy(),
            "mortgage_rate_5y": mortgage_by_calendar.reindex(next_month).to_numpy(),
        }
    )


def _toy_panel(
    phi_by_region: dict[str, float],
    b_u: float,
    b_m: float,
    n_months: int = 60,
    mortgages: dict[str, float] | None = None,
    noise_sd: float = 0.0,
    seed: int = 0,
) -> pd.DataFrame:
    """A panel of several regions that exactly follow the ADR 0004 pooled equation
    (shared `b_u`, `b_m`, each region's own `phi`), plus a CA row with its own level
    and the given mortgage weights. No noise by default, so a fit should recover the
    coefficients exactly."""
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
    mortgages = mortgages or {region: 1_000.0 for region in phi_by_region}

    frames = []
    ca_level = 0.0
    ca_weighted_change = np.zeros(n_months)
    total_weight = sum(mortgages[r] for r in phi_by_region)
    for region, phi in phi_by_region.items():
        level = 50.0 + hash(region) % 7  # distinct starting levels
        change = 0.0
        levels = []
        for i in range(n_months):
            change = phi * change + b_u * x_u[i] + b_m * x_m[i] + rng.normal(0, noise_sd)
            level += change
            levels.append(level)
        frames.append(
            _region_rows(months, region, np.array(levels), u, m, mortgages=mortgages[region])
        )
        start_level = 50.0 + hash(region) % 7
        ca_weighted_change += (mortgages[region] / total_weight) * (np.array(levels) - start_level)
        ca_level = 40.0  # arbitrary, independent CA starting level

    ca_rate = ca_level + ca_weighted_change
    frames.append(_region_rows(months, "CA", ca_rate, u, m, mortgages=total_weight))
    return pd.concat(frames, ignore_index=True)


PHI = {"ATL": 0.2, "QC": 0.1, "ON": 0.3, "MB": 0.05, "SK": 0.0, "AB": 0.4, "BC": 0.15}


# --- the pooled fit and its sign rule --------------------------------------------------


def test_pooled_fit_recovers_exact_shared_and_per_region_coefficients() -> None:
    panel = _toy_panel(PHI, b_u=1.5, b_m=0.8)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    assert fit.dropped == ()
    assert fit.beta_unemployment == pytest.approx(1.5, abs=1e-6)
    assert fit.beta_rate == pytest.approx(0.8, abs=1e-6)
    for region, phi in PHI.items():
        assert fit.phi[region] == pytest.approx(phi, abs=1e-6)


def _direct_refit(panel: pd.DataFrame, cutoff: pd.Timestamp, keep_column: str) -> np.ndarray:
    """An independent least-squares solve on the pooled design, using only
    `keep_column` (plus the per-region phi columns), to check `fit_pooled_arx`'s
    refit branch against (not the DGP's true coefficients, which omitted-variable
    bias makes an unreliable target once a driver is dropped)."""
    design, target = scenario._stacked_design(panel, cutoff, scenario.REGIONS)
    columns = [f"phi_{r}" for r in scenario.REGIONS] + [keep_column]
    coef, *_ = np.linalg.lstsq(
        design[columns].to_numpy(dtype=float), target.to_numpy(dtype=float), rcond=None
    )
    return np.asarray(coef, dtype=float)


def test_sign_rule_drops_a_wrong_signed_unemployment_slope() -> None:
    panel = _toy_panel(PHI, b_u=-1.0, b_m=0.8)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    assert fit.dropped == ("unemployment_rate",)
    assert fit.beta_unemployment == 0.0
    assert not fit.no_scenario

    coef = _direct_refit(panel, cutoff, "x_m")
    assert fit.beta_rate == pytest.approx(float(coef[-1]), abs=1e-9)
    for i, region in enumerate(scenario.REGIONS):
        assert fit.phi[region] == pytest.approx(float(coef[i]), abs=1e-9)


def test_sign_rule_drops_a_wrong_signed_rate_slope() -> None:
    panel = _toy_panel(PHI, b_u=1.5, b_m=-0.4)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    assert fit.dropped == ("mortgage_rate_5y",)
    assert fit.beta_rate == 0.0

    coef = _direct_refit(panel, cutoff, "x_u")
    assert fit.beta_unemployment == pytest.approx(float(coef[-1]), abs=1e-9)
    for i, region in enumerate(scenario.REGIONS):
        assert fit.phi[region] == pytest.approx(float(coef[i]), abs=1e-9)


def test_sign_rule_draws_no_scenario_when_both_slopes_are_wrong() -> None:
    panel = _toy_panel(PHI, b_u=-1.0, b_m=-0.4)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    assert fit.no_scenario
    assert fit.dropped == ("unemployment_rate", "mortgage_rate_5y")
    assert fit.beta_unemployment == 0.0
    assert fit.beta_rate == 0.0


def test_fit_raises_with_too_few_rows() -> None:
    panel = _toy_panel(PHI, b_u=1.0, b_m=1.0, n_months=3)
    cutoff = pd.Timestamp(panel["month"].max())
    with pytest.raises(ValueError, match="too few rows"):
        scenario.fit_pooled_arx(panel, cutoff)


def test_fit_drops_deferral_month_rows() -> None:
    """A deferral-month jump in one region must not pull the pooled fit off the
    true coefficients, because those rows are dropped (ADR 0004)."""
    clean = _toy_panel(PHI, b_u=1.0, b_m=1.0, n_months=400)
    jump = clean.copy()
    jump_row = (jump["region"] == "ON") & (jump["month"] == scenario.DEFERRAL_START)
    assert jump_row.any()
    jump.loc[jump_row, "arrears_rate_bp"] += 5_000.0
    # Every later ON row shifts too, since arrears_rate_bp is a level.
    later = (jump["region"] == "ON") & (jump["month"] > scenario.DEFERRAL_START)
    jump.loc[later, "arrears_rate_bp"] += 5_000.0

    cutoff = pd.Timestamp(clean["month"].max())
    clean_fit = scenario.fit_pooled_arx(clean, cutoff)
    jump_fit = scenario.fit_pooled_arx(jump, cutoff)
    assert jump_fit.beta_unemployment == pytest.approx(clean_fit.beta_unemployment, abs=1e-6)
    assert jump_fit.beta_rate == pytest.approx(clean_fit.beta_rate, abs=1e-6)


# --- driver paths ------------------------------------------------------------------------


def test_path_from_changes_hits_the_two_anchor_points() -> None:
    path = scenario.path_from_changes(last_value=7.0, change_12m=1.0, change_24m=3.0, n_months=24)
    assert path[11] == pytest.approx(8.0)  # k=12
    assert path[23] == pytest.approx(10.0)  # k=24
    assert path[5] == pytest.approx(7.0 + 1.0 * 6 / 12)  # halfway to the 12-month point


def test_national_path_for_regions_applies_the_same_change_everywhere() -> None:
    last_values = {"ON": 6.0, "QC": 8.0}
    paths = scenario.national_path_for_regions(
        last_values, change_12m=2.0, change_24m=2.0, n_months=12
    )
    assert paths["ON"][-1] == pytest.approx(8.0)
    assert paths["QC"][-1] == pytest.approx(10.0)


# --- running a path forward --------------------------------------------------------------


def test_run_region_floors_at_zero_and_flags_the_floored_months() -> None:
    panel = _toy_panel(PHI, b_u=1.0, b_m=1.0, n_months=60)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    region_panel = panel.loc[(panel["region"] == "ON") & (panel["month"] <= cutoff)]
    last_u = float(arrears_model.calendar_drivers(region_panel)["unemployment_rate"].iloc[-1])
    last_m = float(arrears_model.calendar_drivers(region_panel)["mortgage_rate_5y"].iloc[-1])
    # A large drop in both drivers, with the sign-correct positive slopes, should
    # push the path below zero and trigger the floor.
    u_path = scenario.path_from_changes(last_u, -50.0, -50.0)
    m_path = scenario.path_from_changes(last_m, -50.0, -50.0)
    result = scenario.run_region(panel, "ON", cutoff, fit, u_path, m_path)
    assert result.floored.any()
    assert (result.path_bp[result.floored] == 0.0).all()
    assert (result.path_bp >= 0.0).all()


def test_run_region_raises_if_the_driver_path_is_too_short() -> None:
    panel = _toy_panel(PHI, b_u=1.0, b_m=1.0, n_months=60)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    with pytest.raises(ValueError, match="driver path"):
        scenario.run_region(panel, "ON", cutoff, fit, np.array([7.0]), np.array([6.0]))


def test_run_ca_is_the_mortgage_weighted_average_of_the_seven_regions() -> None:
    mortgages = {
        "ATL": 100.0,
        "QC": 300.0,
        "ON": 600.0,
        "MB": 50.0,
        "SK": 50.0,
        "AB": 200.0,
        "BC": 150.0,
    }
    panel = _toy_panel(PHI, b_u=1.2, b_m=0.6, mortgages=mortgages)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)

    region_results = {}
    for region in scenario.REGIONS:
        region_panel = panel.loc[(panel["region"] == region) & (panel["month"] <= cutoff)]
        last_u = float(arrears_model.calendar_drivers(region_panel)["unemployment_rate"].iloc[-1])
        last_m = float(arrears_model.calendar_drivers(region_panel)["mortgage_rate_5y"].iloc[-1])
        u_path = scenario.path_from_changes(last_u, 1.0, 1.0)
        m_path = scenario.path_from_changes(last_m, 0.5, 0.5)
        region_results[region] = scenario.run_region(panel, region, cutoff, fit, u_path, m_path)

    ca = scenario.run_ca(panel, cutoff, region_results)
    ca_known = panel.loc[(panel["region"] == "CA") & (panel["month"] == cutoff)]
    ca_level = float(ca_known["arrears_rate_bp"].iloc[0])
    total = sum(mortgages.values())

    expected_change = np.zeros(scenario.HORIZON_MONTHS)
    for region, result in region_results.items():
        region_level = float(
            panel.loc[
                (panel["region"] == region) & (panel["month"] == cutoff), "arrears_rate_bp"
            ].iloc[0]
        )
        expected_change += (mortgages[region] / total) * (result.path_bp - region_level)
    expected = np.where(ca_level + expected_change < 0.0, 0.0, ca_level + expected_change)
    np.testing.assert_allclose(ca.path_bp, expected)


# --- the linear decomposition -------------------------------------------------------------


def test_region_sensitivities_sum_matches_run_region_on_a_toy_path() -> None:
    panel = _toy_panel(PHI, b_u=1.1, b_m=0.7, n_months=60)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    region_panel = panel.loc[(panel["region"] == "ON") & (panel["month"] <= cutoff)]
    last_u = float(arrears_model.calendar_drivers(region_panel)["unemployment_rate"].iloc[-1])
    last_m = float(arrears_model.calendar_drivers(region_panel)["mortgage_rate_5y"].iloc[-1])

    u_path = scenario.path_from_changes(last_u, 2.0, -1.0)
    m_path = scenario.path_from_changes(last_m, -0.5, 1.5)
    direct = scenario.run_region(panel, "ON", cutoff, fit, u_path, m_path)

    sens = scenario.region_sensitivities(panel, "ON", cutoff, fit)
    u_delta = u_path - sens.last_unemployment
    m_delta = m_path - sens.last_rate
    reconstructed = (
        sens.baseline_path
        + sens.sensitivity_unemployment @ u_delta
        + sens.sensitivity_rate @ m_delta
    )
    np.testing.assert_allclose(reconstructed, direct.path_bp, atol=1e-8)


@pytest.mark.parametrize("region", list(backtest.PRIMARY_REGIONS))
def test_region_sensitivities_sum_matches_run_region_on_every_committed_preset(region: str) -> None:
    """ADR 0004: "a test checks that the sum matches run_forward on every preset"."""
    panel = backtest.load_panel(REPO / "data")
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    if fit.no_scenario:
        pytest.skip("the sign rule dropped both drivers at the committed data's last origin")

    unemployment = pd.read_csv(REPO / "data/processed/unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(REPO / "data/processed/mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force = pd.read_csv(REPO / "data/processed/labour_force.csv", parse_dates=["month"])
    presets = scenario.build_presets(unemployment, mortgage_rate, labour_force)
    if all(p.rate_change is None for p in presets):
        pytest.skip("no preset has a rate path yet")

    region_panel = panel.loc[(panel["region"] == region) & (panel["month"] <= cutoff)]
    last_u = float(arrears_model.calendar_drivers(region_panel)["unemployment_rate"].iloc[-1])
    last_m = float(arrears_model.calendar_drivers(region_panel)["mortgage_rate_5y"].iloc[-1])
    sens = scenario.region_sensitivities(panel, region, cutoff, fit)

    for preset in presets:
        if preset.rate_change is None:
            continue
        u_path = last_u + preset.unemployment_change[region]
        m_path = last_m + preset.rate_change
        direct = scenario.run_region(panel, region, cutoff, fit, u_path, m_path)
        n = len(u_path)
        u_delta = u_path - sens.last_unemployment
        m_delta = m_path - sens.last_rate
        reconstructed = (
            sens.baseline_path
            + sens.sensitivity_unemployment[:, :n] @ u_delta
            + sens.sensitivity_rate[:, :n] @ m_delta
        )
        np.testing.assert_allclose(reconstructed, direct.path_bp, atol=1e-6)


# --- the honest range of inputs ------------------------------------------------------------


def test_classify_ok_beyond_history_and_refuses_past_the_widened_range() -> None:
    assert scenario.classify(5.0, low=0.0, high=10.0, widened_low=-5.0, widened_high=15.0) == "ok"
    assert (
        scenario.classify(12.0, low=0.0, high=10.0, widened_low=-5.0, widened_high=15.0)
        == "beyond_history"
    )
    with pytest.raises(ValueError, match="widened range"):
        scenario.classify(100.0, low=0.0, high=10.0, widened_low=-5.0, widened_high=15.0)


def test_honest_range_widens_by_half_its_width_on_each_side() -> None:
    rng = scenario.HonestRange(term_low=-1.0, term_high=1.0, level_low=0.0, level_high=10.0)
    (term_low, term_high), (level_low, level_high) = rng.widened()
    assert term_low == pytest.approx(-2.0)
    assert term_high == pytest.approx(2.0)
    assert level_low == pytest.approx(-5.0)
    assert level_high == pytest.approx(15.0)


def test_driver_ranges_on_real_data_covers_unemployment_since_1976_and_rate_since_its_start() -> (
    None
):
    panel = backtest.load_panel(REPO / "data")
    cutoff = pd.Timestamp(panel["month"].max())
    unemployment = pd.read_csv(REPO / "data/processed/unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(REPO / "data/processed/mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force = pd.read_csv(REPO / "data/processed/labour_force.csv", parse_dates=["month"])
    ranges = scenario.driver_ranges(panel, unemployment, mortgage_rate, labour_force, cutoff)
    assert set(ranges) == {"unemployment_rate", "mortgage_rate_5y"}
    assert (
        ranges["unemployment_rate"].level_low
        <= unemployment.loc[unemployment["region"] != "CA", "unemployment_rate"].min()
    )
    assert ranges["mortgage_rate_5y"].level_high >= mortgage_rate["value"].max() - 1e-9


# --- presets from history -------------------------------------------------------------------


def test_build_presets_matches_the_adr_start_months_on_committed_data() -> None:
    unemployment = pd.read_csv(REPO / "data/processed/unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(REPO / "data/processed/mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force = pd.read_csv(REPO / "data/processed/labour_force.csv", parse_dates=["month"])
    presets = scenario.build_presets(unemployment, mortgage_rate, labour_force)
    starts = {p.name: p.start_month for p in presets}
    assert starts == {rule.name: rule.expected_start for rule in scenario.PRESET_RULES}
    for preset in presets:
        assert len(preset.unemployment_change["ON"]) == scenario.PRESET_MONTHS


def test_build_presets_raises_if_the_recomputed_start_month_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_rule = scenario.PresetRule(
        "bad",
        "unemployment_rate",
        pd.Timestamp("1989-01-01"),
        pd.Timestamp("1990-12-01"),
        pd.Timestamp("1900-01-01"),  # deliberately wrong
    )
    monkeypatch.setattr(scenario, "PRESET_RULES", (bad_rule,))
    unemployment = pd.read_csv(REPO / "data/processed/unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(REPO / "data/processed/mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force = pd.read_csv(REPO / "data/processed/labour_force.csv", parse_dates=["month"])
    with pytest.raises(ValueError, match="recomputed start month"):
        scenario.build_presets(unemployment, mortgage_rate, labour_force)


def test_preset_to_dict_is_json_safe_and_rounds() -> None:
    preset = scenario.Preset(
        name="x",
        start_month=pd.Timestamp("2000-01-01"),
        unemployment_change={"ON": np.array([1.23456, 2.0])},
        rate_change=np.array([0.1111, 0.2222]),
        rate_note=None,
    )
    data = scenario.preset_to_dict(preset)
    json.dumps(data)  # must not raise
    assert data["start_month"] == "2000-01"
    assert data["unemployment_change"]["ON"] == [1.23, 2.0]
    assert data["rate_change"] == [0.11, 0.22]


# --- the conditional backtest, verdict and label ----------------------------------------


def _conditional_rows(
    model_errors: dict[int, list[float]], baseline_errors: dict[int, list[float]]
) -> pd.DataFrame:
    """Build minimal conditional-backtest rows for `summarize_check`/`bands_...`:
    one region (ATL), with as many origins as there are errors per horizon."""
    rows = []
    for h, errors in model_errors.items():
        for i, error in enumerate(errors):
            origin = pd.Timestamp("2017-01-01") + pd.DateOffset(months=i)
            rows.append(
                {
                    "origin_month": origin,
                    "target_month": origin + pd.DateOffset(months=h),
                    "horizon": h,
                    "region": "ATL",
                    "model": scenario.MODEL_NAME,
                    "forecast_bp": 0.0,
                    "actual_bp": error,
                    "error_bp": error,
                    "abs_error_bp": abs(error),
                    "period": "test",
                }
            )
    for h, errors in baseline_errors.items():
        for i, error in enumerate(errors):
            origin = pd.Timestamp("2017-01-01") + pd.DateOffset(months=i)
            for period, bump in (("dev", 0.0), ("test", 0.0)):
                rows.append(
                    {
                        "origin_month": origin,
                        "target_month": origin + pd.DateOffset(months=h),
                        "horizon": h,
                        "region": "ATL",
                        "model": "ar1",
                        "forecast_bp": 0.0,
                        "actual_bp": error + bump,
                        "error_bp": error + bump,
                        "abs_error_bp": abs(error + bump),
                        "period": period,
                    }
                )
            rows.append(
                {
                    "origin_month": origin,
                    "target_month": origin + pd.DateOffset(months=h),
                    "horizon": h,
                    "region": "ATL",
                    "model": "persistence",
                    "forecast_bp": 0.0,
                    "actual_bp": error * 3,
                    "error_bp": error * 3,
                    "abs_error_bp": abs(error * 3),
                    "period": "dev",
                }
            )
    return pd.DataFrame(rows, columns=scenario.CONDITIONAL_BACKTEST_COLUMNS)


def test_summarize_check_passes_and_labels_a_conditional_forecast() -> None:
    n = 30
    model_small = [0.1] * n  # tiny errors: model clearly better than ar1
    ar1_big = [5.0] * n
    rows = _conditional_rows({12: model_small, 24: model_small}, {12: ar1_big, 24: ar1_big})
    summary = scenario.summarize_check(rows)
    assert summary["label"] == scenario.CONDITIONAL_FORECAST_LABEL
    assert summary["label_reason"] is None
    assert summary["check"]["h12"]["passes"]
    assert summary["check"]["h24"]["passes"]


def test_summarize_check_fails_and_labels_illustrative() -> None:
    n = 30
    model_big = [5.0] * n  # model clearly worse than ar1
    ar1_small = [0.1] * n
    rows = _conditional_rows({12: model_big, 24: model_big}, {12: ar1_small, 24: ar1_small})
    summary = scenario.summarize_check(rows)
    assert summary["label"] == scenario.ILLUSTRATIVE_LABEL
    assert summary["label_reason"] == scenario.ILLUSTRATIVE_SENTENCE


def test_summarize_check_handles_no_rows() -> None:
    summary = scenario.summarize_check(pd.DataFrame(columns=scenario.CONDITIONAL_BACKTEST_COLUMNS))
    assert summary["label"] == scenario.ILLUSTRATIVE_LABEL
    assert summary["check"]["h12"] is None


def test_bands_by_region_and_horizon_uses_10th_and_90th_percentiles() -> None:
    errors = list(range(-10, 11))  # -10..10, so the 10th/90th percentiles are clean
    rows = []
    for i, error in enumerate(errors):
        rows.append(
            {
                "origin_month": pd.Timestamp("2010-01-01") + pd.DateOffset(months=i),
                "target_month": pd.Timestamp("2010-01-01") + pd.DateOffset(months=i + 12),
                "horizon": 12,
                "region": "ON",
                "model": scenario.MODEL_NAME,
                "forecast_bp": 0.0,
                "actual_bp": error,
                "error_bp": error,
                "abs_error_bp": abs(error),
                "period": "test",
            }
        )
    frame = pd.DataFrame(rows, columns=scenario.CONDITIONAL_BACKTEST_COLUMNS)
    bands = scenario.bands_by_region_and_horizon(frame, regions=("ON",), horizons=range(12, 13))
    band = bands["ON"]["h12"]
    assert band["n_origins"] == len(errors)
    assert band["lo80_bp"] == pytest.approx(float(np.percentile(errors, 10)), abs=0.5)
    assert band["hi80_bp"] == pytest.approx(float(np.percentile(errors, 90)), abs=0.5)


def test_run_conditional_backtest_only_scores_published_targets() -> None:
    panel = _toy_panel(PHI, b_u=1.0, b_m=1.0, n_months=60)
    origins = pd.date_range(
        panel["month"].min() + pd.DateOffset(months=40), panel["month"].max(), freq="MS"
    )
    rows = scenario.run_conditional_backtest(panel, origins, horizons=range(1, 4))
    assert not rows.empty
    for _, row in rows.iterrows():
        assert row["target_month"] <= panel["month"].max()
    # No row scores a horizon whose target is beyond the panel's last month.
    assert (rows["target_month"] <= panel["month"].max()).all()


# --- end-to-end reproducibility, like test_backtest.py's committed-metrics check ---------


def test_committed_scenario_reports_match_a_fresh_run() -> None:
    """reports/scenario_backtest.csv, reports/scenario_metrics.json and
    reports/scenario_presets.json must be what the code makes on the committed data.
    Run `python -m household_credit_stress.evaluate_scenario` if this fails."""
    fresh_metrics, fresh_rows = evaluate_scenario.run_scenario_evaluation(REPO / "data")
    committed_metrics = json.loads(
        (REPO / "reports" / evaluate_scenario.METRICS_FILE).read_text(encoding="utf-8")
    )
    assert committed_metrics == fresh_metrics

    committed_rows = pd.read_csv(
        REPO / "reports" / evaluate_scenario.BACKTEST_FILE,
        parse_dates=["origin_month", "target_month"],
    )
    pd.testing.assert_frame_equal(
        committed_rows, evaluate_scenario.committed_backtest_rows(fresh_rows)
    )

    fresh_presets = evaluate_scenario._presets_payload(REPO / "data")
    committed_presets = json.loads(
        (REPO / "reports" / evaluate_scenario.PRESETS_FILE).read_text(encoding="utf-8")
    )
    assert committed_presets == fresh_presets
