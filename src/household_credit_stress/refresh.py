"""Pull the latest public data and record how fresh each source is.

Run with `python -m household_credit_stress.refresh`. It writes:

- `data/processed/mortgage_rate_5y.csv`: monthly mean of the 5-year posted rate
- `data/processed/unemployment.csv`: monthly unemployment rate by province
- `data/processed/arrears.csv`: monthly mortgages and arrears by CBA region
- `data/raw/cba/YYYY-MM.csv`: the numbers from every CBA file, since the CBA removes old
  ones. The spreadsheet itself is not kept (ADR 0006)
- `data/status.json`: for each source, whether the last pull worked and how old its
  newest month is

A source that fails keeps its previous CSV and is marked stale in `status.json`. The run
still exits 0, so a publisher changing its site does not send a failure email every
week. The scheduled workflow prints a warning instead, and anything that shows results
reads `status.json` and labels stale data as stale. An unexpected error outside a single
source is also printed as a warning, with exit 0. Pass `--strict` to exit 1 (or raise)
when any source fails.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from household_credit_stress.sources import boc, cba, statcan

DATA_DIR = Path("data")

# How many months old a source's newest value may be before it counts as stale. The
# CBA publishes about two months after the month it reports on.
MAX_AGE_MONTHS = {
    "mortgage_rate_5y": 2,
    "unemployment": 3,
    "arrears": 5,
    "labour_force": 3,
}


@dataclass
class SourceStatus:
    ok: bool
    stale: bool
    latest_month: str | None
    checked_at: str
    error: str | None = None


def months_between(earlier: pd.Timestamp, later: pd.Timestamp) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _pull_rates(data_dir: Path) -> pd.DataFrame:
    return boc.monthly_mean(boc.fetch_series(boc.MORTGAGE_5Y))


def _pull_unemployment(data_dir: Path) -> pd.DataFrame:
    return statcan.fetch_unemployment()


def _pull_arrears(data_dir: Path) -> pd.DataFrame:
    frame, _, _ = cba.download_latest(data_dir / "raw" / "cba")
    return frame


def _pull_labour_force(data_dir: Path) -> pd.DataFrame:
    # Unemployed and labour-force counts for the four Atlantic provinces, used to
    # build the ATL unemployment rate; see features.atlantic_unemployment_rate and
    # "Atlantic unemployment" in docs/eval_plan.md.
    return statcan.fetch_labour_force()


PULLERS: dict[str, Callable[[Path], pd.DataFrame]] = {
    "mortgage_rate_5y": _pull_rates,
    "unemployment": _pull_unemployment,
    "arrears": _pull_arrears,
    "labour_force": _pull_labour_force,
}


def latest_month(name: str, frame: pd.DataFrame) -> pd.Timestamp:
    """The newest month that has a real value (arrears rows for future months are blank)."""
    if name == "arrears":
        frame = frame[frame["arrears"].notna()]
    return pd.Timestamp(frame["month"].max())


def refresh(
    data_dir: Path = DATA_DIR,
    pullers: dict[str, Callable[[Path], pd.DataFrame]] | None = None,
    today: dt.date | None = None,
) -> dict[str, SourceStatus]:
    """Pull every source, write what worked, and return each source's status."""
    pullers = PULLERS if pullers is None else pullers
    today_month = pd.Timestamp(today or dt.date.today()).to_period("M").to_timestamp()
    checked_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    status_path = data_dir / "status.json"
    previous = json.loads(status_path.read_text()) if status_path.exists() else {}

    statuses: dict[str, SourceStatus] = {}
    for name, pull in pullers.items():
        try:
            frame = pull(data_dir)
            newest = latest_month(name, frame)
            frame.to_csv(processed / f"{name}.csv", index=False, date_format="%Y-%m-%d")
            stale = months_between(newest, today_month) > MAX_AGE_MONTHS[name]
            statuses[name] = SourceStatus(True, stale, f"{newest:%Y-%m}", checked_at)
        except Exception as error:  # noqa: BLE001  any failure marks the source stale
            last = previous.get(name, {}).get("latest_month")
            statuses[name] = SourceStatus(
                False, True, last, checked_at, f"{type(error).__name__}: {error}"
            )

    status_path.write_text(json.dumps({k: asdict(v) for k, v in statuses.items()}, indent=2) + "\n")
    return statuses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--strict", action="store_true", help="exit 1 if any source fails")
    args = parser.parse_args(argv)

    try:
        statuses = refresh(args.data_dir)
    except Exception as error:  # noqa: BLE001  a scheduled run must not fail on a surprise
        if args.strict:
            raise
        # refresh() already handles a failing source. This catches anything else, such as
        # an unreadable status.json. The old files stay and keep their stale labels.
        print(f"::warning title=Refresh crashed::{type(error).__name__}: {error}")
        return 0
    for name, s in statuses.items():
        line = f"{name}: latest {s.latest_month}, ok={s.ok}, stale={s.stale}"
        print(line if not s.error else f"{line} ({s.error})")
        if s.stale:
            # Shows as a yellow note on the GitHub Actions run, without failing it.
            print(f"::warning title={name} is stale::{s.error or 'newest data is too old'}")
    failed = any(not s.ok for s in statuses.values())
    return 1 if args.strict and failed else 0


if __name__ == "__main__":
    sys.exit(main())
