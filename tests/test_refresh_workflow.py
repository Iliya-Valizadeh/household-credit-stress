"""Checks that the scheduled workflow cannot fail the run or publish the CBA files.

`.github/workflows/refresh.yml` is the only scheduled workflow, and a failed run emails
the owner (ADR 0005). These tests read the file as text, since the rules are about what
it says, not about running it.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "refresh.yml"


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_cba_spreadsheets_are_never_staged() -> None:
    add_lines = [line.strip() for line in text().splitlines() if line.strip().startswith("git add")]
    assert add_lines, "the workflow should stage files"
    assert all(":!data/raw/cba/*.xlsx" in line for line in add_lines)
    # The change check must not look at data/raw either.
    assert "data/raw ledger" not in text()


def test_pull_step_cannot_fail_the_run() -> None:
    block = text().split("- name: Pull the latest data")[1].split("- name:")[0]
    assert "continue-on-error: true" in block


def test_push_failure_is_a_warning_and_never_forced() -> None:
    assert "--force" not in text()
    tail = text().split("- name: Commit new data")[1]
    assert "::warning title=Push failed" in tail
    assert "git pull --rebase" in tail
    assert tail.rstrip().endswith("exit 0")
