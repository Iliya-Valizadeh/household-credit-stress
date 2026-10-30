# 0006: Keep only the numbers from CBA files, not the spreadsheets

Date: 2026-10-20. Status: accepted. Replaces the last bullet of the decision in
[ADR 0005](0005-scheduled-run-never-fails.md) and the first consequence of
[ADR 0001](0001-refresh-and-stale-data.md).

## Context

The Canadian Bankers Association (CBA) posts one spreadsheet of mortgage arrears each
month and takes the old one down. The repo keeps a copy of each month's file, because
the live forecast record needs to know what the CBA said in a given month (ADR 0001).

The CBA's [Terms of Use](https://cba.ca/article/terms-of-use) let anyone copy
"Information" from its site if it is copied accurately, kept in context and credited
to the CBA. They do not say whether a copy of the spreadsheet file itself may be
shared. Until now the repo held one such file, `data/raw/cba/2026-07.xlsx`. The repo
has never been pushed, so no copy of it has left this computer.

## Options

- Keep the spreadsheets and ask the CBA for permission. This keeps the files exactly
  as published, but the repo cannot be public until the CBA answers.
- Keep only the numbers. Each month's file becomes a small CSV with the month, the
  region, the number of mortgages and the number in arrears, under a header that names
  the CBA, the table title, the page address and the time it was downloaded. This is
  the kind of accurate, credited copying the terms allow. The cost: the CBA's layout,
  notes and own percentage column are not kept.
- Keep no archive. This removes the question, but the forecast record could no longer
  show what the CBA reported in a given month.

## Decision

Keep only the numbers. I chose this option on 2026-10-20.

- `sources/cba.py` reads a downloaded spreadsheet in memory and writes
  `data/raw/cba/YYYY-MM.csv`. The spreadsheet is never written to disk. An existing CSV
  is never overwritten, so the first copy of each month's numbers is the one kept.
- `python -m household_credit_stress.sources.cba FILE.xlsx --retrieved-at WHEN`
  converts a spreadsheet that is already on disk. It made `data/raw/cba/2026-07.csv`
  from the old spreadsheet. The "Retrieved" time in that file's header is the
  `checked_at` time that `data/status.json` recorded for the first data pull.
- `forecast.py` treats a target month as reported once `data/raw/cba/YYYY-MM.csv`
  exists. This is the same rule as before, with a new file type.
- `.gitignore` excludes `data/raw/cba/*.xlsx`, and the refresh workflow still leaves
  that pattern out of `git add`, as a second guard.
- The old spreadsheet is moved out of the repo, to my private portfolio folder.
  Nothing is deleted.
- Because the repo has never been pushed, its local history is rewritten once, before
  the first push, so that no commit holds the spreadsheet. The commit that first added
  the spreadsheet now adds the CSV instead. I approved this one rewrite on
  2026-10-20.

## Consequences

- Every number the repo uses is unchanged. The CSV holds exactly the rows that the
  spreadsheet gave, and `data/processed/arrears.csv` and `reports/metrics.json` are the
  same before and after the change. `tests/test_sources.py` checks that the CSV reads
  back to the same rows as the parsed spreadsheet.
- The CSV in the rewritten first-data commit was made later, by the converter added in
  this change. That commit's own code still saved spreadsheets; only its data changed.
- Commit hashes from before the rewrite no longer exist in the repo. Docs that cited
  them now cite the new hashes, and the full old-to-new map is committed.
- If the CBA changes its layout, the parser fails and the source is marked stale, as
  before (ADR 0001). The CSV format does not depend on the layout.

## The history rewrite (2026-10-20)

The rewrite was done once, on this computer, before the repo was ever pushed. It used
`git filter-repo` to drop every `data/raw/cba/*.xlsx` file from every commit and to add
`data/raw/cba/2026-07.csv` to the commit that first added the spreadsheet.

- What changed: the hash of every commit from the first data pull on. The commit that
  added the spreadsheet was `6a2c65c` and is now `4b34816`. The evaluation plan commit
  was `bc8acfd` and is now `4c4e1c7`. The full map, as written by `git filter-repo`, is
  in [docs/history_rewrite_map.txt](../history_rewrite_map.txt).
- What did not change: any other file in any commit, and the message, author, author
  date, committer date and order of every commit. This was checked against a copy of
  the old history. For each rewritten commit, `git diff` between the old and the new
  commit lists only `data/raw/cba/2026-07.xlsx` and `data/raw/cba/2026-07.csv`. The
  log of messages, authors and dates is the same, line for line.
- The backup: a `git bundle` of the whole history before the rewrite, and the
  spreadsheet itself, are kept in my private portfolio folder, outside the repo.
  The bundle was made just before the two commits that start this change, so it does
  not hold their old versions. Their files were the same before and after the rewrite,
  because neither old version held a spreadsheet.
- Hashes cited in the docs now point to the new commits. One old hash stays on
  purpose: `reports/test_runs.csv` is append-only (docs/eval_plan.md), so its first
  row keeps the hash it recorded, `75ea840`. The map gives the new hash, `a9a1a65`.
