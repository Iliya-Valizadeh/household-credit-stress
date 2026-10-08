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
| `reports/figures/mae_arx_vs_baseline.png` | The headline chart that `make eval` draws |

## Package

| Module | What it does |
|---|---|
| `sources/` | Fetches and parses each public source (`boc.py`, `statcan.py`, `cba.py`, `http.py`) |
| `refresh.py` | Pulls all sources and writes `data/processed/*.csv` and `data/status.json` |
| `features.py` | Builds the monthly feature panel, with point-in-time lags, used by the [backtest](glossary.md#backtest) |
| `arrears_model.py` | The ADR 0003 `arx` model: the AR(1) [baseline](glossary.md#baseline) plus two lagged drivers |
| `backtest.py` | The expanding-window backtest harness and the persistence and AR(1) baselines |
| `metrics.py` | [Mean absolute error](glossary.md#mean-absolute-error) with a [bootstrap](glossary.md#bootstrap) [confidence interval](glossary.md#confidence-interval) |
| `plots.py` | Draws the headline chart |
| `evaluate.py` | Runs the evaluation for `make eval` and writes the files above |
| `demo.py` | Runs the same evaluation for `make demo` and prints it, with no files written |
