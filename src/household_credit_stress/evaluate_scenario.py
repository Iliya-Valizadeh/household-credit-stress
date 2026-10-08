"""Runs the ADR 0004 scenario engine's conditional backtest (`scenario.py`) and the
presets it needs (`docs/decisions/0004-scenarios.md`, "Presets from history").

Writes `reports/scenario_backtest.csv` (the conditional backtest rows),
`reports/scenario_metrics.json` (the h=12/h=24 verdict, the label it decides, and the
80% bands by region and month ahead), and `reports/scenario_presets.json` (each
preset's monthly driver changes). The single-vintage caveat in `docs/eval_plan.md`
applies: this is a backtest on the latest published vintage of every input, not what
a user would have seen at the time.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import backtest, scenario

BACKTEST_FILE = "scenario_backtest.csv"
METRICS_FILE = "scenario_metrics.json"
PRESETS_FILE = "scenario_presets.json"


def run_scenario_evaluation(data_dir: Path = Path("data")) -> tuple[dict[str, Any], pd.DataFrame]:
    """Runs the conditional backtest and builds the verdict, label and bands."""
    panel = backtest.load_panel(data_dir)
    last_month = pd.Timestamp(panel["month"].max())
    origins = pd.date_range(backtest.DEV_START, last_month, freq="MS")
    rows = scenario.run_conditional_backtest(panel, origins)
    check = scenario.summarize_check(rows)
    bands = scenario.bands_by_region_and_horizon(rows)
    metrics = {
        "about": (
            "Conditional backtest of the ADR 0004 pooled_arx scenario model "
            "(docs/decisions/0004-scenarios.md) against the persistence and AR(1) "
            "baselines, at h=12 and h=24 months, as fixed in docs/eval_plan.md, "
            "'Changes to this plan' (2026-10-08). The model is given the true future "
            "unemployment and rate paths, which breaks the point-in-time rule on "
            "purpose: this is a backtest on the latest published vintage, not a "
            "point-in-time forecast, and these results are never forecasts or ledger "
            "entries."
        ),
        "generated_by": "python -m household_credit_stress.evaluate_scenario",
        "regions": list(scenario.REGIONS),
        "dev_period": {"start": f"{backtest.DEV_START:%Y-%m}", "end": f"{backtest.DEV_END:%Y-%m}"},
        "test_period": {
            "start": f"{backtest.TEST_START:%Y-%m}",
            "end": f"{rows['origin_month'].max():%Y-%m}" if not rows.empty else None,
        },
        **check,
        "bands_80_by_region": bands,
    }
    return metrics, rows


def _presets_payload(data_dir: Path) -> dict[str, Any]:
    processed = data_dir / "processed"
    unemployment = pd.read_csv(processed / "unemployment.csv", parse_dates=["month"])
    mortgage_rate = pd.read_csv(processed / "mortgage_rate_5y.csv", parse_dates=["month"])
    labour_force_path = processed / "labour_force.csv"
    labour_force = (
        pd.read_csv(labour_force_path, parse_dates=["month"])
        if labour_force_path.exists()
        else pd.DataFrame({"month": [], "region": [], "unemployed": [], "labour_force": []})
    )
    presets = scenario.build_presets(unemployment, mortgage_rate, labour_force)
    return {
        "about": (
            "Presets from history (docs/decisions/0004-scenarios.md, 'Presets from "
            "history'): each replays a past change in the drivers, not a past level. "
            "Values are the change from the driver's last known value, by month."
        ),
        "generated_by": "python -m household_credit_stress.evaluate_scenario",
        "horizon_months": scenario.PRESET_MONTHS,
        "presets": [scenario.preset_to_dict(p) for p in presets],
    }


def committed_backtest_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """The rows written to `reports/scenario_backtest.csv`: only the two horizons the
    verdict actually scores (h=12, h=24), not the full h=1..24 grid `run_scenario_evaluation`
    computes in memory to build the bands. That grid is ~12x bigger for no audit benefit
    (its per-horizon errors are already summarized in `bands_80_by_region`), so committing
    all of it would needlessly bloat the repo."""
    return rows.loc[rows["horizon"].isin(scenario.CHECK_HORIZONS)].reset_index(drop=True)


def write_reports(reports_dir: Path, data_dir: Path = Path("data")) -> dict[str, Any]:
    metrics, rows = run_scenario_evaluation(data_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    committed_backtest_rows(rows).to_csv(
        reports_dir / BACKTEST_FILE, index=False, date_format="%Y-%m-%d"
    )
    text = json.dumps(metrics, indent=2) + "\n"
    (reports_dir / METRICS_FILE).write_text(text, encoding="utf-8", newline="\n")

    presets = _presets_payload(data_dir)
    presets_text = json.dumps(presets, indent=2) + "\n"
    (reports_dir / PRESETS_FILE).write_text(presets_text, encoding="utf-8", newline="\n")
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    metrics = write_reports(args.reports_dir, args.data_dir)
    print(
        f"Wrote {args.reports_dir / BACKTEST_FILE}, {args.reports_dir / METRICS_FILE} "
        f"and {args.reports_dir / PRESETS_FILE}"
    )
    print(f"label: {metrics['label']}")
    for h in scenario.CHECK_HORIZONS:
        result = metrics["check"].get(f"h{h}")
        if result is not None:
            print(f"h{h}: passes={result['passes']} vs {result['best_baseline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
