"""Tests for the weekly refresh workflow's commit decision (T14, `_portfolio/hcs/TASKS.md`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from household_credit_stress import refresh_commit

OK_UNCHANGED = {
    "arrears": {
        "ok": True,
        "stale": False,
        "latest_month": "2026-07",
        "checked_at": "2026-10-01T00:00:00+00:00",
        "error": None,
    }
}


def test_identical_snapshots_are_unchanged() -> None:
    assert not refresh_commit.status_flags_changed(OK_UNCHANGED, OK_UNCHANGED)


def test_checked_at_and_error_alone_do_not_count_as_changed() -> None:
    after = {
        "arrears": {
            **OK_UNCHANGED["arrears"],
            "checked_at": "2026-10-08T00:00:00+00:00",
            "error": "transient warning, still ok",
        }
    }
    assert not refresh_commit.status_flags_changed(OK_UNCHANGED, after)


def test_latest_month_alone_does_not_count_as_changed() -> None:
    # A new month lands in a tracked CSV, which `git diff` on data/processed already
    # catches; this function only watches ok/stale so the two checks do not overlap.
    after = {"arrears": {**OK_UNCHANGED["arrears"], "latest_month": "2026-08"}}
    assert not refresh_commit.status_flags_changed(OK_UNCHANGED, after)


def test_ok_flip_counts_as_changed() -> None:
    after = {"arrears": {**OK_UNCHANGED["arrears"], "ok": False, "error": "site down"}}
    assert refresh_commit.status_flags_changed(OK_UNCHANGED, after)


def test_stale_flip_counts_as_changed() -> None:
    after = {"arrears": {**OK_UNCHANGED["arrears"], "stale": True}}
    assert refresh_commit.status_flags_changed(OK_UNCHANGED, after)


def test_new_source_counts_as_changed() -> None:
    before: dict[str, object] = {}
    assert refresh_commit.status_flags_changed(before, OK_UNCHANGED)


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert refresh_commit._load(tmp_path / "missing.json") == {}


def test_load_empty_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    assert refresh_commit._load(path) == {}


def test_main_exits_0_and_prints_changed_when_a_flag_flips(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps(OK_UNCHANGED), encoding="utf-8")
    after_path.write_text(
        json.dumps({"arrears": {**OK_UNCHANGED["arrears"], "stale": True}}), encoding="utf-8"
    )
    code = refresh_commit.main(["--before", str(before_path), "--after", str(after_path)])
    assert code == 0
    assert "changed" in capsys.readouterr().out


def test_main_exits_1_and_prints_unchanged_when_nothing_flips(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps(OK_UNCHANGED), encoding="utf-8")
    after_path.write_text(json.dumps(OK_UNCHANGED), encoding="utf-8")
    code = refresh_commit.main(["--before", str(before_path), "--after", str(after_path)])
    assert code == 1
    assert "unchanged" in capsys.readouterr().out


def test_main_treats_a_missing_before_file_as_the_first_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    after_path = tmp_path / "after.json"
    after_path.write_text(json.dumps(OK_UNCHANGED), encoding="utf-8")
    code = refresh_commit.main(
        ["--before", str(tmp_path / "missing.json"), "--after", str(after_path)]
    )
    assert code == 0
    assert "changed" in capsys.readouterr().out
