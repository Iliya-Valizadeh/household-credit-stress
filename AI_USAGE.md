DRAFT: Iliya to edit

# How the AI assistant was used

This page says which parts of the work were mine and which parts an AI coding assistant
wrote. The owner of the repo edits it and removes the draft line above.

## What I decided

I set the question in [docs/eval_plan.md](docs/eval_plan.md) before any model code
existed: can mortgage rates, unemployment and past arrears forecast the arrears rate by
region better than a simple rule, one and three months ahead. I fixed the data, the
target, the publication lags, the [baseline](docs/glossary.md#baseline) each model must
beat, the metric and the rule for a win, and the choice of model and the scenario
design in
[docs/decisions/](docs/decisions/), each written and committed before its result was
seen. I set the task queue the assistant worked from, and decided what each task would
cover.

## What I checked

I reviewed the pipeline and the quality gates after the core model and the live ledger
were built, before any scenario work started, and recorded a pre-registered verdict:
`arx` showed no clear difference from AR(1), and its per-region driver coefficients
were unstable enough that they should not drive scenarios as they stood. That review
set the direction for the scenario design that followed. I check that every number
quoted in this repo's docs has a row in [CLAIMS.md](CLAIMS.md) pointing at a committed,
runnable command, and that `make check-docs` and `make test` pass before anything is
merged.

## What the AI assistant wrote

The assistant wrote the source fetchers, the feature panel, the
[backtest](docs/glossary.md#backtest) harness, both
models, the live ledger code, the scenario engine, the static page, the tests and the
first drafts of every document in this repo, including this one, each against the
decisions above. [docs/whats_weak.md](docs/whats_weak.md) and the README's "What's
weak" section list what it found weak in its own work.
