"""Short demo for `make demo`. It must run with no downloads and no keys.

It runs the same evaluation as `make eval` on the built-in synthetic data and prints
the result. It writes no files. Replace it with a demo of your real pipeline.
"""

from __future__ import annotations

from .evaluate import run_evaluation


def _line(label: str, est: dict[str, float]) -> str:
    interval = f"(95% interval {est['ci_low']:.3f} to {est['ci_high']:.3f})"
    return f"{label:<28}{est['value']:.3f}  {interval}"


def main() -> int:
    metrics, _ = run_evaluation()
    print(f"Synthetic data: {metrics['n_train']} training rows, {metrics['n_test']} test rows.")
    print("Mean absolute error on the test rows (lower is better):")
    print(_line("  Baseline (training mean)", metrics["baseline"]))
    print(_line("  Linear model", metrics["model"]))
    print(_line("  Gap (baseline - model)", metrics["mae_gap"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
