"""Residential mortgage arrears from the Canadian Bankers Association (CBA).

The CBA posts one spreadsheet each month at https://cba.ca/article/mortgages-in-arrears.
Each new file holds the full monthly history since January 1995 for every region, and
the CBA takes the old file down when it posts a new one. So the refresh keeps a copy of
every file it downloads.

A mortgage is "in arrears" when payments are three or more months overdue.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

import openpyxl
import pandas as pd

from household_credit_stress.sources.http import get_bytes

PAGE_URL = "https://cba.ca/article/mortgages-in-arrears"
SITE_ROOT = "https://cba.ca"

# Sheet name in the workbook -> short region code used in this repo.
SHEETS = {
    "CAN": "CA",
    "AC": "ATL",
    "QC": "QC",
    "ON": "ON",
    "MB": "MB",
    "SK": "SK",
    "AB": "AB",
    "BC": "BC",
    "Terr.": "TERR",
}

_XLSX_LINK = re.compile(r'href="([^"]*arrears[^"]*-en\.xlsx)"', re.IGNORECASE)
_MONTH_ENDED = re.compile(r"Month Ended\s+([A-Za-z]+ \d{1,2}, \d{4})")


def find_xlsx_url(page_html: str) -> str:
    """Return the full URL of the English spreadsheet linked from the CBA page."""
    match = _XLSX_LINK.search(page_html)
    if not match:
        raise ValueError("No arrears spreadsheet link found on the CBA page")
    href = match.group(1)
    return href if href.startswith("http") else SITE_ROOT + href


def report_month(workbook_bytes: bytes) -> pd.Timestamp:
    """The month the file reports on, read from the "Month Ended ..." line of the summary."""
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)
    try:
        for row in wb["Summary"].iter_rows(max_row=10, values_only=True):
            for cell in row:
                if isinstance(cell, str) and (match := _MONTH_ENDED.search(cell)):
                    day = dt.datetime.strptime(match.group(1), "%B %d, %Y")
                    return pd.Timestamp(day.year, day.month, 1)
    finally:
        wb.close()
    raise ValueError("No 'Month Ended' line in the Summary sheet")


def parse_workbook(workbook_bytes: bytes) -> pd.DataFrame:
    """Return rows of (month, region, mortgages, arrears) for every filled month.

    Each region sheet lays its history out in side-by-side blocks. A block row starts
    with a date, followed by the number of mortgages and the number in arrears. Older
    rows are dated at month end and newer rows at month start, so every date is moved
    to the first of its month. The CBA's own percentage column is ignored because some
    older rows are rounded; the rate is recomputed from the two counts instead.
    """
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)
    rows = []
    try:
        for sheet, region in SHEETS.items():
            if sheet not in wb.sheetnames:
                raise ValueError(f"Sheet {sheet!r} missing; the CBA layout may have changed")
            for values in wb[sheet].iter_rows(values_only=True):
                for i, cell in enumerate(values):
                    if not isinstance(cell, dt.datetime) or i + 2 >= len(values):
                        continue
                    total, arrears = values[i + 1], values[i + 2]
                    if not isinstance(total, int | float):
                        continue
                    rows.append(
                        {
                            "month": pd.Timestamp(cell.year, cell.month, 1),
                            "region": region,
                            "mortgages": int(total),
                            "arrears": int(arrears) if isinstance(arrears, int | float) else None,
                        }
                    )
    finally:
        wb.close()
    if not rows:
        raise ValueError("No monthly rows found in the CBA workbook")
    frame = pd.DataFrame(rows).astype({"arrears": "Int64"})
    frame = frame.sort_values(["region", "month"], ignore_index=True)
    if frame.duplicated(["region", "month"]).any():
        raise ValueError("A region has two rows for the same month")
    return frame


def download_latest(archive_dir: Path) -> tuple[pd.DataFrame, pd.Timestamp, Path]:
    """Download the current spreadsheet, keep a copy, and return its parsed rows.

    The copy is saved as `<archive_dir>/YYYY-MM.xlsx`, named after the report month.
    """
    page = get_bytes(PAGE_URL).decode("utf-8", errors="replace")
    workbook = get_bytes(find_xlsx_url(page))
    month = report_month(workbook)
    frame = parse_workbook(workbook)
    archive_dir.mkdir(parents=True, exist_ok=True)
    saved = archive_dir / f"{month:%Y-%m}.xlsx"
    if not saved.exists():
        saved.write_bytes(workbook)
    return frame, month, saved
