# Reference

Facts to look up: commands, files and settings.

## Make targets

| Target | What it does |
|---|---|
| `make setup` | Installs the pinned packages with `uv` |
| `make lint` | Runs ruff and mypy |
| `make test` | Runs pytest with a coverage report for `src/` |
| `make eval` | Runs the evaluation and writes `reports/metrics.json` |
| `make demo` | Reruns the [backtest](glossary.md#backtest) on the committed data and prints the headline result, with no downloads or keys |
| `make check-docs` | Runs the claims, readability, AI-writing signs, link and README checks |
| `make all` | Runs every step above in order |

## Output files

| File | What it holds |
|---|---|
| `reports/metrics.json` | The headline numbers, read by `CLAIMS.md` and the portfolio site |
| `reports/figures/mae_arx_vs_baseline.png` | The headline chart that `make eval` draws |
| `reports/scenario_metrics.json` | The pooled_arx scenario check at `h=12`/`h=24`, its label, and the 80% bands by region <!-- not-a-claim --> |
| `reports/scenario_backtest.csv` | One row per origin, region and horizon of the pooled_arx conditional [backtest](glossary.md#backtest) |
| `reports/scenario_presets.json` | Each history preset's monthly driver changes (ADR 0004) |
| `ledger/forecasts.csv` | The append-only live forecast rows, one per region and horizon |
| `ledger/outcomes.csv` | The actual rate for a forecast's target month, once the CBA archive publishes it |
| `site/data/*.json` | What `site_data.py` exports for the static page: scenario sensitivities, the ledger joined with outcomes, and `data/status.json` |

## Package

| Module | What it does |
|---|---|
| `sources/` | Fetches and parses each public source (`boc.py`, `statcan.py`, `cba.py`, `http.py`) |
| `refresh.py` | Pulls all sources and writes `data/processed/*.csv` and `data/status.json` |
| `features.py` | Builds the monthly feature panel, with point-in-time lags, used by the [backtest](glossary.md#backtest) |
| `arrears_model.py` | The ADR 0003 `arx` model: the AR(1) [baseline](glossary.md#baseline) plus two lagged drivers, reused by `scenario.py`'s forward run |
| `backtest.py` | The expanding-window backtest harness and the persistence and AR(1) baselines |
| `metrics.py` | [Mean absolute error](glossary.md#mean-absolute-error) with a [bootstrap](glossary.md#bootstrap) [confidence interval](glossary.md#confidence-interval) |
| `plots.py` | Draws the headline chart |
| `evaluate.py` | Runs the evaluation for `make eval` and writes the files above |
| `demo.py` | Runs the same evaluation for `make demo` and prints it, with no files written |
| `forecast.py` | Writes and grades the live ledger rows under `ledger/` |
| `scenario.py` | The ADR 0004 `pooled_arx` scenario engine and its conditional backtest |
| `evaluate_scenario.py` | Runs `scenario.py`'s backtest and presets, and writes the three scenario report files above |
| `site_data.py` | Exports the JSON files the static page in `site/` reads |
