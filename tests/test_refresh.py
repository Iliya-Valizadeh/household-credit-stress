"""Tests for the refresh step: what gets written, and how failures are recorded."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from household_credit_stress import refresh
from household_credit_stress.sources import boc, cba, statcan

TODAY = dt.date(2026, 10, 7)


def rates(_: Path) -> pd.DataFrame:
    return pd.DataFrame(
        {"month": pd.to_datetime(["2026-09-01", "2026-10-01"]), "value": [6.1, 6.2]}
    )


def arrears(_: Path) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": pd.to_datetime(["2026-06-01", "2026-07-01", "2026-08-01"]),
            "region": ["CA"] * 3,
            "mortgages": [10, 10, 10],
            "arrears": pd.array([1, 2, None], dtype="Int64"),
        }
    )


def old_unemployment(_: Path) -> pd.DataFrame:
    return pd.DataFrame(
        {"month": pd.to_datetime(["2025-01-01"]), "region": ["ON"], "unemployment_rate": [6.0]}
    )


def broken(_: Path) -> pd.DataFrame:
    raise ConnectionError("site down")


def run(tmp_path: Path, pullers: dict[str, Callable[[Path], pd.DataFrame]]) -> dict[str, Any]:
    refresh.refresh(tmp_path, pullers=pullers, today=TODAY)
    loaded: dict[str, Any] = json.loads((tmp_path / "status.json").read_text())
    return loaded


def test_fresh_sources_are_written_and_marked_ok(tmp_path: Path) -> None:
    status = run(tmp_path, {"mortgage_rate_5y": rates, "arrears": arrears})
    assert status["mortgage_rate_5y"]["ok"] and not status["mortgage_rate_5y"]["stale"]
    assert status["mortgage_rate_5y"]["latest_month"] == "2026-10"
    # The blank August row does not count as data.
    assert status["arrears"]["latest_month"] == "2026-07"
    assert not status["arrears"]["stale"]
    assert (tmp_path / "processed" / "arrears.csv").exists()


def test_old_data_is_marked_stale(tmp_path: Path) -> None:
    status = run(tmp_path, {"unemployment": old_unemployment})
    assert status["unemployment"]["ok"] and status["unemployment"]["stale"]


def test_failed_source_keeps_old_file_and_last_month(tmp_path: Path) -> None:
    run(tmp_path, {"mortgage_rate_5y": rates})
    before = (tmp_path / "processed" / "mortgage_rate_5y.csv").read_text()
    status = run(tmp_path, {"mortgage_rate_5y": broken})
    entry = status["mortgage_rate_5y"]
    assert not entry["ok"] and entry["stale"]
    assert entry["latest_month"] == "2026-10"
    assert "site down" in entry["error"]
    assert (tmp_path / "processed" / "mortgage_rate_5y.csv").read_text() == before


def test_main_exits_zero_unless_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(refresh, "PULLERS", {"mortgage_rate_5y": broken})
    assert refresh.main(["--data-dir", str(tmp_path)]) == 0
    assert "::warning" in capsys.readouterr().out
    assert refresh.main(["--data-dir", str(tmp_path), "--strict"]) == 1


def test_unexpected_crash_is_a_warning_unless_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "status.json").write_text("{not json")  # refresh() cannot read this
    assert refresh.main(["--data-dir", str(tmp_path)]) == 0
    assert "::warning title=Refresh crashed" in capsys.readouterr().out
    with pytest.raises(json.JSONDecodeError):
        refresh.main(["--data-dir", str(tmp_path), "--strict"])


def test_months_between() -> None:
    assert refresh.months_between(pd.Timestamp("2025-11-01"), pd.Timestamp("2026-02-01")) == 3


def test_default_pullers_call_the_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    weekly = pd.DataFrame({"date": pd.to_datetime(["2026-10-07"]), "value": [6.19]})
    monkeypatch.setattr(boc, "fetch_series", lambda series: weekly)
    monkeypatch.setattr(statcan, "fetch_unemployment", lambda: old_unemployment(tmp_path))
    monkeypatch.setattr(
        cba,
        "download_latest",
        lambda d: (arrears(d), pd.Timestamp("2026-07-01"), d / "2026-07.csv"),
    )
    monkeypatch.setattr(
        statcan,
        "fetch_labour_force",
        lambda: pd.DataFrame(
            {
                "month": pd.to_datetime(["2026-09-01"]),
                "region": ["NL"],
                "unemployed": [10.0],
                "labour_force": [100.0],
            }
        ),
    )
    status = run(tmp_path, refresh.PULLERS)
    assert all(entry["ok"] for entry in status.values())
