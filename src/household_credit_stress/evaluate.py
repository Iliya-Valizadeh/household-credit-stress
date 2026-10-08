"""Evaluation for `make eval`. It writes reports/metrics.json and the headline chart.

The template ships a small worked example so every new repo runs end to end on day
one. It makes synthetic data, fits a mean baseline and a linear model, and reports
each one's mean absolute error with a 95% bootstrap interval. It also reports the gap
between them with a paired bootstrap interval.

Replace this with the evaluation in docs/eval_plan.md. Every number the docs quote
must come from the file this script writes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .data import make_dataset, train_test_split
from .metrics import Estimate, bootstrap_mae, bootstrap_mae_gap
from .models import LinearModel, MeanBaseline

SEED = 7
N_ROWS = 1000
TEST_FRACTION = 0.2
N_RESAMPLES = 2000
LEVEL = 0.95
DECIMALS = 4

METRICS_FILE = "metrics.json"
CHART_FILE = "figures/mae_by_model.png"


def _rounded(est: Estimate) -> dict[str, float]:
    return {
        "value": round(est.value, DECIMALS),
        "ci_low": round(est.ci_low, DECIMALS),
        "ci_high": round(est.ci_high, DECIMALS),
    }


def run_evaluation() -> tuple[dict[str, Any], dict[str, Estimate]]:
    """Run the whole evaluation. Returns the metrics dict and the raw estimates."""
    x, y = make_dataset(N_ROWS, seed=SEED)
    split = train_test_split(x, y, TEST_FRACTION, seed=SEED + 1)

    baseline = MeanBaseline().fit(split.x_train, split.y_train)
    model = LinearModel().fit(split.x_train, split.y_train)
    pred_base = baseline.predict(split.x_test)
    pred_model = model.predict(split.x_test)

    boot_seed = SEED + 2
    estimates = {
        "baseline": bootstrap_mae(split.y_test, pred_base, N_RESAMPLES, LEVEL, boot_seed),
        "model": bootstrap_mae(split.y_test, pred_model, N_RESAMPLES, LEVEL, boot_seed),
        "mae_gap": bootstrap_mae_gap(
            split.y_test, pred_base, pred_model, N_RESAMPLES, LEVEL, boot_seed
        ),
    }
    metrics: dict[str, Any] = {
        "about": "Template demo on synthetic data. Replace with your real evaluation.",
        "seed": SEED,
        "n_train": len(split.y_train),
        "n_test": len(split.y_test),
        "metric": "mean_absolute_error",
        "interval": {"method": "percentile_bootstrap", "resamples": N_RESAMPLES, "level": LEVEL},
        "baseline": {"name": MeanBaseline.name, **_rounded(estimates["baseline"])},
        "model": {"name": LinearModel.name, **_rounded(estimates["model"])},
        "mae_gap": _rounded(estimates["mae_gap"]),
    }
    return metrics, estimates


def write_reports(reports_dir: Path) -> dict[str, Any]:
    """Run the evaluation and write metrics.json and the chart under `reports_dir`."""
    from .plots import MUTED, SERIES_1, plot_mae

    metrics, est = run_evaluation()
    reports_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(metrics, indent=2) + "\n"
    # Always LF, so a run on Windows writes the same bytes as a run on Linux.
    (reports_dir / METRICS_FILE).write_text(text, encoding="utf-8", newline="\n")
    plot_mae(
        [
            ("Baseline: training mean", est["baseline"], MUTED),
            ("Linear model", est["model"], SERIES_1),
        ],
        n_test=metrics["n_test"],
        path=reports_dir / CHART_FILE,
    )
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = parser.parse_args(argv)
    metrics = write_reports(args.reports_dir)
    print(f"Wrote {args.reports_dir / METRICS_FILE} and {args.reports_dir / CHART_FILE}")
    print(f"Model MAE {metrics['model']['value']}, baseline MAE {metrics['baseline']['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
