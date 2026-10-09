# ML Test Score self-assessment

This page scores this repo against the ML Test Score, a checklist from
[Breck et al. (Google, 2017)][breck]. It scores the real system: the data refresh, the
`arx` ledger model ([ADR 0003](decisions/0003-arrears-model.md)) and the `pooled_arx`
scenario engine ([ADR 0004](decisions/0004-scenarios.md)). No point is given that the
code does not earn.

## In plain words

Google wrote a list of 28 tests for a machine learning system. <!-- not-a-claim -->
A system should pass them before people rely on it.
This page checks this repo against that list. The repo scores zero, the lowest level.
Many of the tests are done and written down, but nothing runs as a live service yet:
the weekly data refresh has never run on GitHub, and no live forecast has been graded.

## How the scoring works

The paper gives each test a score:

- none: the test is not done
- half a point: the test is done by hand, and the result is written down
- one point: the test is automated and runs again on every change

A section's score is the sum of its seven tests. The overall score is the lowest of
the four section scores, so one weak section pulls the whole system down. The paper
reads an overall score of zero as closer to a research project than a production
system.

The repo has no GitHub remote yet, so CI (continuous integration, the checks GitHub
runs on every push) has never run. Every test below that `pytest` covers therefore
counts as done by hand. Once CI passes on GitHub, the tests that CI runs can move from
half a point to one point.

## Summary

| Section | Score out of 7 |
|---|---|
| Features and data | one point |
| Model development | one point |
| Infrastructure | two points |
| Monitoring | none |
| Overall (the lowest section) | 0 |

In total, eight tests earn half a point each. The other tests earn nothing.

## Tests for features and data

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Feature expectations are captured in a schema | none | The parsers in `sources/` reject an empty or failed reply, but no schema lists types or allowed ranges for the processed CSV files |
| 2 | All features are beneficial | none | The two drivers are only tested together, as `arx` against AR(1). That test finds no clear gain at one and three months (`reports/metrics.json`), and no test drops one driver at a time |
| 3 | No feature's cost is too much | none | Not measured |
| 4 | Features adhere to meta-level requirements | half | The point-in-time rule in [the evaluation plan](eval_plan.md) is tested: a feature from after the cutoff raises (`tests/test_backtest.py`). The three data sources' terms of use are now recorded in the README's [Data notes](../README.md#data-notes): the Bank of Canada and Statistics Canada licences allow redistribution with attribution, but the CBA's terms do not say whether archiving its spreadsheet counts as permitted copying, which is open under "Needs Iliya" |
| 5 | The data pipeline has appropriate privacy controls | none | The data are public regional totals with no personal data, and there is no privacy control |
| 6 | New features can be added quickly | none | Not measured |
| 7 | All input feature code is tested | half | `tests/test_features.py` covers the lag rules and the Atlantic aggregation, and `tests/test_sources.py` covers each parser on saved replies |

## Tests for model development

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Model specs (the code that defines a model) are reviewed and checked in | none | Each model has an ADR committed before its code, and an AI review session checked them. No second person has reviewed them |
| 2 | Offline and online metrics correlate | none | The live ledger holds one set of forecasts and none is graded yet, so there is nothing to compare with the [backtest](glossary.md#backtest) |
| 3 | All hyperparameters have been tuned | none | Nothing is tuned, on purpose (ADR 0003). There is no tuning code |
| 4 | The impact of model staleness is known | none | Both models are refit at every origin, and the effect of using an older fit was not studied |
| 5 | A simpler model is not better | half | `evaluate.py` and `evaluate_scenario.py` compare each model with persistence and AR(1), with a paired [bootstrap](glossary.md#bootstrap) interval. The check runs and finds that the simpler AR(1) is not beaten, and the docs say so |
| 6 | Model quality is sufficient on important data slices | half | `reports/metrics.json` reports test MAE by region, and `docs/whats_weak.md` lists the regions the evaluation plan's rule flags |
| 7 | The model is tested for considerations of inclusion | none | The models describe regions, not people, and nothing checks this |

## Tests for infrastructure

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Training is reproducible | half | The bootstrap uses a fixed seed and packages come from the lockfile. Two tests rerun the backtest and the scenario check and compare them with the committed reports (`tests/test_backtest.py`, `tests/test_scenario.py`) |
| 2 | Model specs are unit tested | half | `tests/test_arrears_model.py` and `tests/test_scenario.py` check that each fit recovers known slopes from exact data, a forward run worked out by hand, the sign rule and the deferral-month drop |
| 3 | The ML pipeline is integration tested | half | The same two reproduction tests run the whole evaluation from `data/processed/` to the reports. The fetch step is tested only with saved replies |
| 4 | Model quality is validated before serving | half | The scenario label on the page comes from the pre-registered check in `reports/scenario_metrics.json`, so a failed check shows "Illustrative: not a forecast". The ledger forecasts are written with no quality gate |
| 5 | The model is debuggable | none | There is no tool to follow one forecast through the model step by step |
| 6 | Models are canaried before serving | none | There is no staged release |
| 7 | Serving models can be rolled back | none | Each ledger row records `model_version`, but there is no rollback step |

## Monitoring tests

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Dependency changes result in notification | none | Versions are pinned in `uv.lock`, but nothing reports new releases |
| 2 | Data invariants hold for inputs | none | A failed fetch marks its source stale in `data/status.json` (tested in `tests/test_refresh.py`), but no check runs on the values themselves |
| 3 | Training and serving are not skewed | none | `forecast.py` builds its inputs with the same `features.py` code as the backtest, but no test compares the two |
| 4 | Models are not too stale | none | `data/status.json` flags old data, and the weekly workflow now reruns `site_data.py` so the page's copy stays current and commits on an ok/stale flip (`.github/workflows/refresh.yml`, `tests/test_refresh_commit.py`), but the refresh has never run on a schedule, since the repo has no GitHub remote yet |
| 5 | Models are numerically stable | none | Nothing checks for missing or infinite values in predictions |
| 6 | Computing performance has not regressed | none | Speed and memory use are not measured |
| 7 | Prediction quality has not regressed | none | `forecast.py` grades ledger rows once the CBA publishes them, but none is graded yet and nothing raises an alert |

## What would raise the score

- Push the repo and let CI pass, which moves most half points to one point.
- Let the weekly refresh run, so the ledger grades forecasts and the monitoring tests
  have something to watch.

[breck]: https://research.google/pubs/the-ml-test-score-a-rubric-for-ml-production-readiness-and-technical-debt-reduction/
