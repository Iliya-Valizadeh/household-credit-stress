# Claims

Every number in this repo's Markdown files has a row here. Each row says where the
number comes from and which command makes that file. `make check-docs` fails if a
number in the docs has no row, or if a row does not match its source.

Every row below is a [backtest](docs/glossary.md#backtest) on the latest [vintage](docs/glossary.md#vintage) of the
data, not the numbers a forecaster saw at the time (docs/eval_plan.md, "The
single-vintage caveat").

Small whole numbers (0 to 10), years, dates and version numbers are skipped. To skip
one line by hand, add the comment `<!-- not-a-claim -->` to it.

| Claim | Value | Source | Command |
|---|---|---|---|
| arx model (ADR 0003) test MAE, 1 month ahead | 0.73 bp | `reports/metrics.json#baselines.arx.h1.test.mae_bp.value` | `make eval` |
| arx model (ADR 0003) test MAE, 3 months ahead | 1.66 bp | `reports/metrics.json#baselines.arx.h3.test.mae_bp.value` | `make eval` |
| Best [baseline](docs/glossary.md#baseline) (AR(1)) test MAE, 1 month ahead | 0.70 bp | `reports/metrics.json#baselines.ar1.h1.test.mae_bp.value` | `make eval` |
| Best baseline (AR(1)) test MAE, 3 months ahead | 1.49 bp | `reports/metrics.json#baselines.ar1.h3.test.mae_bp.value` | `make eval` |
| arx minus AR(1) test MAE gap, 1 month ahead (95% interval) | 0.03 bp (-0.01 to 0.12 bp) | `reports/metrics.json#model.h1.gap_bp` | `make eval` |
| arx minus AR(1) test MAE gap, 3 months ahead (95% interval) | 0.17 bp (-0.03 to 0.54 bp) | `reports/metrics.json#model.h3.gap_bp` | `make eval` |
| pooled_arx scenario model (ADR 0004) conditional-backtest MAE gap vs. its best baseline, AR(1), 12 months ahead (95% interval) | 1.25 bp (-0.08 to 3.79 bp) | `reports/scenario_metrics.json#check.h12.gap_bp` | `uv run python -m household_credit_stress.evaluate_scenario` |
| pooled_arx scenario model conditional-backtest MAE gap vs. AR(1), 24 months ahead (95% interval) | 1.64 bp (-0.17 to 5.67 bp) | `reports/scenario_metrics.json#check.h24.gap_bp` | `uv run python -m household_credit_stress.evaluate_scenario` |
| arx test MAE in QC, 3 months ahead | 1.37 bp | `reports/metrics.json#baselines.arx.h3.by_region_test_mae_bp.QC` | `make eval` |
| Persistence test MAE in QC, 3 months ahead | 1.22 bp | `reports/metrics.json#baselines.persistence.h3.by_region_test_mae_bp.QC` | `make eval` |
| arx test MAE in AB, 3 months ahead | 1.95 bp | `reports/metrics.json#baselines.arx.h3.by_region_test_mae_bp.AB` | `make eval` |
| Persistence test MAE in AB, 3 months ahead | 1.62 bp | `reports/metrics.json#baselines.persistence.h3.by_region_test_mae_bp.AB` | `make eval` |
| arx test MAE in the payment-deferral period (March 2020-December 2021), 1 month ahead | 1.18 bp | `reports/metrics.json#test_subperiods.2020-03_2021-12.arx.h1.mae_bp.value` | `make eval` |
| AR(1) test MAE in the payment-deferral period, 1 month ahead | 1.00 bp | `reports/metrics.json#test_subperiods.2020-03_2021-12.ar1.h1.mae_bp.value` | `make eval` |
| arx test MAE in the payment-deferral period, 3 months ahead | 3.21 bp | `reports/metrics.json#test_subperiods.2020-03_2021-12.arx.h3.mae_bp.value` | `make eval` |
| AR(1) test MAE in the payment-deferral period, 3 months ahead | 2.38 bp | `reports/metrics.json#test_subperiods.2020-03_2021-12.ar1.h3.mae_bp.value` | `make eval` |

Example row, for the format only:
`| Test AUC | 0.58 (0.55 to 0.61) | reports/metrics.json#auc | make eval |`
