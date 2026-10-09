# Evaluation plan

This plan was written and committed before any model code existed and before any
forecast was scored. The README links to the commit that added it, so a reader can see
that the plan came first. If the plan changes later, add a dated note under "Changes to
this plan" and say why. Old results stay in the record.

The reasons for the target and horizons are in
[ADR 0002](decisions/0002-forecast-target.md).

## Question

Can a model that uses mortgage rates, unemployment and past arrears forecast the share
of mortgages in arrears in each Canadian region better than simple rules, one month and
three months ahead?

## Target

- The arrears rate: mortgages three or more months overdue divided by all mortgages,
  computed from the Canadian Bankers Association (CBA) counts. The CBA's own percentage
  column is not used.
- Unit: basis points (bp). One [basis point](glossary.md#basis-point) is one hundredth
  of a percentage point.
- Regions: the CBA regions ATL, QC, ON, MB, SK, AB and BC, plus CA for the whole
  country. TERR has no arrears figures and is left out.
- Origin: the latest month the CBA has published at the time of the forecast. Call it
  month L.
- Horizons: h = 1 (month L+1) and h = 3 (month L+3). Month L+1 is the next file the CBA
  will publish.
- A model may forecast the change from month L and add it back, but it is always scored
  on the level of the rate in basis points.

## Data known at each origin

A forecast may use only data that was published before the forecast was made. The
table gives, for an origin L, the last month of each source that the forecast may use.
The [backtest](glossary.md#backtest) applies the same rule at every past origin.

| Source | Last usable month | Why |
|---|---|---|
| CBA arrears and mortgages | L | L is the latest file by definition |
| Unemployment rate (Statistics Canada table `14-10-0287-01`) | L+1 | The Labour Force Survey for a month comes out early in the next month. The CBA file for L comes out about two months after L, so the survey for L+1 is already out |
| Posted 5-year mortgage rate (Bank of Canada, weekly) | L+1 | The monthly mean needs a complete month. L+1 is complete by the time the CBA file for L appears. L+2 may not be |

Rules that follow from the table:

- A month of the mortgage rate counts only when every week of it is in. A partial month,
  such as the current one, is never used.
- A forecast uses actual values only. It never uses the real future values of
  unemployment or the mortgage rate. A model that needs future inputs must forecast them
  itself, or forecast directly from what is known at L.
- In live use, the forecast waits until every input in the table is published. If the
  CBA publishes the target month first, that forecast is missed and is never filled in
  later.
- Scenario paths that a user sets in the app are separate from this plan. They are not
  forecasts and are never scored.

## Atlantic unemployment

The CBA reports one Atlantic region (ATL). Statistics Canada reports its four provinces
separately: Newfoundland and Labrador (NL), Prince Edward Island (PE), Nova Scotia (NS)
and New Brunswick (NB). The Atlantic rate is built as:

```text
ATL unemployment rate = 100 × (unemployed in NL + PE + NS + NB)
                            / (labour force in NL + PE + NS + NB)
```

- Both counts are seasonally adjusted and come from the same table and the same month.
- This equals the average of the four provincial rates weighted by each province's
  labour force in that month. Counts are used because the published rates are rounded
  to one decimal.
- The fetcher does not yet pull the counts. The task that builds the features adds them.
  If counts are ever missing for a month, that month's ATL rate is the labour-force
  weighted average of the rates, and the code logs it.
- QC, ON, MB, SK, AB and BC use their own provincial rate. CA uses the national rate.
  The mortgage rate is national and is the same for every region.

## Baselines

Each [baseline](glossary.md#baseline) is computed at every origin with the same data
rule as the model.

1. [Persistence](glossary.md#persistence-forecast): the rate in month L+h equals the
   rate in month L.
2. A simple time-series model per region: an AR(1) model on the monthly change in the
   rate, with no constant (ARIMA(1,1,0)). It is fit by least squares on all months up to
   L and run forward h steps.

Both baselines also give a [prediction interval](glossary.md#prediction-interval). It
comes from the spread of their own past errors at the same horizon, using only errors
that were known at L.

The "best baseline" for each horizon is the one with the lower error over the
development origins (see below). It is chosen once, before the test period is run.

## Backtest design

- Expanding window: at each origin L, every model and baseline is refit on data up to L,
  under the rule in "Data known at each origin". No future month is used for fitting,
  scaling, feature choice or picking settings.
- Training data starts in January 1995, the first month the CBA reports.
- Development origins: January 2007 to December 2016. Any model choice, feature choice
  or setting is made by looking at these origins only.
- Test origins: January 2017 to the last origin whose target month is published.
  The test period covers the pandemic and the rate rises from 2022 on.
- The first origin comes after the MB and SK reporting change in November 2006, so that
  break is never a target. Models that train across it must allow a level shift for MB
  and SK at that month. The AR(1) baseline drops that one monthly change when it fits.
- The test period is run once per model version. Each test run adds a row to an
  append-only log in `reports/`, so the number of attempts is visible. If a model is
  changed after its test result is seen, the old result stays in the log and the change
  is noted below.

### The single-vintage caveat

Every past number in the backtest is the latest published version
([vintage](glossary.md#vintage)), not the number people saw at the time.

- The CBA deletes its old files. Each file holds the full history, and our archive
  starts with the July 2026 file. Revisions before that, and changes in the list of
  reporting banks, are invisible.
- Statistics Canada revises the Labour Force Survey, including the seasonal adjustment
  each year and full rebases from time to time. The backtest uses today's revised values.

This most likely makes the backtest look better than live use would have been. Every
place that shows backtest numbers must say "backtest on the latest vintage". The live
ledger is the only fully point-in-time test.

## Metrics

Primary metric, for each horizon on the test origins:

- [Mean absolute error](glossary.md#mean-absolute-error) (MAE) in basis points, averaged
  with equal weight over the seven regions ATL, QC, ON, MB, SK, AB and BC.
- The same for each baseline, and the difference: model MAE minus best-baseline MAE.

Also reported, never used for the verdict:

- MAE for CA and for each region.
- The ratio of model MAE to persistence MAE, by region.
- Results for the development origins, labelled as such.
- Test results split into January 2017 to February 2020, March 2020 to December 2021
  (payment deferrals), and January 2022 on.

[Interval coverage](glossary.md#interval-coverage):

- Model and baselines each give an 80% central prediction interval. <!-- not-a-claim -->
  Its ends are the 10th and 90th percentiles of the forecast. <!-- not-a-claim -->
- Coverage is the share of actual values that fall inside the interval, pooled over the
  seven regions. The mean interval width in basis points is reported next to it.

### Intervals on the metrics

Each metric gets a 95% [confidence interval](glossary.md#confidence-interval) <!-- not-a-claim -->
from a moving-block [bootstrap](glossary.md#bootstrap) over origin months.

| Setting | Value |
|---|---|
| What is resampled | Whole origin months, all regions together, so that the link between regions is kept | <!-- not-a-claim -->
| Block length | 12 consecutive origins, because errors at nearby origins are related, and 3-month forecasts overlap | <!-- not-a-claim -->
| Resamples | 2,000, with a fixed seed of 0 | <!-- not-a-claim -->
| Interval | 2.5th to 97.5th percentile of the resampled values | <!-- not-a-claim -->
| Pairing | Model and baselines use the same resampled months, so the difference has its own interval |

## What counts as beating the baseline

These rules are fixed now. They apply to each horizon on its own.

The model beats the baseline at horizon h when both hold:

1. The 95% interval for (model MAE minus best-baseline MAE) lies wholly below zero. <!-- not-a-claim -->
2. The model MAE is at least 5% lower than the best-baseline MAE (point estimate). <!-- not-a-claim -->
   A smaller gain is too small to matter for a stress test.

The model's intervals pass when pooled test coverage of the 80% interval <!-- not-a-claim -->
is between 70% and 90% at that horizon. <!-- not-a-claim -->

Outcomes:

- Beats the baseline: both conditions hold. The README may say so for that horizon
  only, with the interval and the vintage caveat.
- No clear difference: the interval for the difference includes zero. This counts as a
  failure to beat the baseline.
- Worse: the interval lies wholly above zero. This is a failure.
- Intervals fail: coverage outside the band. This is reported as a failure of the
  intervals, even if the point forecasts beat the baseline.

On any failure, the README headline says so plainly. `docs/whats_weak.md` lists it. Any
region where the model's MAE is more than 10% above persistence <!-- not-a-claim -->
is listed there too, whatever the overall verdict.

## Live forecast ledger

The live forecasts are the real test, because they are made before the answer exists.

- File: `ledger/forecasts.csv`. It is append-only. Rows are never edited or deleted. A
  check fails if a new version of the file does not start with the old version.
- When a refresh finds a new CBA month L, the same run writes one row per region and
  horizon, then commits. The commit that adds a row is its timestamp.
- A row counts only if its commit is an ancestor of the commit that first adds the
  target month's CBA file to `data/raw/cba/`. Rows that fail this are shown as late,
  never scored.
- Git commit times come from the local clock. The commit order and, once the repo is on
  GitHub, the push history are the evidence. Commits are never backdated.
- The processed data files are committed in the same commit as the rows, so the inputs
  behind each forecast can be rebuilt.

Columns of `ledger/forecasts.csv`:

| Column | Meaning |
|---|---|
| `origin_month` | Month L, as YYYY-MM |
| `target_month` | Month L+h, as YYYY-MM |
| `horizon` | 1 or 3 |
| `region` | CA, ATL, QC, ON, MB, SK, AB or BC |
| `forecast_bp` | Model point forecast in basis points |
| `lo80_bp`, `hi80_bp` | Ends of the 80% prediction interval | <!-- not-a-claim -->
| `persistence_bp` | Persistence baseline for the same target |
| `ar1_bp` | AR(1) baseline for the same target |
| `arrears_through`, `unemployment_through`, `rate_through` | Last month of each input used |
| `model_version` | Package version that made the forecast |
| `written_at` | UTC time from the machine, for reading only. The commit is the proof |

Actual values go in a second append-only file, `ledger/outcomes.csv`, with the columns
`target_month`, `region`, `actual_bp`, `cba_file` and `first_seen_at`. Each target is
scored against the first CBA file that reports it, even if the CBA revises it later.
Scores are computed by a script from these two files. Nobody types a score by hand.

Reporting the live record:

- The live page shows every scored row, every late row and every missed slot.
- It shows model MAE against persistence and AR(1) MAE, by horizon.
- It makes no claim about the model beating a baseline until there are at least 12 <!-- not-a-claim -->
  scored origins at that horizon. Even then the interval will be wide, and the page says
  so.

## What would change the conclusion

- A result that holds in the test period as a whole but fails in one of the three
  sub-periods. The README must say which.
- A large gap between backtest and live errors. That would point to the vintage problem
  or to look-ahead in the backtest.
- One region driving the pooled result. The per-region table shows this.

## Changes to this plan

### 2026-10-08: the test-run log starts late

`reports/test_runs.csv` exists from this date on. `evaluate.py` and
`evaluate_scenario.py` each append one row per run: model, version, git hash, UTC time,
and that script's headline test MAE gap. Every run from here on is visible, including
one that changes nothing. Runs before this date are not in the log; the only record of
them is the git history of `reports/metrics.json` and `reports/scenario_metrics.json`,
which shows when each file last changed but not how many times a run was tried without
changing it.

### 2026-10-08: a scenario check at twelve and twenty-four months

Why: the one and three month test above cannot show how arrears respond to
unemployment, because that response builds over many months. The scenario engine in
[ADR 0004](decisions/0004-scenarios.md) works over two years. This section fixes a
check for that horizon. It was written and committed before any scenario code existed
and before any result for it was seen. Nothing above changes. The bullet "Scenario
paths that a user sets in the app are separate from this plan" still holds: user paths
are never scored. This check scores the engine, not a user's path.

What is tested:

- The model is `pooled_arx` from ADR 0004, with its sign rule, refitted at each origin
  on data up to L only.
- It is a conditional backtest. At each origin the model is given the actual
  unemployment and mortgage rate paths after L+1, as if a user had typed in the true
  path. This breaks the data rule in "Data known at each origin" on purpose, because a
  scenario is a forecast given a path. The results are never called forecasts, and they
  never feed the ledger or the one and three month verdict.
- The baselines are persistence and AR(1), run forward h months from L with no driver
  data, as defined in "Baselines".
- If the model cannot beat them even when it knows the true paths, the drivers add
  nothing a user can rely on at this horizon.

Settings:

| Setting | Value |
|---|---|
| Horizons scored | h = 12 and h = 24 | <!-- not-a-claim -->
| Origins | The same development and test periods as "Backtest design". The test origins run to the last origin whose target month L+h is published |
| Regions | The seven regions ATL, QC, ON, MB, SK, AB and BC, with equal weight. CA is reported, not used |
| Metric | MAE in basis points on the test origins, as in "Metrics" |
| Best baseline | The baseline with the lower development MAE at that horizon, chosen before the test origins are run |
| Interval on the gap | Moving-block bootstrap as in "Intervals on the metrics", but with blocks of 24 origins, because forecasts this long overlap for two years. 2,000 resamples, seed 0 | <!-- not-a-claim -->

Verdict, for each horizon:

1. The model passes at h when the 95% interval for (model MAE minus best-baseline MAE) <!-- not-a-claim -->
   lies wholly below zero, and the point estimate is at least 5% lower. <!-- not-a-claim -->
   These are the same rules as "What counts as beating the baseline".
2. The test uses every test origin. Origins whose target falls in the deferral months
   (March 2020 to December 2021) stay in. Results without them are also reported, but
   never used for the verdict.

What the app says:

- Scenarios are called conditional forecasts only if the model passes at both h = 12 <!-- not-a-claim -->
  and h = 24. <!-- not-a-claim -->
- In every other case, every scenario carries the label "Illustrative: not a forecast"
  and this sentence: "In a backtest on the latest vintage, this model did not forecast
  arrears better than a simple rule over one to two years, even when it was given the
  true unemployment and rate paths."
- If the sign rule drops a driver at the last origin, the page says so whatever the
  verdict.

Also reported, never used for the verdict:

- The development results, labelled as such.
- The same three sub-periods as in "Metrics", split by target month.
- MAE by region, and the ADR 0003 `arx` model run in the same conditional way.
- The pooled slopes and their intervals at each December origin, and which origins the
  sign rule dropped a driver at.

The test is run once per model version. Each run adds a row to the append-only test log
in `reports/`, as for the main test. The single-vintage caveat applies, so every place
that shows these numbers says "backtest on the latest vintage".
