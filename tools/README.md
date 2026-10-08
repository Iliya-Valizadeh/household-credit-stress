# tools

Checks that keep this repo's docs honest and easy to read. `make check-docs` runs all
of them, and CI runs the same target.

These files are copied from the `ds-project-standard` template. Do not edit them here.
Change them in the template, then run `copier update` in this repo.

| Tool | What it checks |
|---|---|
| `ai_signs_check.py` | Common signs of AI writing: puffery words, em dashes, bold lead-ins, title-case headings |
| `claims_check.py` | Every number in `CLAIMS.md` matches its source file, and every number in the docs is listed in `CLAIMS.md` |
| `readability_check.py` | Reading grade of the "In plain words" section and notes, reading grade of the rest, and glossary links on first use |
| `links_check.py` | Links between local files and to sections inside them, with no network access |
| `lychee.toml` | Settings for lychee, which checks links to other websites in CI |
| `readme_sections.py` | Checks the README section order and keeps the repo map table up to date |

Add `--help` to any Python tool to see its options.
