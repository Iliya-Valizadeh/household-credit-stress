"""Interest rates from the Bank of Canada Valet API.

Valet is free and needs no key: https://www.bankofcanada.ca/valet/docs
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from household_credit_stress.sources.http import get_bytes

VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json?start_date={start}"

# The 5-year conventional mortgage rate posted by the chartered banks, weekly.
MORTGAGE_5Y = "V80691335"


def parse_observations(payload: dict[str, Any], series: str) -> pd.DataFrame:
    """Turn a Valet JSON reply into rows of (date, value), skipping blank values."""
    rows = []
    for obs in payload.get("observations", []):
        cell = obs.get(series)
        if not cell or cell.get("v") in (None, ""):
            continue
        rows.append({"date": pd.Timestamp(obs["d"]), "value": float(cell["v"])})
    if not rows:
        raise ValueError(f"Valet returned no values for {series}")
    return pd.DataFrame(rows).sort_values("date", ignore_index=True)


def fetch_series(series: str, start: str = "1989-01-01") -> pd.DataFrame:
    """Download one Valet series from `start` to the latest value.

    `start` default is 1989-01-01: ADR 0004 (docs/decisions/0004-scenarios.md) needs
    the posted 5-year rate from 1989-10 for the early-1990s preset, and the Valet
    series for `MORTGAGE_5Y` covers that far back (checked by hand against
    https://www.bankofcanada.ca/valet/observations/V80691335/json?start_date=1989-01-01
    before this change).
    """
    raw = get_bytes(VALET_URL.format(series=series, start=start))
    return parse_observations(json.loads(raw), series)


def monthly_mean(frame: pd.DataFrame) -> pd.DataFrame:
    """Average a weekly series into calendar months, dated the first of the month."""
    month = frame["date"].dt.to_period("M").dt.to_timestamp()
    out = frame.groupby(month)["value"].mean().reset_index()
    return out.rename(columns={"date": "month"})
