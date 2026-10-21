"""Exports the JSON files the static web page in `site/` reads (T10,
`_portfolio/hcs/TASKS.md`).

The page is plain HTML/CSS/JS with no framework and no model code of its own: it adds
up numbers this module already computed. Run after `refresh.py`, `evaluate_scenario.py`
and `forecast.py`, so the exported files reflect the latest pulled data, backtest and
ledger:

- `site/data/scenario.json`: for each region, the ADR 0004 linear decomposition
  (`scenario.region_sensitivities`) at the latest cutoff month, plus the honest range of
  each driver (`scenario.driver_ranges`) and the weights `scenario.run_ca` uses to build
  the CA path. The page reconstructs a region's arrears path as
  `baseline_path + sensitivity_unemployment @ (u_path - last_unemployment) +
  sensitivity_rate @ (m_path - last_rate)` (ADR 0004, "How a path becomes arrears") and
  never runs the model itself.
- `site/data/ledger.json`: every row of `ledger/forecasts.csv`, joined with
  `ledger/outcomes.csv` once a target month is graded.
- `site/data/scenario_metrics.json`, `site/data/scenario_presets.json`: copies of the
  same-named files `evaluate_scenario.py` writes to `reports/` (the conditional-backtest
  label and 80% bands, and the three presets from history).
- `site/data/status.json`: a copy of `data/status.json`, for the page's stale label.

docs/whats_weak.md records what the page's range check leaves out: it checks each
driver's honest LEVEL range (widened), not the x_u/x_m TERM range ADR 0004 also
defines, because the term depends on 12 months of history the page would otherwise
need to carry just for a warning message.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from household_credit_stress import backtest, scenario

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
LEDGER_DIR = Path("ledger")
SITE_DATA_DIR = Path("site/data")

REGION_NAMES: dict[str, str] = {
    "ATL": "Atlantic",
    "QC": "Quebec",
    "ON": "Ontario",
    "MB": "Manitoba",
    "SK": "Saskatchewan",
    "AB": "Alberta",
    "BC": "British Columbia",
}

SCENARIO_ABOUT = (
    "The ADR 0004 pooled_arx scenario model (docs/decisions/0004-scenarios.md), as a "
    "linear decomposition: for each region, the path with both drivers held flat at "
    "their last known value (baseline_path), and the response of each of the 24 "
    "arrears months to a one-point bump of each of the 24 future driver months "
    "(sensitivity_unemployment, sensitivity_rate). The web page adds these up and runs "
    "no model code of its own (ADR 0004, 'How a path becomes arrears'). See "
    "scenario_metrics.json for whether this model is labelled a conditional forecast "
    "or illustrative."
)

LEDGER_ABOUT = (
    "Every forecast this app has written to ledger/forecasts.csv for 1 and 3 months "
    "ahead (docs/eval_plan.md, 'Live forecast ledger'), joined with the actual arrears "
    "rate once the CBA publishes it (ledger/outcomes.csv). A forecast row is never "
    "edited after it is written; a target with no actual yet carries actual_bp: null."
)

_SENSITIVITY_DECIMALS = 4
_LEVEL_DECIMALS = 3
_WEIGHT_DECIMALS = 1


def _round_list(values: Any, decimals: int) -> list[float]:
    rounded: list[float] = np.round(np.asarray(values, dtype=float), decimals).tolist()
    return rounded


def _range_payload(honest_range: scenario.HonestRange) -> dict[str, float]:
    (_term_low, _term_high), (level_low, level_high) = honest_range.widened()
    return {
        "level_low": round(honest_range.level_low, _LEVEL_DECIMALS),
        "level_high": round(honest_range.level_high, _LEVEL_DECIMALS),
        "level_widened_low": round(level_low, _LEVEL_DECIMALS),
        "level_widened_high": round(level_high, _LEVEL_DECIMALS),
    }


def build_scenario_payload(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """The payload for `site/data/scenario.json`: the linear decomposition of
    `pooled_arx` at the latest cutoff month, for every region, plus the honest input
    ranges and the mortgage-count weights `scenario.run_ca` uses."""
    processed = data_dir / "processed"
    panel = backtest.load_panel(data_dir)
    cutoff = pd.Timestamp(panel["month"].max())
    fit = scenario.fit_pooled_arx(panel, cutoff)

    unemployment = pd.read_csv(processed / "unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(processed / "mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force_path = processed / "labour_force.csv"
    labour_force = (
        pd.read_csv(labour_force_path, parse_dates=["month"])
        if labour_force_path.exists()
        else pd.DataFrame({"month": [], "region": [], "unemployed": [], "labour_force": []})
    )
    ranges = scenario.driver_ranges(panel, unemployment, mortgage_rate, labour_force, cutoff)
    target_months = pd.date_range(
        cutoff + pd.DateOffset(months=1), periods=scenario.HORIZON_MONTHS, freq="MS"
    )

    def _level_at_cutoff(region: str) -> float:
        rows = panel.loc[(panel["region"] == region) & (panel["month"] == cutoff)]
        return float(rows["arrears_rate_bp"].iloc[0])

    by_region: dict[str, Any] = {}
    weights: dict[str, float] = {}
    for region in scenario.REGIONS:
        sens = scenario.region_sensitivities(panel, region, cutoff, fit)
        by_region[region] = {
            "level_at_cutoff": round(_level_at_cutoff(region), _LEVEL_DECIMALS),
            "last_unemployment": round(sens.last_unemployment, _LEVEL_DECIMALS),
            "last_rate": round(sens.last_rate, _LEVEL_DECIMALS),
            "baseline_path": _round_list(sens.baseline_path, _LEVEL_DECIMALS),
            "sensitivity_unemployment": [
                _round_list(row, _SENSITIVITY_DECIMALS) for row in sens.sensitivity_unemployment
            ],
            "sensitivity_rate": [
                _round_list(row, _SENSITIVITY_DECIMALS) for row in sens.sensitivity_rate
            ],
        }
        region_panel = panel.loc[panel["region"] == region].sort_values("month")
        known = region_panel.loc[region_panel["month"] <= cutoff]
        mortgages_at_cutoff = float(known.set_index("month")["mortgages"].loc[cutoff])
        weights[region] = round(mortgages_at_cutoff, _WEIGHT_DECIMALS)

    return {
        "about": SCENARIO_ABOUT,
        "generated_by": "python -m household_credit_stress.site_data",
        "model_name": scenario.MODEL_NAME,
        "cutoff": f"{cutoff:%Y-%m}",
        "horizon_months": scenario.HORIZON_MONTHS,
        "target_months": [f"{m:%Y-%m}" for m in target_months],
        "dropped_drivers": list(fit.dropped),
        "no_scenario": fit.no_scenario,
        "regions": list(scenario.REGIONS),
        "region_names": REGION_NAMES,
        "ranges": {
            "unemployment_rate": _range_payload(ranges["unemployment_rate"]),
            "mortgage_rate_5y": _range_payload(ranges["mortgage_rate_5y"]),
        },
        "by_region": by_region,
        "ca": {
            "level_at_cutoff": round(_level_at_cutoff("CA"), _LEVEL_DECIMALS),
            "mortgage_weights": weights,
        },
    }


def build_ledger_payload(ledger_dir: Path = LEDGER_DIR) -> dict[str, Any]:
    """The payload for `site/data/ledger.json`: `ledger/forecasts.csv` joined with
    `ledger/outcomes.csv` on (target_month, region). A target not yet graded carries
    `actual_bp: null`."""
    forecasts = pd.read_csv(
        ledger_dir / "forecasts.csv", dtype={"origin_month": str, "target_month": str}
    )
    outcomes_path = ledger_dir / "outcomes.csv"
    if outcomes_path.exists():
        outcomes = pd.read_csv(outcomes_path, dtype={"target_month": str})
    else:
        outcomes = pd.DataFrame(columns=["target_month", "region", "actual_bp"])

    merged = forecasts.merge(
        outcomes[["target_month", "region", "actual_bp"]],
        on=["target_month", "region"],
        how="left",
    )
    merged = merged.sort_values(["region", "horizon", "target_month"]).reset_index(drop=True)

    rows = []
    for _, row in merged.iterrows():
        actual = row["actual_bp"]
        rows.append(
            {
                "origin_month": row["origin_month"],
                "target_month": row["target_month"],
                "horizon": int(row["horizon"]),
                "region": row["region"],
                "forecast_bp": round(float(row["forecast_bp"]), _LEVEL_DECIMALS),
                "lo80_bp": round(float(row["lo80_bp"]), _LEVEL_DECIMALS),
                "hi80_bp": round(float(row["hi80_bp"]), _LEVEL_DECIMALS),
                "actual_bp": None if pd.isna(actual) else round(float(actual), _LEVEL_DECIMALS),
            }
        )

    return {
        "about": LEDGER_ABOUT,
        "generated_by": "python -m household_credit_stress.site_data",
        "regions": sorted(merged["region"].unique().tolist()),
        "rows": rows,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    text = json.dumps(payload, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def write_site_data(
    data_dir: Path = DATA_DIR,
    reports_dir: Path = REPORTS_DIR,
    ledger_dir: Path = LEDGER_DIR,
    site_data_dir: Path = SITE_DATA_DIR,
) -> list[Path]:
    """Writes every file under `site/data/` the page needs. Returns the paths written."""
    site_data_dir.mkdir(parents=True, exist_ok=True)
    written = [
        _write_json(site_data_dir / "scenario.json", build_scenario_payload(data_dir)),
        _write_json(site_data_dir / "ledger.json", build_ledger_payload(ledger_dir)),
    ]

    for name in ("scenario_metrics.json", "scenario_presets.json"):
        src = reports_dir / name
        if src.exists():
            dest = site_data_dir / name
            shutil.copyfile(src, dest)
            written.append(dest)

    status_src = data_dir / "status.json"
    if status_src.exists():
        status_dest = site_data_dir / "status.json"
        shutil.copyfile(status_src, status_dest)
        written.append(status_dest)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--ledger-dir", type=Path, default=LEDGER_DIR)
    parser.add_argument("--site-data-dir", type=Path, default=SITE_DATA_DIR)
    args = parser.parse_args(argv)
    written = write_site_data(args.data_dir, args.reports_dir, args.ledger_dir, args.site_data_dir)
    print("Wrote " + ", ".join(str(p) for p in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
