# Claims

Every number in this repo's Markdown files has a row here. Each row says where the
number comes from and which command makes that file. `make check-docs` fails if a
number in the docs has no row, or if a row does not match its source.

Small whole numbers (0 to 10), years, dates and version numbers are skipped. To skip
one line by hand, add the comment `<!-- not-a-claim -->` to it.

| Claim | Value | Source | Command |
|---|---|---|---|

Example row, for the format only:
`| Test AUC | 0.58 (0.55 to 0.61) | reports/metrics.json#auc | make eval |`
