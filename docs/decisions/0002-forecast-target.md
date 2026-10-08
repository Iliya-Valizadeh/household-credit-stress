# 0002: Forecast the arrears rate by CBA region, one and three months after the latest file

Date: 2026-10-08. Status: accepted.

## Context

The project forecasts mortgage arrears each month before the Canadian Bankers
Association (CBA) publishes them, and grades those forecasts in the open. The target has
to be fixed before any model exists, or the choice could drift toward whatever scores
well.

Facts that shape the choice:

- The CBA reports, for each region, the number of mortgages and the number three or
  more months overdue. It publishes about two months after the month it reports on.
- The regions are ATL, QC, ON, MB, SK, AB, BC, TERR and CA for the whole country. TERR
  has no arrears figures. ATL covers four provinces that Statistics Canada reports one
  by one.
- The number of mortgages grows over time, so arrears counts drift up even when stress
  does not.
- The CBA notes a reporting change for MB and SK in November 2006, and its list of
  banks changed over time.
- The users are risk teams at Canadian banks, who think in arrears rates and in basis
  points.

## Options

Target quantity:

1. Arrears count. Easy to read, but it mixes stress with growth in the number of
   mortgages.
2. Arrears rate (arrears divided by mortgages). Removes the growth. This is the number
   people quote.
3. Monthly change in the rate. Easier to model, but hard to read and easy to make look
   good.

Geography:

1. Canada only. One series, little to learn from.
2. CBA regions. Matches how the data is published and how regional shocks, such as the
   oil price fall in AB and SK, show up.

Horizon and timing:

1. Calendar months, such as "next month". The CBA lag means "next month" is not
   published for about three months, so the forecast mixes known and unknown months.
2. Months counted from the latest published CBA month (L). One month ahead is the next
   file the CBA will publish. Three months ahead is about a quarter of extra lead time.

## Decision

Forecast the arrears rate, computed from the counts and scored in basis points, for
each CBA region except TERR, plus CA. Horizons are L+1 and L+3, where L is the latest
CBA month published when the forecast is made. A model may predict the change from L,
but it is always scored on the level.

The rate is what users quote and it is not driven by loan growth. Counting from L makes
every forecast a true forecast of an unpublished number, and L+1 is graded within about
a month.

## Consequences

- Each origin gives one forecast per region and horizon. The live ledger and the
  [backtest](../glossary.md#backtest) use the same rows.
- Scoring in basis points keeps errors in the unit users read.
- Regions with few mortgages, such as MB and SK, give noisier rates. Results are shown
  by region so one region cannot hide in the average.
- The MB and SK reporting change is a level shift. It falls before the first backtest
  origin, and models must allow for it in training.
- ATL needs an Atlantic unemployment rate built from four provinces. The method is in
  [the evaluation plan](../eval_plan.md#atlantic-unemployment).
- L+2 is not forecast. Adding it later is a change to the plan and must be logged there.
