"""Tests for the live forecast ledger (docs/eval_plan.md, "Live forecast ledger").

Checks: `build_forecast_rows` produces one row per region and horizon with a sane
shape; the ledger is append-only (an existing region/horizon, or an already-graded
target/region, is never rewritten, and a file only ever grows); grading waits for the
CBA archive file that first reports a target month. No test touches the network.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from household_credit_stress import arrears_model, backtest, forecast

REGIONS = ("CA", "ON")
WRITTEN_AT = dt.datetime(2026, 10, 7, tzinfo=dt.UTC)


def _panel(region: str, seed: int, n_months: int = 40) -> pd.DataFrame:
    """A synthetic feature panel for one region, long enough for the arx model
    (ADR 0003) to fit: at least `MIN_FIT_ROWS` usable rows once the LAG+WINDOW
    warm-up is dropped. The numbers are not meant to satisfy the ADR 0003 equation,
    only to be smooth enough that a fit does not degenerate.
    """
    lead_in = arrears_model.LAG_MONTHS + arrears_model.WINDOW_MONTHS
    calendar = pd.date_range("2015-01-01", periods=n_months + lead_in + 1, freq="MS")
    rng = np.random.default_rng(seed)
    u = pd.Series(7.0 + np.cumsum(rng.normal(0, 0.1, len(calendar))), index=calendar)
    m = pd.Series(5.0 + np.cumsum(rng.normal(0, 0.05, len(calendar))), index=calendar)
    months = calendar[lead_in : lead_in + n_months]
    next_month = months + pd.DateOffset(months=1)
    rate_bp = 50.0 + np.cumsum(rng.normal(0, 0.3, n_months))
    return pd.DataFrame(
        {
            "month": months,
            "region": region,
            "arrears_rate_bp": rate_bp,
            "unemployment_rate": u.reindex(next_month).to_numpy(),
            "mortgage_rate_5y": m.reindex(next_month).to_numpy(),
            "arrears_through": months,
            "unemployment_through": next_month,
            "rate_through": next_month,
        }
    )


def _two_region_panel() -> pd.DataFrame:
    return pd.concat([_panel("CA", 0), _panel("ON", 1)], ignore_index=True)


# Building the forecast rows -----------------------------------------------------------


def test_build_forecast_rows_has_one_row_per_region_and_horizon() -> None:
    panel = _two_region_panel()
    origin = pd.Timestamp(panel["month"].max())
    rows = forecast.build_forecast_rows(panel, origin, "9.9.9", WRITTEN_AT, regions=REGIONS)

    keys = {(row["region"], row["horizon"]) for row in rows}
    assert keys == {(region, h) for region in REGIONS for h in forecast.HORIZONS}
    for row in rows:
        assert row["origin_month"] == f"{origin:%Y-%m}"
        assert row["model_version"] == "9.9.9"
        assert row["written_at"] == "2026-10-07T00:00:00+00:00"
        assert isinstance(row["forecast_bp"], float)
        assert not np.isnan(row["forecast_bp"])


def test_build_forecast_rows_skips_a_region_with_no_row_at_the_origin() -> None:
    short_region = _panel("BC", 2, n_months=5)  # stops long before the other two
    panel = pd.concat([_two_region_panel(), short_region], ignore_index=True)
    origin = pd.Timestamp(panel["month"].max())

    rows = forecast.build_forecast_rows(
        panel, origin, "9.9.9", WRITTEN_AT, regions=(*REGIONS, "BC")
    )
    assert "BC" not in {row["region"] for row in rows}


# Append-only: forecasts.csv ------------------------------------------------------------


def _patch_model(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]]) -> None:
    """Replace the model with canned rows, so these tests check the ledger's file
    contract (append-only, idempotent) and not the arx model itself."""
    monkeypatch.setattr(forecast, "build_forecast_rows", lambda *a, **k: rows)
    monkeypatch.setattr(backtest, "load_panel", lambda data_dir: pd.DataFrame())


def _write_arrears(data_dir: Path, month: str, region: str = "CA") -> None:
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"month": [month], "region": [region], "mortgages": [1000], "arrears": [5]}
    )
    frame.to_csv(processed / "arrears.csv", index=False)


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


def test_append_forecasts_writes_the_new_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_model(monkeypatch, [_row("2026-08", "2026-09", 1), _row("2026-08", "2026-11", 3)])
    _write_arrears(tmp_path, "2026-08-01")

    added = forecast.append_forecasts(tmp_path, tmp_path / "ledger")
    assert added == 2
    written = pd.read_csv(tmp_path / "ledger" / "forecasts.csv", dtype=str)
    assert len(written) == 2
    assert set(written["horizon"]) == {"1", "3"}


def test_append_forecasts_never_rewrites_an_existing_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_arrears(tmp_path, "2026-08-01")
    ledger_dir = tmp_path / "ledger"

    _patch_model(monkeypatch, [_row("2026-08", "2026-09", 1)])
    forecast.append_forecasts(tmp_path, ledger_dir)
    before = (ledger_dir / "forecasts.csv").read_text(encoding="utf-8")

    # Rerun for the same origin with a model that would now forecast something
    # different: the row already on disk must not change.
    changed_row = _row("2026-08", "2026-09", 1)
    changed_row["forecast_bp"] = 999.0
    _patch_model(monkeypatch, [changed_row])
    added = forecast.append_forecasts(tmp_path, ledger_dir)
    after = (ledger_dir / "forecasts.csv").read_text(encoding="utf-8")

    assert added == 0
    assert after == before


def test_append_forecasts_adds_a_new_origin_without_touching_the_old_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir = tmp_path / "ledger"
    _write_arrears(tmp_path, "2026-08-01")
    _patch_model(monkeypatch, [_row("2026-08", "2026-09", 1)])
    forecast.append_forecasts(tmp_path, ledger_dir)
    before = (ledger_dir / "forecasts.csv").read_text(encoding="utf-8")

    _write_arrears(tmp_path, "2026-09-01")
    _patch_model(monkeypatch, [_row("2026-09", "2026-10", 1)])
    added = forecast.append_forecasts(tmp_path, ledger_dir)
    after = (ledger_dir / "forecasts.csv").read_text(encoding="utf-8")

    assert added == 1
    assert after.startswith(before)  # the file only ever grows
    assert "2026-09" in after


# Grading: outcomes.csv -----------------------------------------------------------------


def _write_ledger(ledger_dir: Path, rows: list[dict[str, object]]) -> None:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=forecast.FORECASTS_COLUMNS).to_csv(
        ledger_dir / "forecasts.csv", index=False
    )


def _write_processed_arrears(data_dir: Path, rows: list[tuple[str, str, int, int]]) -> None:
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["month", "region", "mortgages", "arrears"]).to_csv(
        processed / "arrears.csv", index=False
    )


def test_grade_outcomes_grades_once_the_archive_file_exists(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ledger_dir = tmp_path / "ledger"
    _write_ledger(ledger_dir, [_row("2026-08", "2026-09", 1)])
    _write_processed_arrears(data_dir, [("2026-09-01", "CA", 1000, 7)])
    cba_dir = data_dir / "raw" / "cba"
    cba_dir.mkdir(parents=True)
    (cba_dir / "2026-09.xlsx").write_bytes(b"")

    now = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    added = forecast.grade_outcomes(data_dir, ledger_dir, now=now)
    assert added == 1
    outcomes = pd.read_csv(ledger_dir / "outcomes.csv")
    assert outcomes.loc[0, "actual_bp"] == pytest.approx(70.0)
    assert outcomes.loc[0, "cba_file"] == "data/raw/cba/2026-09.xlsx"


def test_grade_outcomes_leaves_a_target_ungraded_without_the_archive_file(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    ledger_dir = tmp_path / "ledger"
    _write_ledger(ledger_dir, [_row("2026-08", "2026-09", 1)])
    _write_processed_arrears(data_dir, [("2026-09-01", "CA", 1000, 7)])
    # No data/raw/cba/2026-09.xlsx: the CBA has not published that month yet.

    added = forecast.grade_outcomes(data_dir, ledger_dir)
    assert added == 0
    assert not (ledger_dir / "outcomes.csv").exists()


def test_grade_outcomes_never_regrades_a_target(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ledger_dir = tmp_path / "ledger"
    _write_ledger(ledger_dir, [_row("2026-08", "2026-09", 1)])
    _write_processed_arrears(data_dir, [("2026-09-01", "CA", 1000, 7)])
    cba_dir = data_dir / "raw" / "cba"
    cba_dir.mkdir(parents=True)
    (cba_dir / "2026-09.xlsx").write_bytes(b"")

    forecast.grade_outcomes(data_dir, ledger_dir)
    before = (ledger_dir / "outcomes.csv").read_text(encoding="utf-8")
    added = forecast.grade_outcomes(data_dir, ledger_dir)
    after = (ledger_dir / "outcomes.csv").read_text(encoding="utf-8")

    assert added == 0
    assert after == before
