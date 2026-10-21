# 0005: The weekly refresh never fails the run and never commits CBA files

Date: 2026-10-20. Status: accepted. The CBA part of the decision is partly replaced by [ADR 0006](0006-cba-numbers-only.md): only the numbers from each CBA file are kept, and they are committed.

## Context

`refresh.yml` is the only scheduled workflow. A failed run emails the owner, so a bug or a site change must not fail it week after week. Separately, whether the repo may archive the CBA spreadsheets is still an open question (see "Needs Iliya" in the portfolio status file).

## Decision

- The pull, forecast and export steps all use `continue-on-error`, and each prints a `::warning::` when it fails. `refresh.py` also catches any error that is not one source failing, prints a warning and exits 0. The old files stay and the data stays marked stale (ADR 0001). `--strict` still raises, for local use.
- The commit step prints a warning and exits 0 if the commit or the push fails. It tries one `git pull --rebase` and one more push, never a force-push. The next run tries again.
- The workflow stages `data/`, `ledger/` and `site/data/` but excludes `data/raw/cba/*.xlsx`. A new spreadsheet exists only in the runner's working tree, which is enough for the forecast step to grade outcomes in that same run.

## Consequences

If the forecast step fails in the week a new spreadsheet appears, that file is gone next week and the outcome stays ungraded as a late slot. Any CBA file already in git history stays there.
