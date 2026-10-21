# Explanation

Background and reasons. This page says why the project works the way it does. The
tutorial and how-to guides say what to type.

## Why this approach

The question in [the evaluation plan](eval_plan.md) is whether the mortgage rate,
unemployment and past arrears can forecast the regional arrears rate better than a
simple rule. A small linear model answers that question in a way a reader can check.
Each slope has a meaning, and the model has nothing to tune. So a win or a loss
against the [baseline](glossary.md#baseline) says something about the drivers, not
about settings picked after the fact.

The test that matters is the live ledger. A [backtest](glossary.md#backtest) can only
use today's revised data, while a ledger row is written before the CBA publishes the
month it forecasts. So the repo makes its forecasts in public and grades them later.

## Choices and their costs

- Stale, not failed ([ADR 0001](decisions/0001-refresh-and-stale-data.md)). A source
  that cannot be fetched keeps its old data and is marked stale. The cost: the page can
  show old numbers, with a label, instead of stopping.
- The forecast target ([ADR 0002](decisions/0002-forecast-target.md)). The model
  forecasts the arrears rate by CBA region, one and three months after the latest
  published month. The cost: arrears react to unemployment over many months, so a test
  this short can miss the effect.
- The `arx` model ([ADR 0003](decisions/0003-arrears-model.md)). It is the AR(1)
  baseline plus two lagged drivers, fitted per region. The cost: its slopes are
  unstable from region to region, and it does not beat AR(1).
- The scenario engine ([ADR 0004](decisions/0004-scenarios.md)). It shares one pair of
  driver slopes across regions and runs two years ahead. The cost: it failed its own
  check, so every scenario is shown as an illustration, not a forecast.
- Numbers only from the CBA ([ADR 0006](decisions/0006-cba-numbers-only.md)). The
  repo keeps the counts from each CBA file, with a credit to the CBA, and not the
  spreadsheet, because the CBA's terms do not say whether the file may be shared.
  The cost: the CBA's own layout and notes are not kept.
