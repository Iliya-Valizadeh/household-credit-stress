"""Short demo for `make demo`. It must run with no downloads and no keys.

It fits the template's worked example (a linear model against a training-mean
baseline) on built-in synthetic data and prints the result. It writes no files.
`evaluate.py` now runs the real backtest in `backtest.py`, which needs the processed
data files, so this demo no longer goes through it. Replace this with a demo of your
real pipeline.
"""

from __future__ import annotations

from .data import make_dataset, train_test_split
from .metrics import Estimate, bootstrap_mae, bootstrap_mae_gap
from .models import LinearModel, MeanBaseline

SEED = 7
N_ROWS = 1000
TEST_FRACTION = 0.2
N_RESAMPLES = 2000
LEVEL = 0.95


def _line(label: str, est: Estimate) -> str:
    interval = f"(95% interval {est.ci_low:.3f} to {est.ci_high:.3f})"
    return f"{label:<28}{est.value:.3f}  {interval}"


def main() -> int:
    x, y = make_dataset(N_ROWS, seed=SEED)
    split = train_test_split(x, y, TEST_FRACTION, seed=SEED + 1)

    baseline = MeanBaseline().fit(split.x_train, split.y_train)
    model = LinearModel().fit(split.x_train, split.y_train)
    pred_base = baseline.predict(split.x_test)
    pred_model = model.predict(split.x_test)

    boot_seed = SEED + 2
    est_base = bootstrap_mae(split.y_test, pred_base, N_RESAMPLES, LEVEL, boot_seed)
    est_model = bootstrap_mae(split.y_test, pred_model, N_RESAMPLES, LEVEL, boot_seed)
    est_gap = bootstrap_mae_gap(split.y_test, pred_base, pred_model, N_RESAMPLES, LEVEL, boot_seed)

    print(f"Synthetic data: {len(split.y_train)} training rows, {len(split.y_test)} test rows.")
    print("Mean absolute error on the test rows (lower is better):")
    print(_line("  Baseline (training mean)", est_base))
    print(_line("  Linear model", est_model))
    print(_line("  Gap (baseline - model)", est_gap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
