# ML Test Score self-assessment

This page scores this repo against the ML Test Score, a checklist from
[Breck et al. (Google, 2017)][breck]. The scores below describe the worked example
that came with the template. When you replace the example, score your own system
again, and never give a point that the code does not earn.

## In plain words

Google wrote a list of 28 tests for a machine learning system. <!-- not-a-claim -->
A system should pass them before people rely on it.
This page checks this repo against that list. The worked example scores zero, the
lowest level. Its model is a toy, and nothing runs as a live service.

## How the scoring works

The paper gives each test a score:

- none: the test is not done
- half a point: the test is done by hand, and the result is written down
- one point: the test is automated and runs again on every change

A section's score is the sum of its seven tests. The overall score is the lowest of
the four section scores, so one weak section pulls the whole system down. The paper
reads an overall score of zero as closer to a research project than a production
system.

## What is scored

The worked example makes synthetic data and fits a [baseline](glossary.md#baseline)
that always predicts the training mean. It also fits a linear model. It reports the
[mean absolute error](glossary.md#mean-absolute-error) of each, with a
[bootstrap](glossary.md#bootstrap) [confidence interval](glossary.md#confidence-interval).
The code is in `src/` and the tests are in `tests/test_pipeline.py`.

The tests below count as done by hand until CI (continuous integration, the checks
GitHub runs on every push) has run them. TODO: once CI passes on GitHub, move the
tests that CI runs from half a point to one point.

## Summary

| Section | Score out of 7 |
|---|---|
| Features and data | half a point |
| Model development | half a point |
| Infrastructure | one and a half points |
| Monitoring | none |
| Overall (the lowest section) | 0 |

In total, five tests earn half a point each. The other tests earn nothing.

## Tests for features and data

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Feature expectations are captured in a schema | none | Tests check the number of rows and columns only. No schema lists types or allowed ranges |
| 2 | All features are beneficial | none | Feature 2 has no effect on the target on purpose (`TRUE_COEFFICIENTS` in `data.py`). Nothing detects this |
| 3 | No feature's cost is too much | none | Not measured |
| 4 | Features adhere to meta-level requirements | none | The data is synthetic, so no outside rules apply yet. Nothing records or checks this |
| 5 | The data pipeline has appropriate privacy controls | none | There is no personal data and no privacy control. Real data needs one |
| 6 | New features can be added quickly | none | Not measured |
| 7 | All input feature code is tested | half | Tests cover `make_dataset` and `train_test_split`: fixed seeds, shapes and bad inputs |

## Tests for model development

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Model specs (the code that defines a model) are reviewed and checked in | none | The model code is in git, but no second person has reviewed it |
| 2 | Offline and online metrics correlate | none | There is no online use |
| 3 | All hyperparameters have been tuned | none | The linear model has no hyperparameters, and there is no tuning code for models that do |
| 4 | The impact of model staleness is known | none | The synthetic data does not change over time, so this was not studied |
| 5 | A simpler model is not better | half | `evaluate.py` fits the baseline next to the model and reports the gap in mean absolute error with a paired bootstrap interval. A test checks that the model beats the baseline |
| 6 | Model quality is sufficient on important data slices | none | No slices are defined or reported |
| 7 | The model is tested for considerations of inclusion | none | The synthetic data describes no people, and nothing checks this |

## Tests for infrastructure

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Training is reproducible | half | Every random step uses a fixed seed. A test reruns the evaluation and compares it with the committed `reports/metrics.json`. The CI workflow installs packages from the lockfile |
| 2 | Model specs are unit tested | half | Tests check that the linear model recovers a known rule from data with no noise, that the baseline predicts the training mean, and that predicting before fitting fails |
| 3 | The ML pipeline is integration tested | half | One test runs the whole evaluation, from data to `metrics.json` and the chart |
| 4 | Model quality is validated before serving | none | There is no serving step |
| 5 | The model is debuggable | none | There is no tool to follow one example through the model step by step |
| 6 | Models are canaried before serving | none | There is no serving step |
| 7 | Serving models can be rolled back | none | There is no serving step |

## Monitoring tests

| # | Test | Score | Evidence or gap |
|---|---|---|---|
| 1 | Dependency changes result in notification | none | Versions are pinned, but nothing reports new releases |
| 2 | Data invariants hold for inputs | none | `train_test_split` rejects inputs of different lengths, but no schema check runs on the data |
| 3 | Training and serving are not skewed | none | There is no serving step |
| 4 | Models are not too stale | none | There is no serving step |
| 5 | Models are numerically stable | none | Nothing checks for missing or infinite values in predictions |
| 6 | Computing performance has not regressed | none | Speed and memory use are not measured |
| 7 | Prediction quality has not regressed | none | There is no served data. The test that compares a fresh run with `reports/metrics.json` catches offline changes only |

[breck]: https://research.google/pubs/the-ml-test-score-a-rubric-for-ml-production-readiness-and-technical-debt-reduction/
