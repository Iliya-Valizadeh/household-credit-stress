"""Tests for the test-run log (docs/eval_plan.md, "Backtest design": "Each test run
adds a row to an append-only log in `reports/`, so the number of attempts is
visible."). Checks: the log is append-only and grows by exactly one row per call, even
for a call identical to the one before it; the header is written once; a run with no
score yet still gets a row; `current_git_hash` falls back to "unknown" instead of
raising when git is unavailable. No test touches the network."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from household_credit_stress import evaluate, evaluate_scenario, run_log

WHEN = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.UTC)


def test_append_run_writes_header_and_row(tmp_path: Path) -> None:
    run_log.append_run(tmp_path, "arx", "0.1.0", "abc123", 0.03, utc_time=WHEN)

    written = pd.read_csv(tmp_path / run_log.FILE_NAME, dtype=str)
    assert list(written.columns) == run_log.COLUMNS
    assert written.loc[0, "model"] == "arx"
    assert written.loc[0, "version"] == "0.1.0"
    assert written.loc[0, "git_hash"] == "abc123"
    assert written.loc[0, "utc_time"] == "2026-10-08T12:00:00+00:00"
    assert written.loc[0, "headline_gap_bp"] == "0.03"


def test_append_run_grows_by_one_row_each_call_even_when_identical(tmp_path: Path) -> None:
    run_log.append_run(tmp_path, "arx", "0.1.0", "abc123", 0.03, utc_time=WHEN)
    before = (tmp_path / run_log.FILE_NAME).read_text(encoding="utf-8")

    run_log.append_run(tmp_path, "arx", "0.1.0", "abc123", 0.03, utc_time=WHEN)
    after = (tmp_path / run_log.FILE_NAME).read_text(encoding="utf-8")

    assert after.startswith(before)  # the file only ever grows
    assert after != before
    written = pd.read_csv(tmp_path / run_log.FILE_NAME)
    assert len(written) == 2


def test_append_run_records_a_run_with_no_score_yet(tmp_path: Path) -> None:
    run_log.append_run(tmp_path, "pooled_arx", "0.1.0", "abc123", None, utc_time=WHEN)

    written = pd.read_csv(tmp_path / run_log.FILE_NAME)
    assert written["headline_gap_bp"].isna().all()


def test_current_git_hash_falls_back_to_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("no git")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert run_log.current_git_hash(tmp_path) == "unknown"


def test_current_git_hash_returns_the_checked_out_commit() -> None:
    repo_dir = Path(__file__).resolve().parents[1]
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert run_log.current_git_hash(repo_dir) == expected


# headline_gap_bp extractors, one per evaluation script ---------------------------------


def test_evaluate_headline_gap_bp_reads_the_headline_horizon() -> None:
    metrics = {"model": {"h1": {"baseline": "ar1", "gap_bp": {"value": 0.03}}}}
    assert evaluate.headline_gap_bp(metrics) == 0.03


def test_evaluate_headline_gap_bp_is_none_without_enough_test_data() -> None:
    metrics = {"model": {"h1": None}}
    assert evaluate.headline_gap_bp(metrics) is None


def test_evaluate_scenario_headline_gap_bp_reads_the_nearer_check_horizon() -> None:
    metrics = {"check": {"h12": {"best_baseline": "ar1", "gap_bp": {"value": 1.25}}}}
    assert evaluate_scenario.headline_gap_bp(metrics) == 1.25


def test_evaluate_scenario_headline_gap_bp_is_none_without_enough_test_data() -> None:
    metrics = {"check": {"h12": None}}
    assert evaluate_scenario.headline_gap_bp(metrics) is None
