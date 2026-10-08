# 0004: Scenarios run a pooled version of the ADR 0003 equation over two years

Date: 2026-10-08. Status: accepted.

## Context

The app lets a user set future paths for unemployment and the posted 5-year mortgage
rate, and shows how the arrears rate in each region responds. This record fixes how
those paths become arrears paths. It was written before any scenario code or result
existed.

Facts that shape the choice:

- The model in [ADR 0003](0003-arrears-model.md) (`arx`) did not beat the AR(1)
  [baseline](../glossary.md#baseline) one and three months ahead. The gap includes zero
  at both horizons, and the point estimate is worse. `CLAIMS.md` has the numbers.
- Its slopes are fitted region by region, and they are unstable. At the last origin the
  rate slope is negative for ATL and MB (`reports/metrics.json`,
  `model.coefficients_last_origin`). A user who raised the rate there would see
  arrears fall.
- Arrears count loans three or more months overdue. A job loss or a higher payment shows
  up months later and keeps building for a long time. A one or three month test is too
  short to show that effect. A stress test is about the next one to two years.
- The drivers are known only through month L+1, where L is the latest CBA month. A
  scenario supplies the months after that.
- The arrears data start in January 1995. Unemployment starts in 1976. The rate file
  starts in 1995 because the fetcher asks for nothing earlier.
- In 2020 and 2021 payment deferrals kept arrears down while unemployment jumped. That
  link between unemployment and arrears was broken by policy, not by borrowers.

## Options

1. Run the ADR 0003 per-region slopes on the user's paths. Simple, and the model is
   already tested. But the slopes are noisy and some have the wrong sign, so a scenario
   could show rate rises lowering arrears.
2. One pooled set of driver slopes for all seven regions, with each region keeping its
   own starting level and its own AR(1) term. The slopes rest on seven times the data,
   so they move less between origins. The cost: a rise of one point in unemployment
   adds the same basis points everywhere, though arrears in AB and SK sit higher than
   in ON.
3. Option 2 plus a constant for each region. The constant would carry the long fall in
   arrears since 1995 forward into every scenario. Over two years that drift would
   swamp the drivers. Rejected.
4. A separate direct regression for each month ahead, up to two years. It cannot turn a
   month-by-month path into a path of arrears without many sets of slopes that can
   disagree. Rejected for the same reason as in ADR 0003.
5. Slopes forced to the expected sign by a constrained fit. The forced value would sit
   at zero most of the time, and a reader could not tell a fitted effect from a forced
   one. Rejected in favour of the sign rule below, which is visible.

## Decision

Option 2, run over a horizon of twenty-four months, with a sign rule, a range check and
presets from history.

### The scenario model

Each region r keeps the ADR 0003 equation, with shared driver slopes:

```text
d_r(t) = phi_r * d_r(t-1) + b_u * x_u_r(t) + b_m * x_m(t) + error
```

- `d`, `x_u` and `x_m` are exactly as in ADR 0003: the monthly change in the arrears rate
  in basis points, and the average monthly change of each driver over twelve months,
  ending two months before month t.
- `phi_r` is fitted for each of the seven regions ATL, QC, ON, MB, SK, AB and BC. `b_u`
  and `b_m` are one pair for all seven. There is no constant.
- The fit is one least-squares problem on the stacked rows of the seven regions, each
  row weighted the same. It uses only rows up to the origin L.
- The fit drops the MB and SK rows next to the November 2006 break, as ADR 0003 does.
- The fit also drops every row whose `d(t)` or `d(t-1)` falls in March 2020 to December
  2021, the deferral months. Every scenario says it assumes no deferral program.
- CA is not fitted. Its path is the CBA's CA rate at L plus the average of the seven
  regions' changes, weighted by each region's mortgage count at L.
- The arrears path is floored at zero. A month at the floor is flagged.

The model is named `pooled_arx`. Code may reuse `arrears_model.run_forward`, which
already takes driver terms built from any path.

### The sign rule

The expected signs are `b_u > 0` and `b_m > 0`: more unemployment or a higher rate
should mean more arrears. At each origin:

- If a fitted slope has the wrong sign (zero counts as wrong), the model is refitted
  without that driver. Its slider then has no effect, and the page says plainly that the
  data did not show the expected effect, with the fitted value.
- If both slopes are wrong, no scenario is drawn. The page says why.
- The same rule runs at every origin of the [backtest](../glossary.md#backtest) below, so the check tests the full
  procedure the app uses, not a cleaner version of it.

Each slope gets a 95% <!-- not-a-claim -->
[confidence interval](../glossary.md#confidence-interval) from the moving-block
[bootstrap](../glossary.md#bootstrap) in the evaluation plan, resampling whole months
for all regions together. The slopes at every December origin are saved, so a chart can
show whether they are stable.

### How a path becomes arrears

- Horizon: arrears months `L+1` to `L+24`. Driver months up to L+1 are actual values. The
  user's path fills the months after L+1.
- A user sets, for each driver, the change from its last known value by twelve months
  later and by twenty-four months later. Straight lines join the points month by month.
  By default the national change applies to every region. The engine also accepts a
  full monthly path for each region.
- Because of the two-month lag, the last two months of a driver path never reach the
  arrears horizon. The page says so.
- The engine runs the equation forward one month at a time from the region's level and
  last change at L, as ADR 0003 does.
- The model is linear. So the engine also exports, for each region, the path with both
  drivers held at their last known values, and the response of each arrears month to a
  one-point change in each driver month. The web page adds these up and runs no model
  code of its own. A test checks that the sum matches `run_forward` on every preset.

### The honest range of inputs

The range is what the model saw when it was fitted.

- For each driver, the engine records the lowest and highest value of its term (`x_u` or
  `x_m`) in the rows of the fit, pooled over regions. It also records the lowest and
  highest level of each driver in the data: unemployment by region since 1976, the rate
  since the first month in the rate file.
- A scenario month inside both ranges gets no warning.
- A month outside either range is drawn dashed, with a "beyond history" warning. The
  warning says the model is extending straight lines past anything it has seen.
- The input range is widened by half its width on each side. Past that the engine
  refuses the path and the slider stops. This is the hard limit on extrapolation.

### Presets from history

Each preset replays a past change, not a past level. For a preset that starts in month S:

```text
driver(L+1+k) = driver(L+1) + [driver(S+k) - driver(S)],   k = 1 ... 23
```

Each region gets its own unemployment change. The rate change is national. The start
month follows a stated rule, so it was not picked to make the result look a certain way.

| Preset | Rule for the start month S | S | Source rows |
|---|---|---|---|
| Early 1990s recession | Last month at the lowest national unemployment rate in 1989 and 1990 | 1989-10 | `data/processed/unemployment.csv`, every region, 1989-10 to 1991-09; ATL from `data/processed/labour_force.csv`, same months; `data/processed/mortgage_rate_5y.csv`, same months |
| 2008-09 recession | Last month at the lowest national unemployment rate in 2007 and 2008 | 2007-10 | The same three files, 2007-10 to 2009-09 |
| Rate rises of 2022 and 2023 | Last month at the lowest posted 5-year rate in 2021 and 2022 | 2022-03 | The same three files, 2022-03 to 2024-02 |

- The start months above come from applying each rule to the data files committed on
  this branch by the first data pull (commit `6a2c65c`). T09 computes them again in code and fails if they
  differ.
- T09 writes each preset's monthly changes to a generated file. Any change quoted in
  prose goes through `CLAIMS.md`.
- The rate file starts in 1995, so the 1990s preset has no rate path yet. T09 moves the
  fetch start in `sources/boc.py` back to 1989 if the Bank of Canada series covers those
  months. If it does not, the 1990s preset holds the rate flat and says so.
- The early 1990s preset comes from a time before the arrears data start. Its
  unemployment rise may leave the range of the fit. The range check then warns.

### Bands and the label

- Each scenario path gets an 80% band. <!-- not-a-claim -->
  Its ends come from the 10th and 90th percentiles of the model's own errors in the <!-- not-a-claim -->
  conditional backtest below, by region and month ahead, using only errors whose target
  month is published. The band shows error when the paths are right. It leaves out the
  error of choosing the paths.
- Whether a scenario is called a conditional forecast or an illustration is decided by
  the check fixed in the [evaluation plan](../eval_plan.md#changes-to-this-plan) on
  2026-10-08, before any scenario result existed. If the model fails that check, every
  scenario is labelled "Illustrative: not a forecast", with one sentence saying why.

## Consequences

- The app can show a two-year response with slopes that rest on all seven regions. A
  region's response differs from the others only through its starting level and its
  AR(1) term, not through its own driver slopes.
- Shared slopes in basis points will understate the response where arrears sit high and
  overstate it where they sit low. `docs/whats_weak.md` must list this.
- Dropping the deferral months is a choice made before seeing results. It means the
  scenarios describe a downturn without a deferral program. A future downturn with one
  would look different.
- If the sign rule drops a driver, the README and the page say so. A model that only
  responds to one driver is still shown, but it is weaker evidence.
- The 1990s preset may need a change to the fetcher. That change stays inside
  `sources/`, so tests still never touch the network.
- The ADR 0003 `arx` model stays as the one and three month forecast in the ledger. The
  two models answer different questions and are named apart.
- Any change to `pooled_arx` after its check result is seen is a new version. It gets a
  new row in the test log and a note under "Changes to this plan".
