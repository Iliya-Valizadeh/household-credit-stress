# Model card: household-credit-stress

Short form of the model card from Mitchell et al., "Model Cards for Model Reporting"
(https://arxiv.org/abs/1810.03993). Every number here needs a row in
[CLAIMS.md](CLAIMS.md).

## Model details

Two linear models, both fitted by ordinary least squares, built by Iliya Valizadeh.

- `arx` ([ADR 0003](docs/decisions/0003-arrears-model.md)): an AR(1) term on the
  monthly change in the arrears rate, plus two lagged driver terms, fitted by region.
  It makes the one- and three-month ledger forecasts.
- `pooled_arx` ([ADR 0004](docs/decisions/0004-scenarios.md)): the same equation, with
  one shared pair of driver slopes for all seven regions and a region-specific AR(1)
  term. It drives the scenario engine over a twenty-four-month horizon.

Version: the equations as implemented on branch `hcs-v1`. License: MIT
([LICENSE](LICENSE)).

## Intended use

`arx`'s one- and three-month forecasts are meant to be graded in the open against the
Canadian Bankers Association's own published numbers, for a reader who wants to see
whether a small, readable model beats a simple rule. `pooled_arx` is meant to show how
a user-drawn path for the mortgage rate and unemployment could move arrears over the
next two years, as an illustration of mechanism, not a number to plan around.

Neither model is meant for setting capital, pricing or lending decisions at a bank. The
"Results" section below is why: neither beats its [baseline](docs/glossary.md#baseline)
on its own pre-registered check.

## Factors

- Region: ATL, QC, ON, MB, SK, AB, BC, and CA for the whole country. TERR has no
  arrears figures.
- Time: a November 2006 reporting change for MB and SK, and payment deferral months
  from March 2020 to December 2021 that `pooled_arx` drops from its fit.
- Horizon: `arx` is scored one and three months ahead; `pooled_arx` is checked twelve
  and twenty-four months ahead, since arrears respond to unemployment over many months,
  not one to three.

## Metrics

[Mean absolute error](docs/glossary.md#mean-absolute-error) in basis points, with a
[confidence interval](docs/glossary.md#confidence-interval)
from a moving-block [bootstrap](docs/glossary.md#bootstrap) over origin months, at the
95% level set out in [the evaluation plan](docs/eval_plan.md) ("Metrics", "Intervals on <!-- not-a-claim -->
the metrics") and its 2026-10-08 addendum for the twelve- and twenty-four-month check.

## Evaluation data

`arx`: development origins January 2007 to December 2016 (used only to pick the best
baseline), test origins 2017-01 to 2026-06, on the processed series under
`data/processed/`.
`pooled_arx`'s check uses the same development and test periods, run forward to
twelve and twenty-four months, so its test origins stop at the last one whose target
month is published.

## Training data

Both models are refit at every [backtest](docs/glossary.md#backtest) origin on rows up
to that origin only, following the point-in-time rule in the evaluation plan. Rows next
to the MB/SK reporting break are dropped from the fit, as are the deferral-month rows
for `pooled_arx`. Data before this repo's own `data/raw/cba/` archive started exists
only as the latest published [vintage](docs/glossary.md#vintage); see
`docs/whats_weak.md`.

## Results

Every result in this section is a backtest on the latest vintage of the data, not on the numbers a
forecaster saw at the time. The live ledger, which avoids this, has no graded rows yet.

`arx` against AR(1), the better baseline at both horizons: the test MAE gap is 0.03 bp
one month ahead (interval -0.01 to 0.12 bp) and 0.17 bp three months ahead (interval
-0.03 to 0.54 bp), both at the 95% level. Both intervals include zero, so there is no <!-- not-a-claim -->
clear difference from AR(1) (`CLAIMS.md`).

`pooled_arx` against AR(1), given the true future rate and unemployment path (a
conditional backtest, not a point-in-time forecast): the test MAE gap is 1.25 bp at
twelve months (interval -0.08 to 3.79 bp) and 1.64 bp at twenty-four months (interval
-0.17 to 5.67 bp), both at the 95% level. Both intervals include zero, so `pooled_arx` <!-- not-a-claim -->
fails its own pre-registered check and every scenario is labelled "Illustrative: not a
forecast" (`CLAIMS.md`, `reports/scenario_metrics.json`).

Fitted by region, `arx`'s own driver slopes are unstable: at the last fitted origin the
mortgage rate slope is negative for ATL and MB, the opposite of the expected sign
(`reports/metrics.json#model.coefficients_last_origin`). This is why `pooled_arx`
shares one pair of slopes across all seven regions instead of fitting one set per
region. Three months ahead, `arx` also does more than a tenth worse than persistence in
QC and AB (`docs/whats_weak.md`, row 6).

## Ethical considerations

A reader could mistake either model's output for real evidence of mortgage stress in a
region it does not support. Both results above show a model that failed to beat a
simple rule, so a forecast or scenario shown without that context could understate the
real uncertainty in household credit risk, in either direction. Neither model should
be read as advice for an individual borrower; it reports a regional rate, not a
household's own risk.

## Caveats and recommendations

Read every forecast and scenario next to the result above: neither model has shown it
beats a simple rule. The full ranked list of weaknesses, including the single-vintage
caveat and the scenario engine's dropped deferral months, is in
[docs/whats_weak.md](docs/whats_weak.md).
