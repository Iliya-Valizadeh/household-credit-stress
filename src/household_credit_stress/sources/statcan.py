"""Provincial unemployment rates from the Statistics Canada Web Data Service.

Table 14-10-0287-01 (Labour Force Survey, monthly, seasonally adjusted). The service is
free and needs no key: https://www.statcan.gc.ca/en/developers/wds
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from household_credit_stress.sources.http import get_bytes

WDS_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromCubePidCoordAndLatestNPeriods"
LFS_TABLE = 14100287

# Member ids in the table's Geography dimension.
GEOGRAPHY = {
    1: "CA",
    2: "NL",
    3: "PE",
    4: "NS",
    5: "NB",
    6: "QC",
    7: "ON",
    8: "MB",
    9: "SK",
    10: "AB",
    11: "BC",
}

# Member ids in the table's "Labour force characteristics" dimension. Only the three
# this project uses are named; the table has more (population, employment, ...).
UNEMPLOYMENT_RATE = 7
LABOUR_FORCE = 2
UNEMPLOYED = 6

# The other dimensions after the indicator: total gender (1), 15 years and over (1),
# estimate (1), seasonally adjusted (1). The four trailing zeros are unused dimensions.
_COORDINATE = "{geo}.{indicator}.1.1.1.1.0.0.0.0"

# Geography member id, keyed by region code.
_GEO_BY_REGION = {region: geo_id for geo_id, region in GEOGRAPHY.items()}

# The four provinces the CBA's Atlantic (ATL) region is built from.
ATLANTIC_PROVINCES = ("NL", "PE", "NS", "NB")


def coordinate(geo_id: int, indicator: int = UNEMPLOYMENT_RATE) -> str:
    """The table coordinate for one region and one indicator (rate, count, ...)."""
    return _COORDINATE.format(geo=geo_id, indicator=indicator)


def parse_response(payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Turn a WDS reply into rows of (month, region, unemployment_rate)."""
    rows = []
    for item in payload:
        if item.get("status") != "SUCCESS":
            raise ValueError(f"WDS request failed: {item.get('object')}")
        obj = item["object"]
        geo_id = int(obj["coordinate"].split(".")[0])
        region = GEOGRAPHY[geo_id]
        for point in obj["vectorDataPoint"]:
            if point.get("value") is None:
                continue
            rows.append(
                {
                    "month": pd.Timestamp(point["refPer"]),
                    "region": region,
                    "unemployment_rate": float(point["value"]),
                }
            )
    if not rows:
        raise ValueError("WDS returned no unemployment values")
    return pd.DataFrame(rows).sort_values(["region", "month"], ignore_index=True)


def fetch_unemployment(latest_n: int = 1000) -> pd.DataFrame:
    """Download every region's monthly unemployment rate, up to `latest_n` months back."""
    request = [
        {"productId": LFS_TABLE, "coordinate": coordinate(geo), "latestN": latest_n}
        for geo in GEOGRAPHY
    ]
    raw = get_bytes(WDS_URL, body=json.dumps(request).encode(), content_type="application/json")
    return parse_response(json.loads(raw))


def parse_labour_force(payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Turn a WDS reply of unemployed and labour-force counts into one row per region
    and month, with both counts as columns.

    Used to build the Atlantic (ATL) unemployment rate from its four provinces; see
    docs/eval_plan.md, "Atlantic unemployment". Counts are in thousands, as published.
    """
    indicator_column = {UNEMPLOYED: "unemployed", LABOUR_FORCE: "labour_force"}
    rows = []
    for item in payload:
        if item.get("status") != "SUCCESS":
            raise ValueError(f"WDS request failed: {item.get('object')}")
        obj = item["object"]
        geo_id, indicator = (int(part) for part in obj["coordinate"].split(".")[:2])
        region = GEOGRAPHY[geo_id]
        column = indicator_column[indicator]
        for point in obj["vectorDataPoint"]:
            if point.get("value") is None:
                continue
            rows.append(
                {
                    "month": pd.Timestamp(point["refPer"]),
                    "region": region,
                    "column": column,
                    "value": float(point["value"]),
                }
            )
    if not rows:
        raise ValueError("WDS returned no labour force values")
    long = pd.DataFrame(rows)
    wide = long.pivot_table(
        index=["region", "month"], columns="column", values="value"
    ).reset_index()
    wide.columns.name = None
    for column in indicator_column.values():
        if column not in wide.columns:
            wide[column] = float("nan")
    return wide.sort_values(["region", "month"], ignore_index=True)[
        ["month", "region", "unemployed", "labour_force"]
    ]


def fetch_labour_force(
    latest_n: int = 1000, regions: tuple[str, ...] = ATLANTIC_PROVINCES
) -> pd.DataFrame:
    """Download unemployed and labour-force counts for `regions`, up to `latest_n`
    months back. Defaults to the four provinces needed for the Atlantic rate."""
    request = [
        {
            "productId": LFS_TABLE,
            "coordinate": coordinate(_GEO_BY_REGION[region], indicator),
            "latestN": latest_n,
        }
        for region in regions
        for indicator in (UNEMPLOYED, LABOUR_FORCE)
    ]
    raw = get_bytes(WDS_URL, body=json.dumps(request).encode(), content_type="application/json")
    return parse_labour_force(json.loads(raw))
