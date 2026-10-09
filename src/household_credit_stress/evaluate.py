"""Evaluation for `make eval`. Writes `reports/backtest.csv` and `reports/metrics.json`.

Runs the backtest harness in `backtest.py` on the real processed data, under the
expanding-window design in `docs/eval_plan.md`. `metrics.json` holds the persistence
and AR(1) baselines, the ADR 0003 `arx` model scored against the better of the two
(docs/eval_plan.md, "What counts as beating the baseline"), and that model's fitted
slopes at the last origin, for each region (`coefficients_last_origin`).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import __version__, backtest, plots, run_log
from .metrics import Estimate

METRICS_FILE = "metrics.json"
BACKTEST_FILE = "backtest.csv"
FIGURE_NAME = "mae_arx_vs_baseline.png"
# The headline forecast horizon (BRIEF.md: "forecasts next month's arrears").
HEADLINE_HORIZON = 1


def run_evaluation(data_dir: Path = Path("data")) -> tuple[dict[str, Any], pd.DataFrame]:
    """Run the whole backtest. Returns the metrics dict and the backtest rows."""
    panel = backtest.load_panel(data_dir)
    last_month = pd.Timestamp(panel["month"].max())
    origins = pd.date_range(backtest.DEV_START, last_month, freq="MS")
    rows = backtest.run_backtest(panel, origins)
    metrics = backtest.summarize(rows)
    metrics["model"]["coefficients_last_origin"] = {
        "cutoff": f"{last_month:%Y-%m}",
        "by_region": backtest.coefficients_at_cutoff(panel, last_month),
    }
    return metrics, rows


def headline_gap_bp(metrics: dict[str, Any]) -> float | None:
    """The model-minus-best-baseline test MAE gap at `HEADLINE_HORIZON`, for the
    run log (docs/eval_plan.md, "Backtest design"). `None` if there was not yet
    enough test-period data to score the model at that horizon."""
    comparison = metrics["model"][f"h{HEADLINE_HORIZON}"]
    if comparison is None:
        return None
    gap = comparison["gap_bp"]["value"]
    return float(gap) if gap is not None else None


def _write_headline_chart(metrics: dict[str, Any], reports_dir: Path) -> None:
    """The one chart: arx against its best baseline, test MAE at `HEADLINE_HORIZON`."""
    comparison = metrics["model"][f"h{HEADLINE_HORIZON}"]
    if comparison is None:
        return  # not enough test-period data yet to score the model
    baseline_name = comparison["baseline"]
    per_horizon = metrics["baselines"]
    baseline_test = per_horizon[baseline_name][f"h{HEADLINE_HORIZON}"]["test"]
    model_test = per_horizon[backtest.MODEL_NAME][f"h{HEADLINE_HORIZON}"]["test"]
    rows = [
        (baseline_name, Estimate(**baseline_test["mae_bp"]), plots.MUTED),
        (backtest.MODEL_NAME, Estimate(**model_test["mae_bp"]), plots.SERIES_1),
    ]
    plots.plot_mae(rows, model_test["n_origins"], reports_dir / "figures" / FIGURE_NAME)


def write_reports(reports_dir: Path, data_dir: Path = Path("data")) -> dict[str, Any]:
    """Run the evaluation and write `backtest.csv`, `metrics.json` and the headline
    chart under `reports_dir`."""
    metrics, rows = run_evaluation(data_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(reports_dir / BACKTEST_FILE, index=False, date_format="%Y-%m-%d")
    # Always LF, so a run on Windows writes the same bytes as a run on Linux.
    text = json.dumps(metrics, indent=2) + "\n"
    (reports_dir / METRICS_FILE).write_text(text, encoding="utf-8", newline="\n")
    _write_headline_chart(metrics, reports_dir)
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    metrics = write_reports(args.reports_dir, args.data_dir)
    run_log.append_run(
        args.reports_dir,
        backtest.MODEL_NAME,
        __version__,
        run_log.current_git_hash(),
        headline_gap_bp(metrics),
    )
    print(f"Wrote {args.reports_dir / BACKTEST_FILE} and {args.reports_dir / METRICS_FILE}")
    for model in backtest.MODELS:
        for h in backtest.HORIZONS:
            test = metrics["baselines"][model][f"h{h}"]["test"]
            if test is not None:
                print(f"{model} h{h} test MAE: {test['mae_bp']['value']} bp")
    for h in backtest.HORIZONS:
        comparison = metrics["model"][f"h{h}"]
        if comparison is not None:
            print(f"arx h{h} vs {comparison['baseline']}: {comparison['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
