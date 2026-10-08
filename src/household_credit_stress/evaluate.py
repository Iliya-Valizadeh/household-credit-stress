"""Evaluation for `make eval`. Writes `reports/backtest.csv` and `reports/metrics.json`.

Runs the backtest harness in `backtest.py` on the real processed data, under the
expanding-window design in `docs/eval_plan.md`. As of this task, `metrics.json` holds
only the two baselines (persistence and AR(1)); T05 adds the model's own rows once
there is a model to score, and its one chart.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import backtest

METRICS_FILE = "metrics.json"
BACKTEST_FILE = "backtest.csv"


def run_evaluation(data_dir: Path = Path("data")) -> tuple[dict[str, Any], pd.DataFrame]:
    """Run the whole backtest. Returns the metrics dict and the backtest rows."""
    panel = backtest.load_panel(data_dir)
    last_month = pd.Timestamp(panel["month"].max())
    origins = pd.date_range(backtest.DEV_START, last_month, freq="MS")
    rows = backtest.run_backtest(panel, origins)
    metrics = backtest.summarize(rows)
    return metrics, rows


def write_reports(reports_dir: Path, data_dir: Path = Path("data")) -> dict[str, Any]:
    """Run the evaluation and write `backtest.csv` and `metrics.json` under `reports_dir`."""
    metrics, rows = run_evaluation(data_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(reports_dir / BACKTEST_FILE, index=False, date_format="%Y-%m-%d")
    # Always LF, so a run on Windows writes the same bytes as a run on Linux.
    text = json.dumps(metrics, indent=2) + "\n"
    (reports_dir / METRICS_FILE).write_text(text, encoding="utf-8", newline="\n")
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    metrics = write_reports(args.reports_dir, args.data_dir)
    print(f"Wrote {args.reports_dir / BACKTEST_FILE} and {args.reports_dir / METRICS_FILE}")
    for model in backtest.MODELS:
        for h in backtest.HORIZONS:
            test = metrics["baselines"][model][f"h{h}"]["test"]
            if test is not None:
                print(f"{model} h{h} test MAE: {test['mae_bp']['value']} bp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
