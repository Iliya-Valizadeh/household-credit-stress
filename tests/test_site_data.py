"""Tests for the JSON exports the static page in `site/` reads (T10).

Checks: `build_scenario_payload` has the shape the page's JS expects and its rounded
numbers still reconstruct a region's path within a fraction of a basis point;
`build_ledger_payload` joins forecasts with outcomes, and leaves `actual_bp: null` when
a target is ungraded or `ledger/outcomes.csv` does not exist yet; `write_site_data`
writes every file and skips a reports file that is not there yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from household_credit_stress import backtest, scenario, site_data

REPO = Path(__file__).resolve().parent.parent


def _row(origin: str, target: str, horizon: int, region: str = "CA") -> dict[str, object]:
    return {
        "origin_month": origin,
        "target_month": target,
        "horizon": horizon,
        "region": region,
        "forecast_bp": 50.0,
        "lo80_bp": 45.0,
        "hi80_bp": 55.0,
        "persistence_bp": 49.0,
        "ar1_bp": 49.5,
        "arrears_through": origin,
        "unemployment_through": origin,
        "rate_through": origin,
        "model_version": "0.1.0",
        "written_at": "2026-10-07T00:00:00+00:00",
    }


FORECASTS_COLUMNS = list(_row("2026-07", "2026-08", 1).keys())


def _write_forecasts(ledger_dir: Path, rows: list[dict[str, object]]) -> None:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=FORECASTS_COLUMNS).to_csv(ledger_dir / "forecasts.csv", index=False)


# --- scenario.json -----------------------------------------------------------------


@pytest.fixture(scope="module")
def scenario_payload() -> dict[str, Any]:
    return site_data.build_scenario_payload(REPO / "data")


def test_build_scenario_payload_has_the_expected_shape(scenario_payload: dict[str, Any]) -> None:
    payload = scenario_payload
    assert payload["regions"] == list(scenario.REGIONS)
    assert len(payload["target_months"]) == scenario.HORIZON_MONTHS
    assert set(payload["by_region"]) == set(scenario.REGIONS)
    for region in scenario.REGIONS:
        region_payload = payload["by_region"][region]
        assert len(region_payload["baseline_path"]) == scenario.HORIZON_MONTHS
        assert len(region_payload["sensitivity_unemployment"]) == scenario.HORIZON_MONTHS
        assert len(region_payload["sensitivity_unemployment"][0]) == scenario.HORIZON_MONTHS
        assert len(region_payload["sensitivity_rate"]) == scenario.HORIZON_MONTHS
    for driver in ("unemployment_rate", "mortgage_rate_5y"):
        bounds = payload["ranges"][driver]
        assert bounds["level_widened_low"] <= bounds["level_low"]
        assert bounds["level_widened_high"] >= bounds["level_high"]
    assert set(payload["ca"]["mortgage_weights"]) == set(scenario.REGIONS)
    assert json.dumps(payload)  # every value is JSON-safe


def test_build_scenario_payload_rounded_numbers_still_reconstruct_run_region(
    scenario_payload: dict[str, Any],
) -> None:
    """The page adds baseline_path to the sensitivities times the user's path and runs
    no model of its own (ADR 0004); rounding for the JSON file must not move that sum
    off the real path by more than a sliver of a basis point."""
    panel = backtest.load_panel(REPO / "data")
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)
    region = "ON"
    region_payload = scenario_payload["by_region"][region]

    last_u = region_payload["last_unemployment"]
    last_m = region_payload["last_rate"]
    u_path = scenario.path_from_changes(last_u, 1.0, 2.0)
    m_path = scenario.path_from_changes(last_m, -0.5, 0.5)
    direct = scenario.run_region(panel, region, cutoff, fit, u_path, m_path)

    baseline = np.array(region_payload["baseline_path"])
    sens_u = np.array(region_payload["sensitivity_unemployment"])
    sens_m = np.array(region_payload["sensitivity_rate"])
    reconstructed = baseline + sens_u @ (u_path - last_u) + sens_m @ (m_path - last_m)
    reconstructed = np.where(reconstructed < 0.0, 0.0, reconstructed)

    np.testing.assert_allclose(reconstructed, direct.path_bp, atol=0.05)


# --- ledger.json --------------------------------------------------------------------


def test_build_ledger_payload_joins_a_graded_outcome(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    _write_forecasts(
        ledger_dir,
        [_row("2026-07", "2026-08", 1, "CA"), _row("2026-07", "2026-10", 3, "CA")],
    )
    pd.DataFrame([{"target_month": "2026-08", "region": "CA", "actual_bp": 48.5}]).to_csv(
        ledger_dir / "outcomes.csv", index=False
    )

    payload = site_data.build_ledger_payload(ledger_dir)

    by_target = {row["target_month"]: row for row in payload["rows"]}
    assert by_target["2026-08"]["actual_bp"] == pytest.approx(48.5)
    assert by_target["2026-10"]["actual_bp"] is None
    assert json.dumps(payload)


def test_build_ledger_payload_without_an_outcomes_file(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    _write_forecasts(ledger_dir, [_row("2026-07", "2026-08", 1, "CA")])
    assert not (ledger_dir / "outcomes.csv").exists()

    payload = site_data.build_ledger_payload(ledger_dir)

    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["actual_bp"] is None


# --- write_site_data -----------------------------------------------------------------


def test_write_site_data_writes_every_file_and_skips_missing_reports(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    _write_forecasts(ledger_dir, [_row("2026-07", "2026-08", 1, "CA")])
    reports_dir = tmp_path / "reports"  # left empty: no scenario_metrics.json yet
    site_data_dir = tmp_path / "site" / "data"

    written = site_data.write_site_data(
        data_dir=REPO / "data",
        reports_dir=reports_dir,
        ledger_dir=ledger_dir,
        site_data_dir=site_data_dir,
    )

    names = {p.name for p in written}
    assert {"scenario.json", "ledger.json", "status.json"} <= names
    assert "scenario_metrics.json" not in names
    for path in written:
        with path.open(encoding="utf-8") as fh:
            json.load(fh)  # every written file parses as JSON
