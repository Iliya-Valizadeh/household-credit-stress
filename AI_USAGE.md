DRAFT: Iliya to edit

# How the AI assistant was used

This page says which parts of the work were mine and which parts an AI coding assistant
did. The owner of the repo edits it and removes the draft line above.

The assistant drafted this page from the repo's own record: the commit history, the
`Co-Authored-By` lines on each commit, and the task notes. It does not claim any
decision for me that the record does not show. Iliya: add your own part below, in your
own words, and delete this paragraph.

## What I decided

Iliya to write: what you chose yourself, for example the project idea and the audience,
and any choice you changed after reading a draft.

## What the AI assistant did

Claude Code, an AI coding assistant, did almost all of the work, in separate sessions:

- Design sessions wrote the evaluation plan
  ([docs/eval_plan.md](docs/eval_plan.md)) and the decision records in
  [docs/decisions/](docs/decisions/). The plan and ADRs 0002 to 0004 were each
  committed before the result they govern.
- Build sessions wrote the source fetchers, the feature panel, the
  [backtest](docs/glossary.md#backtest) harness, both models, the live ledger, the
  scenario engine, the static page, the tests and the first draft of every document.
- A review session checked the work after the live ledger and before the scenario
  design. It recorded that `arx` showed no clear difference from AR(1) and that its
  per-region slopes were too unstable to drive scenarios. That review set the direction
  for ADR 0004.
- A final review session traced each number to `CLAIMS.md`, ranked the weaknesses and
  scored [docs/ml_test_score.md](docs/ml_test_score.md).

## What was checked, and how

Scripts, not people, check most of the work. Every number in the docs must have a row
in [CLAIMS.md](CLAIMS.md) that matches a committed report, and two tests rerun the
backtest and the scenario check and compare them with the committed reports. No second
person has reviewed the code. Iliya to write: what you read or checked yourself.
