# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and each release matches a
git tag.

## [Unreleased]

### Added

- Project skeleton generated from `ds-project-standard`.
- Fetchers for the Bank of Canada, Statistics Canada and CBA data, and a weekly refresh
  in which a failed source is shown as stale (ADR 0001).
- The pre-registered evaluation plan and forecast target (ADR 0002).
- The monthly feature panel with point-in-time lags, the [backtest](docs/glossary.md#backtest) harness, and the
  persistence and AR(1) baselines.
- The `arx` model (ADR 0003) and its backtest result.
- The append-only live forecast ledger, with its first forecasts.
- The `pooled_arx` scenario engine (ADR 0004), its twelve- and twenty-four-month check,
  and the history presets.
- The static web page in `site/`.
- Docs to the house standard, and an ML Test Score self-assessment of the real system.

### Removed

- The template's synthetic worked example.
