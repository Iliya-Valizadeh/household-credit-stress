# 0007: Freeze the backtest window at August 2026

Date: 2026-11-16. Status: accepted.

## Context

`evaluate.py` and `evaluate_scenario.py` ran the [backtest](../glossary.md#backtest) to the newest month in the
data. The weekly refresh adds a month about every four weeks, so each `make eval` would
add a test origin and move the committed numbers. The numbers in the README would then
change without a decision from me. The plan says the test period is run once per model
version (`docs/eval_plan.md`, "Backtest design").

## Decision

- `backtest.BACKTEST_LAST_MONTH` is 2026-08-01, the last month in the committed reports.
  Both evaluation entry points cut the panel there with `backtest.freeze_panel`.
- The weekly refresh still adds data and live forecasts. Only the live ledger uses the
  new months.
- Moving the window is a new model version. It needs a new ADR, a new test-run row and
  a re-check of every CLAIMS row that cites a backtest number.

## Consequences

The reported test MAE no longer improves or worsens by itself as months arrive. The
backtest ends at August 2026 while the live record keeps going, which is the intended
split between the two. A reader who wants a longer backtest has to wait for a deliberate
version change.
