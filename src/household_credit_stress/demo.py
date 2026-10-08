"""Short demo for `make demo`. It must run with no downloads and no keys.

It runs the real backtest (`backtest.py`, via `evaluate.run_evaluation`) on the
committed processed data under `data/processed/` and prints the ADR 0003 `arx`
model's test-period result against its baseline, for horizons 1 and 3 months. It
reads only files already in the repo and writes none; `make eval` is what writes
`reports/backtest.csv` and `reports/metrics.json`.
"""

from __future__ import annotations

from pathlib import Path

from . import evaluate

DATA_DIR = Path("data")
HORIZONS = (1, 3)


def main() -> int:
    metrics, _ = evaluate.run_evaluation(DATA_DIR)
    print("ADR 0003 arx model vs. its baseline, test period (docs/eval_plan.md):")
    for h in HORIZONS:
        comparison = metrics["model"][f"h{h}"]
        if comparison is None:
            print(f"  h{h}: not enough test-period data yet")
            continue
        gap = comparison["gap_bp"]
        print(
            f"  h{h} vs {comparison['baseline']}: gap {gap['value']} bp "
            f"(95% interval {gap['ci_low']} to {gap['ci_high']}), "
            f"verdict: {comparison['verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
