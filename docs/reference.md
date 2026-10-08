# Reference

Facts to look up: commands, files and settings.

## Make targets

| Target | What it does |
|---|---|
| `make setup` | Installs the pinned packages with `uv` |
| `make lint` | Runs ruff and mypy |
| `make test` | Runs pytest with a coverage report for `src/` |
| `make eval` | Runs the evaluation and writes `reports/metrics.json` |
| `make demo` | Runs a short demo that needs no downloads or keys |
| `make check-docs` | Runs the claims, readability, AI-writing signs, link and README checks |
| `make all` | Runs every step above in order |

## Output files

| File | What it holds |
|---|---|
| `reports/metrics.json` | The headline numbers, read by `CLAIMS.md` and the portfolio site |
| `reports/figures/mae_by_model.png` | The headline chart that `make eval` draws |

## Package

The template ships a small worked example. Replace these modules with your own and
update this table.

| Module | What it does |
|---|---|
| `data.py` | Makes a seeded synthetic dataset and splits it into train and test rows |
| `models.py` | A [baseline](glossary.md#baseline) that predicts the training mean, and a linear model |
| `metrics.py` | [Mean absolute error](glossary.md#mean-absolute-error) with a [bootstrap](glossary.md#bootstrap) [confidence interval](glossary.md#confidence-interval) |
| `plots.py` | Draws the headline chart |
| `evaluate.py` | Runs the evaluation for `make eval` and writes the files above |
| `demo.py` | Runs the same evaluation for `make demo` and prints it, with no files written |
