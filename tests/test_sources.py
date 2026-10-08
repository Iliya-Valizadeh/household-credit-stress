"""Tests for the data sources. No test touches the network: replies are built in code."""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd
import pytest

from household_credit_stress.sources import boc, cba, http, statcan

# Bank of Canada -------------------------------------------------------------------


def test_valet_parse_skips_blanks_and_sorts() -> None:
    payload = {
        "observations": [
            {"d": "2026-09-30", "V1": {"v": "6.09"}},
            {"d": "2026-09-23", "V1": {"v": ""}},
            {"d": "2026-09-16", "V1": {"v": "6.00"}},
            {"d": "2026-09-09"},
        ]
    }
    frame = boc.parse_observations(payload, "V1")
    assert list(frame["value"]) == [6.00, 6.09]
    assert frame["date"].is_monotonic_increasing


def test_valet_parse_rejects_empty_reply() -> None:
    with pytest.raises(ValueError):
        boc.parse_observations({"observations": []}, "V1")


def test_monthly_mean_groups_weeks_into_months() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-26", "2026-09-02", "2026-09-30"]),
            "value": [5.0, 6.0, 7.0],
        }
    )
    out = boc.monthly_mean(frame)
    assert list(out["month"]) == [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")]
    assert list(out["value"]) == [5.0, 6.5]


def test_fetch_series_builds_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_get(url: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        seen.append(url)
        return json.dumps({"observations": [{"d": "2026-01-07", "V9": {"v": "5"}}]}).encode()

    monkeypatch.setattr(boc, "get_bytes", fake_get)
    frame = boc.fetch_series("V9", start="2026-01-01")
    assert len(frame) == 1
    assert "V9" in seen[0] and "start_date=2026-01-01" in seen[0]


# Statistics Canada ----------------------------------------------------------------


def _wds_item(geo: int, points: list[tuple[str, float | None]]) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "object": {
            "coordinate": statcan.coordinate(geo),
            "vectorDataPoint": [{"refPer": d, "value": v} for d, v in points],
        },
    }


def test_wds_parse_maps_regions_and_skips_blanks() -> None:
    payload = [
        _wds_item(7, [("2026-07-01", 7.1), ("2026-08-01", 6.9)]),
        _wds_item(9, [("2026-08-01", None)]),
        _wds_item(2, [("2026-08-01", 10.2)]),
    ]
    frame = statcan.parse_response(payload)
    assert sorted(frame["region"].unique()) == ["NL", "ON"]
    on = frame[frame["region"] == "ON"]
    assert list(on["unemployment_rate"]) == [7.1, 6.9]


def test_wds_parse_raises_on_failed_item() -> None:
    with pytest.raises(ValueError):
        statcan.parse_response([{"status": "FAILED", "object": "bad coordinate"}])


def test_wds_parse_raises_when_empty() -> None:
    with pytest.raises(ValueError):
        statcan.parse_response([_wds_item(7, [("2026-08-01", None)])])


def test_wds_coordinate_selects_unemployment_rate() -> None:
    assert statcan.coordinate(7) == "7.7.1.1.1.1.0.0.0.0"


def test_fetch_unemployment_asks_for_every_region(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        assert body is not None and content_type == "application/json"
        request = json.loads(body)
        assert len(request) == len(statcan.GEOGRAPHY)
        geos = [int(r["coordinate"].split(".")[0]) for r in request]
        return json.dumps([_wds_item(g, [("2026-08-01", 6.0)]) for g in geos]).encode()

    monkeypatch.setattr(statcan, "get_bytes", fake_get)
    frame = statcan.fetch_unemployment(latest_n=1)
    assert set(frame["region"]) == set(statcan.GEOGRAPHY.values())


def test_coordinate_selects_other_indicators() -> None:
    assert statcan.coordinate(2) == "2.7.1.1.1.1.0.0.0.0"  # default: unemployment rate
    assert statcan.coordinate(2, statcan.LABOUR_FORCE) == "2.2.1.1.1.1.0.0.0.0"
    assert statcan.coordinate(2, statcan.UNEMPLOYED) == "2.6.1.1.1.1.0.0.0.0"


def _wds_indicator_item(
    geo: int, indicator: int, points: list[tuple[str, float | None]]
) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "object": {
            "coordinate": statcan.coordinate(geo, indicator),
            "vectorDataPoint": [{"refPer": d, "value": v} for d, v in points],
        },
    }


def test_parse_labour_force_combines_both_counts_per_region_and_month() -> None:
    nl = statcan._GEO_BY_REGION["NL"]
    payload = [
        _wds_indicator_item(nl, statcan.UNEMPLOYED, [("2026-08-01", 10.0)]),
        _wds_indicator_item(nl, statcan.LABOUR_FORCE, [("2026-08-01", 100.0)]),
    ]
    frame = statcan.parse_labour_force(payload)
    assert list(frame.columns) == ["month", "region", "unemployed", "labour_force"]
    row = frame.iloc[0]
    assert row["region"] == "NL"
    assert row["unemployed"] == 10.0
    assert row["labour_force"] == 100.0


def test_parse_labour_force_raises_on_failed_item() -> None:
    with pytest.raises(ValueError):
        statcan.parse_labour_force([{"status": "FAILED", "object": "bad coordinate"}])


def test_parse_labour_force_raises_when_empty() -> None:
    nl = statcan._GEO_BY_REGION["NL"]
    with pytest.raises(ValueError):
        statcan.parse_labour_force(
            [_wds_indicator_item(nl, statcan.UNEMPLOYED, [("2026-08-01", None)])]
        )


def test_fetch_labour_force_asks_for_both_counts_for_each_atlantic_province(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        assert body is not None and content_type == "application/json"
        request = json.loads(body)
        assert len(request) == len(statcan.ATLANTIC_PROVINCES) * 2
        items = [
            _wds_indicator_item(
                int(r["coordinate"].split(".")[0]),
                int(r["coordinate"].split(".")[1]),
                [("2026-08-01", 1.0)],
            )
            for r in request
        ]
        return json.dumps(items).encode()

    monkeypatch.setattr(statcan, "get_bytes", fake_get)
    frame = statcan.fetch_labour_force(latest_n=1)
    assert set(frame["region"]) == set(statcan.ATLANTIC_PROVINCES)
    assert frame["unemployed"].notna().all()
    assert frame["labour_force"].notna().all()


# Canadian Bankers Association -----------------------------------------------------


def make_cba_workbook(sheets: dict[str, str] | None = None, month_line: str | None = None) -> bytes:
    """A small workbook laid out like the CBA file: summary sheet plus two-block regions."""
    wb = openpyxl.Workbook()
    summary = wb.active
    assert summary is not None
    summary.title = "Summary"
    summary["A1"] = "CANADIAN BANKERS ASSOCIATION"
    summary["A3"] = month_line or "Month Ended July 31, 2026"
    for sheet in sheets or cba.SHEETS:
        ws = wb.create_sheet(sheet)
        ws.append(["Number of Residential Mortgages in Arrears"])
        ws.append(["As at:", "Mortgages", "in Arrears", "%", None, "As at:", "Mortgages"])
        ws.append(
            [dt.datetime(1995, 1, 31), 1000, 5, 0.005, None, dt.datetime(2026, 6, 1), 2000, 6]
        )
        ws.append(
            [dt.datetime(1995, 2, 28), 1001, 4, 0.004, None, dt.datetime(2026, 7, 1), 2001, 7]
        )
        ws.append([dt.datetime(1995, 3, 31), None, None, None, None, dt.datetime(2026, 8, 1), 2002])
        ws.append([dt.datetime(1995, 4, 30), 1002, None, None, None, None, None])
        ws.append(["* Mortgage arrears is three or more months"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_find_xlsx_url_handles_relative_and_absolute_links() -> None:
    rel = '<a href="/Assets/x/stat-mortgages-arrears-july-2026-en.xlsx">xlsx</a>'
    assert (
        cba.find_xlsx_url(rel) == "https://cba.ca/Assets/x/stat-mortgages-arrears-july-2026-en.xlsx"
    )
    absolute = '<a href="https://example.org/arrears-2026-en.xlsx">'
    assert cba.find_xlsx_url(absolute) == "https://example.org/arrears-2026-en.xlsx"


def test_find_xlsx_url_ignores_french_file_and_fails_when_missing() -> None:
    with pytest.raises(ValueError):
        cba.find_xlsx_url('<a href="/stat-mortgages-arrears-july-2026-fr.xlsx">')


def test_report_month_reads_summary_line() -> None:
    assert cba.report_month(make_cba_workbook()) == pd.Timestamp("2026-07-01")


def test_report_month_fails_without_line() -> None:
    with pytest.raises(ValueError):
        cba.report_month(make_cba_workbook(month_line="no date here"))


def test_parse_workbook_reads_both_blocks_and_normalizes_dates() -> None:
    frame = cba.parse_workbook(make_cba_workbook())
    on = frame[frame["region"] == "ON"].set_index("month")
    assert list(on.index) == [
        pd.Timestamp("1995-01-01"),
        pd.Timestamp("1995-02-01"),
        pd.Timestamp("1995-04-01"),
        pd.Timestamp("2026-06-01"),
        pd.Timestamp("2026-07-01"),
        pd.Timestamp("2026-08-01"),
    ]
    assert on.loc["2026-07-01", "arrears"] == 7
    assert pd.isna(on.loc["2026-08-01", "arrears"])
    assert pd.isna(on.loc["1995-04-01", "arrears"])
    assert set(frame["region"]) == set(cba.SHEETS.values())


def test_parse_workbook_fails_when_a_sheet_is_missing() -> None:
    sheets = {k: v for k, v in cba.SHEETS.items() if k != "ON"}
    with pytest.raises(ValueError, match="ON"):
        cba.parse_workbook(make_cba_workbook(sheets=sheets))


def test_download_latest_keeps_a_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workbook = make_cba_workbook()

    def fake_get(url: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        if url == cba.PAGE_URL:
            return b'<a href="/a/stat-mortgages-arrears-july-2026-en.xlsx">'
        assert url == "https://cba.ca/a/stat-mortgages-arrears-july-2026-en.xlsx"
        return workbook

    monkeypatch.setattr(cba, "get_bytes", fake_get)
    frame, month, saved = cba.download_latest(tmp_path / "cba")
    assert month == pd.Timestamp("2026-07-01")
    assert saved == tmp_path / "cba" / "2026-07.xlsx"
    assert saved.read_bytes() == workbook
    assert not frame.empty


# HTTP helper ----------------------------------------------------------------------


class _Reply:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.data


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {}, None)  # type: ignore[arg-type]


def test_get_bytes_retries_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    replies: list[Exception | bytes] = [_http_error(503), urllib.error.URLError("down"), b"ok"]
    sent: list[Any] = []

    def fake_open(request: Any, timeout: int) -> _Reply:
        sent.append(request)
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Reply(item)

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert http.get_bytes("https://x", body=b"{}", content_type="application/json") == b"ok"
    assert len(sent) == 3
    assert sent[0].get_header("Content-type") == "application/json"


def test_get_bytes_raises_client_errors_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_open(request: Any, timeout: int) -> _Reply:
        nonlocal calls
        calls += 1
        raise _http_error(404)

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    with pytest.raises(urllib.error.HTTPError):
        http.get_bytes("https://x")
    assert calls == 1


def test_get_bytes_gives_up_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_open(request: Any, timeout: int) -> _Reply:
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(urllib.error.URLError):
        http.get_bytes("https://x")
