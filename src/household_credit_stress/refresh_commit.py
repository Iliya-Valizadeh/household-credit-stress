"""Decides whether the weekly refresh workflow has anything worth committing.

`.github/workflows/refresh.yml` reruns `refresh.py` on a schedule, and `data/status.json`
changes on every run because its `checked_at` field is always new. Committing on every
run would bury real changes in noise, so the workflow only commits when a tracked data
file or ledger row actually changed (checked with `git diff`, outside this module) or
when an `ok` or `stale` field in `status.json` flips. That second case needs its own
check: a plain `git diff` on the file would also fire on `checked_at` and `error`, which
change on every run even when nothing a reader of the page needs a new commit for does
(ADR 0001, "Anything that shows results reads `data/status.json`").

Run with `python -m household_credit_stress.refresh_commit --before OLD.json --after
NEW.json`. Exits 0 and prints "changed" if an `ok` or `stale` field differs; exits 1 and
prints "unchanged" otherwise. The workflow's commit step reads this exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: The only fields a flip in matters for this decision. `checked_at`, `latest_month`
#: and `error` all change on a routine, uneventful run and are ignored.
WATCHED_FIELDS = ("ok", "stale")


def status_flags_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """True if any source's `ok` or `stale` field differs between the two snapshots.

    A source present in `after` but missing from `before` (the first run ever, or a
    newly added source) counts as changed, since there is nothing to compare it with.
    A source that disappeared from `after` is not inspected here; `git diff` catches
    that as a file change.
    """
    for source, after_entry in after.items():
        before_entry = before.get(source)
        if before_entry is None:
            return True
        for field in WATCHED_FIELDS:
            if before_entry.get(field) != after_entry.get(field):
                return True
    return False


def _load(path: Path) -> dict[str, Any]:
    """Reads a status.json snapshot. A missing or empty file counts as no sources seen
    yet, which is what `git show HEAD:data/status.json` gives on the very first run."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return dict(json.loads(text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args(argv)

    changed = status_flags_changed(_load(args.before), _load(args.after))
    print("changed" if changed else "unchanged")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
