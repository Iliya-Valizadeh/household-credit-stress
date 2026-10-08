"""The live forecast ledger (docs/eval_plan.md, "Live forecast ledger").

Run with `python -m household_credit_stress.forecast` after `refresh.py` has pulled the
latest data. Two append-only files live under `ledger/`:

- `ledger/forecasts.csv`: one row per region and horizon for the newest CBA-published
  origin month. A row is never edited or rewritten once written; this module only ever
  opens the file in append mode, and skips a region/horizon the ledger already has a
  row for, so running it twice on the same data adds nothing new.
- `ledger/outcomes.csv`: the actual rate for a forecast's target month, added once the
  CBA archive holds the file that first reports it (`data/raw/cba/YYYY-MM.xlsx`), never
  before. A target with no archive file yet is left ungraded; the live page shows it as
  a late or missed slot, per docs/eval_plan.md.

The point forecast is the ADR 0003 arx model (`arrears_model`); `persistence_bp` and
`ar1_bp` are the two backtest baselines for the same target, refit on data up to the
origin only, exactly as `backtest.run_backtest` does. `lo80_bp`/`hi80_bp` come from the
model's own past errors at the same horizon, the same way `backtest.run_backtest`
builds its intervals (not a claim this repo stands behind the way the backtest MAE is;
see the column note in docs/eval_plan.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from household_credit_stress import __version__, arrears_model, backtest, features, refresh

DATA_DIR = Path("data")
LEDGER_DIR = Path("ledger")

FORECASTS_COLUMNS: list[str] = [
    "origin_month",
    "target_month",
    "horizon",
    "region",
    "forecast_bp",
    "lo80_bp",
    "hi80_bp",
    "persistence_bp",
    "ar1_bp",
    "arrears_through",
    "unemployment_through",
    "rate_through",
    "model_version",
    "written_at",
]
OUTCOMES_COLUMNS: list[str] = ["target_month", "region", "actual_bp", "cba_file", "first_seen_at"]

FORECASTS_KEY = ("origin_month", "region", "horizon")
OUTCOMES_KEY = ("target_month", "region")

HORIZONS = backtest.HORIZONS
DECIMALS = backtest.DECIMALS


def _existing_keys(path: Path, key_columns: tuple[str, ...]) -> set[tuple[str, ...]]:
    """The key tuples already written to `path`, read as plain strings.

    Reading everything as `str` means a key built from a freshly computed row (where
    e.g. `horizon` is an `int`) has to be stringified the same way before comparing;
    `_row_key` does that for both sides.
    """
    if not path.exists() or path.stat().st_size == 0:
        return set()
    frame = pd.read_csv(path, dtype=str)
    if frame.empty:
        return set()
    return {tuple(row) for row in frame[list(key_columns)].itertuples(index=False, name=None)}


def _row_key(row: dict[str, Any], key_columns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row[col]) for col in key_columns)


def _append_rows(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> int:
    """Append `rows` to `path`, writing the header first if the file is new.

    This never reads the file back in to rewrite it: it only opens in append mode, so
    a line already on disk cannot be changed by this function, only added to.
    """
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    frame = pd.DataFrame(rows, columns=columns)
    text = frame.to_csv(index=False, header=is_new)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return len(rows)


def build_forecast_rows(
    panel: pd.DataFrame,
    origin: pd.Timestamp,
    model_version: str,
    written_at: dt.datetime,
    regions: tuple[str, ...] = features.REGIONS,
    horizons: tuple[int, ...] = HORIZONS,
) -> list[dict[str, Any]]:
    """One forecast row per region and horizon, for `origin`.

    `panel` is the feature panel from `features.build_feature_panel`, covering every
    region and month up to and including `origin` (and only those, per the
    point-in-time rule: see `arrears_model._check_history`). A region/horizon is left
    out, rather than guessed, if the arx model cannot yet fit or forecast it (ADR 0003,
    `MIN_FIT_ROWS`, or the driver terms not reaching that horizon); it then shows as a
    missed slot on the live page, per docs/eval_plan.md.
    """
    history_origins = pd.date_range(panel["month"].min(), origin, freq="MS")
    past = backtest.run_backtest(panel, history_origins, regions=regions, horizons=horizons)
    past = past[past["model"] == arrears_model.MODEL_NAME]

    written_at_text = written_at.isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for region in regions:
        region_panel = panel.loc[panel["region"] == region].sort_values("month")
        known_panel = region_panel.loc[region_panel["month"] <= origin]
        if known_panel.empty or not (known_panel["month"] == origin).any():
            continue
        drop_month = (
            backtest.MB_SK_LEVEL_SHIFT_MONTH if region in backtest.LEVEL_SHIFT_REGIONS else None
        )
        history = known_panel.set_index("month")["arrears_rate_bp"].sort_index()
        phi = backtest.fit_ar1(history, origin, drop_month)
        persistence_bp = backtest.forecast_persistence(history, origin)
        origin_row = known_panel.loc[known_panel["month"] == origin].iloc[0]

        try:
            fit: arrears_model.ArxFit | None = arrears_model.fit_arx(
                known_panel, origin, drop_month
            )
        except ValueError:
            # Too few usable rows to fit yet (ADR 0003, MIN_FIT_ROWS).
            fit = None

        for horizon in horizons:
            if fit is None:
                continue
            try:
                forecast_bp = arrears_model.forecast_arx(known_panel, origin, horizon, fit)
            except ValueError:
                # The driver terms this horizon needs are not known yet.
                continue
            ar1_bp = backtest.forecast_ar1(history, origin, horizon, phi)

            errors = past.loc[(past["region"] == region) & (past["horizon"] == horizon), "error_bp"]
            if len(errors) >= backtest.MIN_INTERVAL_ERRORS:
                lo80_bp = forecast_bp + float(np.percentile(errors, 10))
                hi80_bp = forecast_bp + float(np.percentile(errors, 90))
            else:
                lo80_bp = hi80_bp = float("nan")

            target = origin + pd.DateOffset(months=horizon)
            rows.append(
                {
                    "origin_month": f"{origin:%Y-%m}",
                    "target_month": f"{target:%Y-%m}",
                    "horizon": horizon,
                    "region": region,
                    "forecast_bp": round(forecast_bp, DECIMALS),
                    "lo80_bp": round(lo80_bp, DECIMALS) if not np.isnan(lo80_bp) else float("nan"),
                    "hi80_bp": round(hi80_bp, DECIMALS) if not np.isnan(hi80_bp) else float("nan"),
                    "persistence_bp": round(persistence_bp, DECIMALS),
                    "ar1_bp": round(ar1_bp, DECIMALS),
                    "arrears_through": f"{pd.Timestamp(origin_row['arrears_through']):%Y-%m}",
                    "unemployment_through": (
                        f"{pd.Timestamp(origin_row['unemployment_through']):%Y-%m}"
                    ),
                    "rate_through": f"{pd.Timestamp(origin_row['rate_through']):%Y-%m}",
                    "model_version": model_version,
                    "written_at": written_at_text,
                }
            )
    return rows


def append_forecasts(
    data_dir: Path = DATA_DIR,
    ledger_dir: Path = LEDGER_DIR,
    now: dt.datetime | None = None,
) -> int:
    """Write the new rows for the newest CBA-published origin month, and return how
    many were added. A region/horizon the ledger already has a row for is skipped, so
    this is safe to run more than once for the same origin."""
    now = now or dt.datetime.now(dt.UTC)
    panel = backtest.load_panel(data_dir)
    arrears = pd.read_csv(data_dir / "processed" / "arrears.csv", parse_dates=["month"])
    origin = refresh.latest_month("arrears", arrears)

    path = ledger_dir / "forecasts.csv"
    existing = _existing_keys(path, FORECASTS_KEY)
    rows = build_forecast_rows(panel, origin, __version__, now)
    new_rows = [row for row in rows if _row_key(row, FORECASTS_KEY) not in existing]
    return _append_rows(path, FORECASTS_COLUMNS, new_rows)


def grade_outcomes(
    data_dir: Path = DATA_DIR,
    ledger_dir: Path = LEDGER_DIR,
    now: dt.datetime | None = None,
) -> int:
    """Grade any ledger forecast whose target month now has a CBA archive file.

    A target counts as reported only once `data/raw/cba/YYYY-MM.xlsx` for that month
    exists: the archive keeps every file as published, named after the newest month it
    reports, so that file is the first one to report its own month (docs/eval_plan.md,
    "Live forecast ledger"). A target/region already graded is skipped."""
    now = now or dt.datetime.now(dt.UTC)
    forecasts_path = ledger_dir / "forecasts.csv"
    if not forecasts_path.exists() or forecasts_path.stat().st_size == 0:
        return 0
    forecasts = pd.read_csv(forecasts_path, dtype=str)
    if forecasts.empty:
        return 0

    outcomes_path = ledger_dir / "outcomes.csv"
    already_graded = _existing_keys(outcomes_path, OUTCOMES_KEY)

    arrears = pd.read_csv(data_dir / "processed" / "arrears.csv", parse_dates=["month"])
    arrears = arrears.set_index(["month", "region"])
    cba_dir = data_dir / "raw" / "cba"
    first_seen_at = now.isoformat(timespec="seconds")

    rows: list[dict[str, Any]] = []
    targets = forecasts[["target_month", "region"]].drop_duplicates()
    for target_month, region in targets.itertuples(index=False, name=None):
        if (target_month, region) in already_graded:
            continue
        target = pd.Timestamp(f"{target_month}-01")
        archive_file = cba_dir / f"{target:%Y-%m}.xlsx"
        if not archive_file.exists():
            continue  # not yet reported by the CBA; stays a late/missed slot for now
        try:
            counts = arrears.loc[(target, region)]
        except KeyError:
            continue
        mortgages, n_arrears = counts["mortgages"], counts["arrears"]
        if pd.isna(mortgages) or pd.isna(n_arrears) or mortgages == 0:
            continue
        actual_bp = round(features.BP_PER_UNIT * float(n_arrears) / float(mortgages), DECIMALS)
        rows.append(
            {
                "target_month": target_month,
                "region": region,
                "actual_bp": actual_bp,
                "cba_file": f"data/raw/cba/{target:%Y-%m}.xlsx",
                "first_seen_at": first_seen_at,
            }
        )
    return _append_rows(outcomes_path, OUTCOMES_COLUMNS, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--ledger-dir", type=Path, default=LEDGER_DIR)
    args = parser.parse_args(argv)

    n_forecasts = append_forecasts(args.data_dir, args.ledger_dir)
    n_outcomes = grade_outcomes(args.data_dir, args.ledger_dir)
    print(f"forecasts: {n_forecasts} new row(s); outcomes: {n_outcomes} new row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
