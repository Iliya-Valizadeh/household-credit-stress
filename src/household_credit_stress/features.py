"""Builds the monthly feature panel used by the backtest and the live forecast.

One row per CBA region and origin month L (ATL, QC, ON, MB, SK, AB, BC, CA; TERR is
left out, per `docs/eval_plan.md`). Every feature holds the value that was actually
published before a forecast made at L could use it: CBA arrears and mortgages through
L, and the unemployment rate and the posted 5-year mortgage rate through L+1. See
"Data known at each origin" in `docs/eval_plan.md`.

The Atlantic (ATL) unemployment rate is built from its four provinces (NL, PE, NS,
NB); see "Atlantic unemployment" in the same plan.
"""

from __future__ import annotations

import logging
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

# The CBA regions this project forecasts. TERR has no arrears figures and is left out.
REGIONS: Final = ("CA", "ATL", "QC", "ON", "MB", "SK", "AB", "BC")

# The four provinces the CBA's Atlantic (ATL) region is built from.
ATLANTIC_PROVINCES: Final = ("NL", "PE", "NS", "NB")

# How many months ahead of the CBA month L each source may be used from, per the
# "Data known at each origin" table in docs/eval_plan.md. CBA arrears and mortgages
# have no lead: L is the latest month by definition.
UNEMPLOYMENT_LEAD_MONTHS: Final = 1
MORTGAGE_RATE_LEAD_MONTHS: Final = 1

BP_PER_UNIT: Final = 10_000


def _lead(frame: pd.DataFrame, lead_months: int) -> pd.DataFrame:
    """Relabel `frame`'s `month` column as the origin it is usable from.

    A value published for `month` may be used by a forecast made at origin
    `month - lead_months` (see the "Data known at each origin" table in
    docs/eval_plan.md). `lead_months` is 0 for a source the origin month itself
    publishes, such as the CBA's own arrears and mortgages.
    """
    out = frame.copy()
    out["month"] = out["month"] - pd.DateOffset(months=lead_months)
    return out


def atlantic_unemployment_rate(
    unemployment: pd.DataFrame, labour_force: pd.DataFrame
) -> pd.DataFrame:
    """One row per month: the Atlantic (ATL) unemployment rate.

    `unemployment` has columns month, region, unemployment_rate (at least the four
    Atlantic provinces). `labour_force` has columns month, region, unemployed,
    labour_force (from `sources.statcan.fetch_labour_force`).

    For a month where every province has both counts, the rate is
    100 * sum(unemployed) / sum(labour_force) (the exact formula in
    docs/eval_plan.md). Where a province's counts are missing for a month, that
    month's rate falls back to the labour-force-weighted average of the provincial
    rates, and this is logged. A month with neither counts nor weights for every
    province is left out.
    """
    rates = unemployment[unemployment["region"].isin(ATLANTIC_PROVINCES)].pivot(
        index="month", columns="region", values="unemployment_rate"
    )
    counts = labour_force[labour_force["region"].isin(ATLANTIC_PROVINCES)]
    unemployed = counts.pivot(index="month", columns="region", values="unemployed")
    weights = counts.pivot(index="month", columns="region", values="labour_force")

    provinces = list(ATLANTIC_PROVINCES)
    months = sorted(set(rates.index) | set(weights.index))
    rows = []
    for month in months:
        month_weights = weights.loc[month].reindex(provinces) if month in weights.index else None
        has_weights = month_weights is not None and month_weights.notna().all()

        month_counts = (
            unemployed.loc[month].reindex(provinces) if month in unemployed.index else None
        )
        has_counts = has_weights and month_counts is not None and month_counts.notna().all()

        if has_counts:
            assert month_counts is not None and month_weights is not None
            rate = 100 * month_counts.sum() / month_weights.sum()
            rows.append({"month": month, "region": "ATL", "unemployment_rate": rate})
            continue

        month_rates = rates.loc[month].reindex(provinces) if month in rates.index else None
        has_rates = month_rates is not None and month_rates.notna().all()
        if has_weights and has_rates:
            assert month_rates is not None and month_weights is not None
            rate = (month_rates * month_weights).sum() / month_weights.sum()
            logger.info(
                "ATL unemployment for %s uses the labour-force weighted rate average; "
                "a province's unemployed or labour-force count is missing",
                month.strftime("%Y-%m"),
            )
            rows.append({"month": month, "region": "ATL", "unemployment_rate": rate})
            continue

        logger.warning(
            "ATL unemployment for %s skipped; neither counts nor weights cover all four provinces",
            month.strftime("%Y-%m"),
        )
    if not rows:
        return pd.DataFrame(
            {
                "month": pd.Series([], dtype="datetime64[ns]"),
                "region": pd.Series([], dtype=str),
                "unemployment_rate": pd.Series([], dtype=float),
            }
        )
    return pd.DataFrame(rows)


def build_feature_panel(
    arrears: pd.DataFrame,
    unemployment: pd.DataFrame,
    mortgage_rate: pd.DataFrame,
    labour_force: pd.DataFrame,
) -> pd.DataFrame:
    """One row per CBA region and origin month L, with every feature as it was known
    at L (see "Data known at each origin" in docs/eval_plan.md).

    `arrears` has columns month, region, mortgages, arrears (`sources.cba`).
    `unemployment` has columns month, region, unemployment_rate (`sources.statcan`),
    for the CBA regions other than ATL plus the Atlantic provinces. `mortgage_rate`
    has columns month, value: the national monthly mean posted 5-year rate
    (`sources.boc`). `labour_force` has columns month, region, unemployed,
    labour_force, for the Atlantic provinces (`sources.statcan.fetch_labour_force`).

    Columns of the result: month (the origin L), region, mortgages, arrears,
    arrears_rate_bp, unemployment_rate, mortgage_rate_5y, arrears_through,
    unemployment_through, rate_through.
    """
    panel = arrears[arrears["region"].isin(REGIONS)].copy()
    panel["arrears_rate_bp"] = BP_PER_UNIT * panel["arrears"] / panel["mortgages"]

    atl_rate = atlantic_unemployment_rate(unemployment, labour_force)
    all_unemployment = pd.concat(
        [unemployment[unemployment["region"].isin(REGIONS)], atl_rate], ignore_index=True
    )
    unemployment_known = _lead(all_unemployment, UNEMPLOYMENT_LEAD_MONTHS)
    panel = panel.merge(
        unemployment_known[["month", "region", "unemployment_rate"]],
        on=["month", "region"],
        how="left",
    )

    rate_known = _lead(
        mortgage_rate.rename(columns={"value": "mortgage_rate_5y"}), MORTGAGE_RATE_LEAD_MONTHS
    )
    panel = panel.merge(rate_known[["month", "mortgage_rate_5y"]], on="month", how="left")

    panel["arrears_through"] = panel["month"]
    panel["unemployment_through"] = panel["month"] + pd.DateOffset(months=UNEMPLOYMENT_LEAD_MONTHS)
    panel["rate_through"] = panel["month"] + pd.DateOffset(months=MORTGAGE_RATE_LEAD_MONTHS)

    return panel.sort_values(["region", "month"], ignore_index=True)[
        [
            "month",
            "region",
            "mortgages",
            "arrears",
            "arrears_rate_bp",
            "unemployment_rate",
            "mortgage_rate_5y",
            "arrears_through",
            "unemployment_through",
            "rate_through",
        ]
    ]
