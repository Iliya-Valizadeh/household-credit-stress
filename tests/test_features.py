"""Tests for the feature panel: the point-in-time lag rules and the Atlantic
aggregation. No test touches the network; features.py never does either."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from household_credit_stress import features


def _rows(region: str, column: str, pairs: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": [pd.Timestamp(m) for m, _ in pairs],
            "region": region,
            column: [v for _, v in pairs],
        }
    )


EMPTY_LABOUR_FORCE = pd.DataFrame(
    {
        "month": pd.Series([], dtype="datetime64[ns]"),
        "region": pd.Series([], dtype=str),
        "unemployed": pd.Series([], dtype=float),
        "labour_force": pd.Series([], dtype=float),
    }
)


# Point-in-time lag rules -----------------------------------------------------------


def test_lead_shifts_the_month_back_by_the_lead() -> None:
    frame = pd.DataFrame(
        {"month": pd.to_datetime(["2020-01-01", "2020-02-01"]), "value": [1.0, 2.0]}
    )
    out = features._lead(frame, lead_months=1)
    assert list(out["month"]) == [pd.Timestamp("2019-12-01"), pd.Timestamp("2020-01-01")]
    assert list(out["value"]) == [1.0, 2.0]


def test_lead_of_zero_keeps_the_month() -> None:
    frame = pd.DataFrame({"month": pd.to_datetime(["2020-01-01"]), "value": [1.0]})
    out = features._lead(frame, lead_months=0)
    assert list(out["month"]) == [pd.Timestamp("2020-01-01")]


def test_build_feature_panel_uses_next_months_unemployment_and_rate() -> None:
    # Arrears is known for its own month L. Unemployment and the mortgage rate are
    # known one month ahead (L+1), per "Data known at each origin" in the eval plan.
    arrears = pd.DataFrame(
        {
            "month": pd.to_datetime(["2020-01-01", "2020-02-01"]),
            "region": "ON",
            "mortgages": [1000, 1000],
            "arrears": [5, 6],
        }
    )
    unemployment = _rows(
        "ON",
        "unemployment_rate",
        [("2020-01-01", 5.0), ("2020-02-01", 5.5), ("2020-03-01", 6.0)],
    )
    mortgage_rate = pd.DataFrame(
        {
            "month": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"]),
            "value": [3.0, 3.1, 3.2],
        }
    )

    panel = features.build_feature_panel(arrears, unemployment, mortgage_rate, EMPTY_LABOUR_FORCE)

    jan = panel[panel["month"] == pd.Timestamp("2020-01-01")].iloc[0]
    assert jan["arrears_rate_bp"] == pytest.approx(50.0)  # 5 / 1000 * 10,000
    assert jan["unemployment_rate"] == pytest.approx(5.5)  # February's value
    assert jan["mortgage_rate_5y"] == pytest.approx(3.1)  # February's value
    assert jan["unemployment_through"] == pd.Timestamp("2020-02-01")
    assert jan["rate_through"] == pd.Timestamp("2020-02-01")
    assert jan["arrears_through"] == pd.Timestamp("2020-01-01")

    feb = panel[panel["month"] == pd.Timestamp("2020-02-01")].iloc[0]
    assert feb["unemployment_rate"] == pytest.approx(6.0)  # March's value
    assert feb["mortgage_rate_5y"] == pytest.approx(3.2)  # March's value


def test_build_feature_panel_drops_regions_outside_the_cba_set() -> None:
    arrears = pd.DataFrame(
        {
            "month": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "region": ["ON", "TERR"],
            "mortgages": [1000, 10],
            "arrears": [5, 1],
        }
    )
    unemployment = _rows("ON", "unemployment_rate", [("2020-02-01", 5.5)])
    mortgage_rate = pd.DataFrame({"month": pd.to_datetime(["2020-02-01"]), "value": [3.1]})

    panel = features.build_feature_panel(arrears, unemployment, mortgage_rate, EMPTY_LABOUR_FORCE)

    assert set(panel["region"]) == {"ON"}


def test_build_feature_panel_includes_the_atlantic_row() -> None:
    arrears = pd.DataFrame(
        {
            "month": pd.to_datetime(["2020-01-01"]),
            "region": ["ATL"],
            "mortgages": [100],
            "arrears": [1],
        }
    )
    unemployment = pd.concat(
        [
            _rows("NL", "unemployment_rate", [("2020-02-01", 10.0)]),
            _rows("PE", "unemployment_rate", [("2020-02-01", 8.0)]),
            _rows("NS", "unemployment_rate", [("2020-02-01", 7.0)]),
            _rows("NB", "unemployment_rate", [("2020-02-01", 9.0)]),
        ],
        ignore_index=True,
    )
    labour_force = pd.concat(
        [
            _rows("NL", "unemployed", [("2020-02-01", 10.0)]).assign(labour_force=100.0),
            _rows("PE", "unemployed", [("2020-02-01", 4.0)]).assign(labour_force=50.0),
            _rows("NS", "unemployed", [("2020-02-01", 14.0)]).assign(labour_force=200.0),
            _rows("NB", "unemployed", [("2020-02-01", 9.0)]).assign(labour_force=100.0),
        ],
        ignore_index=True,
    )
    mortgage_rate = pd.DataFrame({"month": pd.to_datetime(["2020-02-01"]), "value": [3.1]})

    panel = features.build_feature_panel(arrears, unemployment, mortgage_rate, labour_force)

    atl = panel[panel["region"] == "ATL"].iloc[0]
    # 100 * (10 + 4 + 14 + 9) / (100 + 50 + 200 + 100) = 100 * 37 / 450
    assert atl["unemployment_rate"] == pytest.approx(100 * 37 / 450)


# Atlantic aggregation ----------------------------------------------------------------


def test_atlantic_rate_uses_counts_when_every_province_has_them() -> None:
    unemployment = pd.concat(
        [
            _rows("NL", "unemployment_rate", [("2020-01-01", 99.0)]),  # ignored: counts win
            _rows("PE", "unemployment_rate", [("2020-01-01", 99.0)]),
            _rows("NS", "unemployment_rate", [("2020-01-01", 99.0)]),
            _rows("NB", "unemployment_rate", [("2020-01-01", 99.0)]),
        ],
        ignore_index=True,
    )
    labour_force = pd.concat(
        [
            _rows("NL", "unemployed", [("2020-01-01", 10.0)]).assign(labour_force=100.0),
            _rows("PE", "unemployed", [("2020-01-01", 4.0)]).assign(labour_force=50.0),
            _rows("NS", "unemployed", [("2020-01-01", 14.0)]).assign(labour_force=200.0),
            _rows("NB", "unemployed", [("2020-01-01", 9.0)]).assign(labour_force=100.0),
        ],
        ignore_index=True,
    )

    out = features.atlantic_unemployment_rate(unemployment, labour_force)

    assert len(out) == 1
    assert out.iloc[0]["region"] == "ATL"
    assert out.iloc[0]["unemployment_rate"] == pytest.approx(100 * 37 / 450)


def test_atlantic_rate_falls_back_to_weighted_average_when_a_count_is_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unemployment = pd.concat(
        [
            _rows("NL", "unemployment_rate", [("2020-01-01", 10.0)]),
            _rows("PE", "unemployment_rate", [("2020-01-01", 8.0)]),
            _rows("NS", "unemployment_rate", [("2020-01-01", 7.0)]),
            _rows("NB", "unemployment_rate", [("2020-01-01", 9.0)]),
        ],
        ignore_index=True,
    )
    # NB's unemployed count is missing for the month; only the labour-force weight
    # (the denominator) is present for every province.
    labour_force = pd.concat(
        [
            _rows("NL", "unemployed", [("2020-01-01", 10.0)]).assign(labour_force=100.0),
            _rows("PE", "unemployed", [("2020-01-01", 4.0)]).assign(labour_force=50.0),
            _rows("NS", "unemployed", [("2020-01-01", 14.0)]).assign(labour_force=200.0),
            pd.DataFrame(
                {
                    "month": [pd.Timestamp("2020-01-01")],
                    "region": ["NB"],
                    "unemployed": [float("nan")],
                    "labour_force": [100.0],
                }
            ),
        ],
        ignore_index=True,
    )

    with caplog.at_level(logging.INFO, logger=features.logger.name):
        out = features.atlantic_unemployment_rate(unemployment, labour_force)

    weighted = (10.0 * 100 + 8.0 * 50 + 7.0 * 200 + 9.0 * 100) / 450
    assert out.iloc[0]["unemployment_rate"] == pytest.approx(weighted)
    assert "weighted" in caplog.text


def test_atlantic_rate_skips_a_month_with_no_usable_data(caplog: pytest.LogCaptureFixture) -> None:
    # Only two of four provinces report anything for the month: no counts and no
    # complete set of rates, so the month cannot be built at all.
    unemployment = _rows("NL", "unemployment_rate", [("2020-01-01", 10.0)])
    labour_force = _rows("NL", "unemployed", [("2020-01-01", 10.0)]).assign(labour_force=100.0)

    with caplog.at_level(logging.WARNING, logger=features.logger.name):
        out = features.atlantic_unemployment_rate(unemployment, labour_force)

    assert out.empty
    assert list(out.columns) == ["month", "region", "unemployment_rate"]
    assert "skipped" in caplog.text
