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

# The other dimensions: unemployment rate (7), total gender (1), 15 years and over (1),
# estimate (1), seasonally adjusted (1). The four trailing zeros are unused dimensions.
_COORDINATE = "{geo}.7.1.1.1.1.0.0.0.0"


def coordinate(geo_id: int) -> str:
    """The table coordinate for one region's unemployment rate."""
    return _COORDINATE.format(geo=geo_id)


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
