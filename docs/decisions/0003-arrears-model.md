# 0003: Forecast arrears with the AR(1) baseline plus two lagged drivers

Date: 2026-10-08. Status: accepted.

## Context

The [evaluation plan](../eval_plan.md) asks one question. Can a model that uses
mortgage rates, unemployment and past arrears forecast the arrears rate in each region
better than simple rules, one and three months after the latest CBA file (month L)?

Facts that shape the choice:

- The data rule in the plan lets a forecast at L use arrears through L, and
  unemployment and the posted 5-year mortgage rate through L+1. A model may not use
  the real future values of either input.
- The same model will later drive the scenario engine (task T08). There, a user sets
  future paths for unemployment and the mortgage rate. So the model must take those two
  inputs month by month, and it must behave in a sensible way when a user pushes them
  past anything seen in history.
- The data is small: one row per region and month since January 1995. It has breaks:
  the MB and SK reporting change in November 2006, changes in the CBA bank list, and
  the payment deferrals of 2020 and 2021.
- The AR(1) [baseline](../glossary.md#baseline) in the plan is already fitted by region on the monthly change in
  the rate, with no constant.
- Risk teams will ask what each part of the model does. A model they cannot read will
  not be trusted, even if it scores well.

This record fixes every setting before any model result exists. Nothing is tuned on the
development origins, so there is no hidden search over settings.

## Options

1. AR(1) baseline plus lagged driver terms, fitted by region (an ARX model). Small and
   easy to read. Any gain over the AR(1) baseline can only come from the two drivers.
   The same equation can run forward on a scenario path. Slopes for small regions will
   be noisy.
2. A separate regression for each horizon, from what is known at L straight to L+h.
   It needs no step-by-step run. But it gives two sets of slopes that can disagree, and
   it cannot turn a month-by-month scenario path into an arrears path.
3. One pooled model for all regions, with shared driver slopes. Slopes would be steadier.
   But regions differ in how arrears respond, such as AB and SK after the oil price
   fall. Kept as the next attempt if the per-region slopes prove unstable.
4. An error-correction model that ties the level of arrears to the level of
   unemployment. It needs a stable long-run link between the two levels. The bank list
   changes and the MB and SK break make that doubtful.
5. Gradient-boosted trees on many features. There are only a few hundred rows per
   region. Trees also predict a flat line outside the range they were trained on, which
   is wrong for a stress test. They are hard to explain to a risk team.
6. The payment shock at renewal: today's rate minus the rate five years ago. This is
   closer to how rate rises hurt borrowers. But the rate series starts in 1995, so the
   measure would start in 2000 and cut the early training data. Left for later.
7. Option 1 with the deferral months left out of the fit. This might help after 2020.
   But it changes two things at once, so a gain could not be credited to the drivers.

## Decision

Option 1. Each region gets its own fit of this equation, by least squares:

```text
d(t)   = y(t) - y(t-1)
x_u(t) = (u(t-2) - u(t-14)) / 12
x_m(t) = (m(t-2) - m(t-14)) / 12

d(t) = phi * d(t-1) + b_u * x_u(t) + b_m * x_m(t) + error
```

- `y` is the region's arrears rate in [basis points](../glossary.md#basis-point).
- `u` is the region's unemployment rate in percent, by the calendar month it describes.
  ATL uses the rate built from its four provinces, as the plan says.
- `m` is the national posted 5-year mortgage rate in percent, as a monthly mean.
- `x_u` and `x_m` are the average monthly change of each driver over twelve months,
  ending two months before the target month.
- There is no constant, as in the AR(1) baseline. With both
  slopes at zero, the model is the AR(1) baseline. This makes the comparison clean.

Fitting:

- At origin L the fit uses every month t up to L where all terms exist.
- For MB and SK the fit drops the rows whose `d(t)` or `d(t-1)` is the change into
  November 2006. This is the same level-shift rule the AR(1) baseline uses.
- A fit with too few rows raises an error rather than return weak slopes. The limit is
  `MIN_FIT_ROWS` in the code.
- The slopes have no sign limits.

Forecasting:

- The equation runs forward one month at a time from L, using its own forecast of `d`
  for later months. The rate at L+h is the rate at L plus the forecast changes.
- The driver terms for a target month t use the drivers up to month t-2. For L+3 that
  is L+1, the last month the data rule allows. So the model never needs to forecast
  unemployment or the mortgage rate. This is why the lag is two months: it is the
  shortest lag that keeps L+3 inside the rule.
- The lag also fits how arrears work. A loan counts as in arrears only after three
  months unpaid, so a job loss or a higher payment shows up months later.
- The twelve-month window smooths the month-to-month noise in the survey rates of small
  provinces. It keeps the fit to three numbers per region.
- The 80% [prediction interval](../glossary.md#prediction-interval) is built the same <!-- not-a-claim -->
  way as for the baselines: from the model's own past errors at the same horizon, using
  only errors known at L.
- The model is named `arx` in `reports/backtest.csv`.

## Consequences

- The model is a small step past the AR(1) baseline. If it does not beat that baseline,
  the drivers did not help at these horizons, and the README says so.
- The scenario engine can run the same equation on a user's paths. T05 reports the
  signs of `b_u` and `b_m` at the last origin for each region, because T08 needs them.
- The rate slope may come out negative. The Bank of Canada tends to raise rates when the
  economy is strong, so in history rate rises can come with falling arrears. T08 must
  check this before it lets the rate path drive arrears in a scenario.
- In 2020 unemployment jumped while arrears fell, because of payment deferrals. Training
  rows from that time will pull `b_u` down for later origins. The sub-period results in
  the plan will show this, and `docs/whats_weak.md` must list it.
- Slopes for MB, SK and ATL rest on noisier rates and will move more between origins.
- Any change to this model after its test result is seen is a new model version. It
  gets a new row in the test log and a note under "Changes to this plan".
