"""The test-run log (docs/eval_plan.md, "Backtest design": "The test period is run
once per model version. Each test run adds a row to an append-only log in `reports/`,
so the number of attempts is visible.").

`evaluate.py` and `evaluate_scenario.py` each call `append_run` once per run, after
writing their own report files, with that script's headline MAE gap (the model minus
its best baseline, at the horizon each script treats as the headline one). The file
only ever grows: every call writes a new row, including one identical to the row
before it, because the point is to show how many times the test period was run, not to
deduplicate attempts. Runs before this log existed are visible only in the git history
of `reports/*.json` (docs/eval_plan.md, "Changes to this plan").
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pandas as pd

FILE_NAME = "test_runs.csv"
COLUMNS: list[str] = ["model", "version", "git_hash", "utc_time", "headline_gap_bp"]


def current_git_hash(repo_dir: Path = Path(".")) -> str:
    """The full hash of the commit checked out in `repo_dir`.

    This runs `git` locally; it is not a network call, so it is fine for `evaluate.py`
    and `evaluate_scenario.py` to use, but it is kept out of any test (BRIEF.md: tests
    never touch the network, and this also depends on the machine's git state). Returns
    "unknown" if git is missing or `repo_dir` is not a git checkout, so a run never
    fails just because the hash could not be read.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def append_run(
    reports_dir: Path,
    model: str,
    version: str,
    git_hash: str,
    headline_gap_bp: float | None,
    utc_time: dt.datetime | None = None,
) -> None:
    """Append one row to `reports/test_runs.csv`, writing the header first if the file
    is new. Never reads the file back in to rewrite it, so a row already on disk can
    only be added to, never changed. `headline_gap_bp` is `None` when there was not yet
    enough test-period data to score the model; the row is still written, so a run that
    produced no score is also visible."""
    when = utc_time or dt.datetime.now(dt.UTC)
    row = {
        "model": model,
        "version": version,
        "git_hash": git_hash,
        "utc_time": when.isoformat(),
        "headline_gap_bp": headline_gap_bp,
    }
    path = reports_dir / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    frame = pd.DataFrame([row], columns=COLUMNS)
    text = frame.to_csv(index=False, header=is_new)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(text)
