# 0001: Refresh from live sources and label stale data

Date: 2026-10-07. Status: accepted. The first consequence (what the CBA archive keeps) is partly replaced by [ADR 0006](0006-cba-numbers-only.md): the archive now keeps each file's numbers, not the file.

## Context

The project should not go out of date. It reads three public sources: the Bank of
Canada Valet API for the 5-year mortgage rate, the Statistics Canada Web Data Service
for unemployment by province, and the Canadian Bankers Association (CBA) spreadsheet of
mortgages in arrears. All three are free and need no key.

Three facts shape the design:

- The CBA posts one spreadsheet a month and removes the old one. The May 2026 file was
  already gone by October 2026. Each file holds the full history since January 1995.
- The CBA site refuses requests with a custom User-Agent string that contains a URL, and
  serves Python's default one.
- A scheduled GitHub Actions run that fails sends an email. A source that changes its
  site would fail every week until someone fixes it.

## Options

1. Download the data once and commit it. Simple, but the project goes stale.
2. Refresh on a schedule and fail the run when a source fails. Loud, but it emails
   every week until fixed.
3. Refresh on a schedule, keep the last good file when a source fails, and record the
   failure in `data/status.json`. The run passes and shows a warning.

## Decision

Option 3. Anything that shows results reads `data/status.json` and labels a stale
source as stale, so a failure is visible to readers without failing the run.
`--strict` exits 1 for local use.

A source also counts as stale when its newest month is too old, even if the pull
worked: more than 2 months for the rate, 3 for unemployment, and 5 for arrears.

## Consequences

- Every CBA file is kept in `data/raw/cba/`, named by the month it reports on. This is
  the only way to have the history of what the CBA said in a given month, which the
  forecast record needs.
- A broken source shows up as a warning on the Actions run and as a stale label, not
  as an email. Someone has to look.
- The repo grows by one small CBA file (well under a megabyte) a month.
- Check the CBA's terms of use before the repo is public, since it republishes their
  files.
