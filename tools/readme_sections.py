"""Write and check the standard README sections.

Usage:
  python tools/readme_sections.py new --title NAME --one-line TEXT [--out README.md]
  python tools/readme_sections.py check README.md
  python tools/readme_sections.py repo-map README.md [--root DIR] [--check]

new       prints (or writes) a README skeleton with the nine sections in order.
          It will not overwrite an existing file unless --force is given.
check     fails if the README has no title and one-line summary, or if a required
          section is missing or out of order. Extra sections are allowed.
repo-map  rewrites the table between <!-- repo-map:start --> and <!-- repo-map:end -->
          from the folders and files that really exist. Descriptions already in the
          table are kept. With --check it only reports whether the table is out of date.

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _markdown import heading, prose_lines

# Required level-2 sections, in order (PORTFOLIO_PLAN.md section 3.1).
SECTIONS = [
    "In plain words",
    "Try it",
    "Result",
    "How I worked",
    "How it works",
    "What's weak",
    "Docs",
    "Repo map",
]

MAP_START = "<!-- repo-map:start -->"
MAP_END = "<!-- repo-map:end -->"
TODO = "TODO: describe"

# Default descriptions for common folders and files.
KNOWN = {
    ".github/": "CI workflows and GitHub settings",
    "data/": "Small data files, or scripts that download the data",
    "docs/": "Evaluation plan, decisions, glossary and the four kinds of docs",
    "examples/": "A project generated from this template, tested in CI",
    "notebooks/": "Exploration notebooks (not used to make the reported numbers)",
    "reports/": "Generated results, including metrics.json",
    "src/": "The package code",
    "template/": "The Copier template files",
    "tests/": "Unit and data tests",
    "tools/": "Checks for claims, readability, AI-writing signs and links",
    "CLAIMS.md": "Every number in the docs, with its source file and command",
    "Makefile": "One command for each step: setup, lint, test, eval, demo",
}
SKIP = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "build",
    "dist",
}
TOP_FILES = {"CLAIMS.md", "Makefile", "copier.yml", "STANDARD.md"}


def skeleton(title: str, one_line: str) -> str:
    """The README skeleton. Each TODO line says what the section must hold."""
    return f"""# {title}

{one_line}

## In plain words

TODO: three short sentences that a person with no technical background can follow.

## Try it

TODO: a live link if one exists. Otherwise three commands:

```bash
make setup
make demo
make all
```

## Result

TODO: one number with its interval, compared against a simple baseline.
Add one chart with a caption that says what to notice.

## How I worked

- Evaluation plan, written before any results: [docs/eval_plan.md](docs/eval_plan.md)
  (TODO: commit hash).
- Decisions: [docs/decisions/](docs/decisions/).
- Error analysis: TODO: link.

## How it works

```mermaid
flowchart LR
    A[Input] --> B[Model] --> C[Output]
```

TODO: five lines of text that explain the diagram.

## What's weak

TODO: the main weaknesses, ranked by how much each could change the result.
The full list is in [docs/whats_weak.md](docs/whats_weak.md).

## Docs

- Tutorial: [docs/tutorial.md](docs/tutorial.md)
- How-to guides: [docs/how-to/](docs/how-to/)
- Reference: [docs/reference.md](docs/reference.md)
- Explanation: [docs/explanation.md](docs/explanation.md)

## Repo map

{MAP_START}
{MAP_END}
"""


def check_readme(text: str) -> list[str]:
    """Return problems with the README's title, one-line summary and section order."""
    problems = []
    lines = [line for _, line in prose_lines(text)]
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    h = heading(lines[first]) if first is not None else None
    if first is None or h is None or h[0] != 1:
        problems.append("the first line must be the title, as a level-1 heading")
    else:
        rest = [line for line in lines[first + 1 :] if line.strip()]
        if not rest or heading(rest[0]):
            problems.append("the title must be followed by a one-line summary")
    found = [h[1].strip() for line in lines if (h := heading(line)) and h[0] == 2]
    norm = [s.lower().replace("’", "'") for s in found]
    position = -1
    for name in SECTIONS:
        if name.lower() not in norm:
            problems.append(f"missing section: ## {name}")
            continue
        idx = norm.index(name.lower())
        if idx < position:
            problems.append(f"section out of order: ## {name}")
        position = max(position, idx)
    return problems


def existing_descriptions(block: str) -> dict[str, str]:
    """Read descriptions from an existing repo-map table so hand edits survive."""
    out = {}
    for m in re.finditer(r"^\|\s*`?([^`|]+?)`?\s*\|\s*(.*?)\s*\|\s*$", block, re.M):
        name, desc = m.group(1).strip(), m.group(2).strip()
        if name.lower() not in {"path", "folder"} and not set(name) <= {"-", ":"}:
            out[name] = desc
    return out


def build_map(root: Path, old: dict[str, str]) -> str:
    entries = []
    for p in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if p.name in SKIP or p.name.endswith(".egg-info"):
            continue
        if p.is_dir() and (not p.name.startswith(".") or p.name == ".github"):
            entries.append(p.name + "/")
        elif p.is_file() and p.name in TOP_FILES:
            entries.append(p.name)
    rows = ["| Path | What it holds |", "|---|---|"]
    for name in entries:
        desc = old.get(name) or KNOWN.get(name) or TODO
        rows.append(f"| `{name}` | {desc} |")
    return "\n".join(rows)


def update_repo_map(text: str, root: Path) -> str:
    """Return the README text with a fresh repo-map table between the markers."""
    start, end = text.find(MAP_START), text.find(MAP_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"README needs the markers {MAP_START} and {MAP_END}")
    block = text[start + len(MAP_START) : end]
    table = build_map(root, existing_descriptions(block))
    return text[:start] + MAP_START + "\n" + table + "\n" + text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new", help="write a README skeleton")
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--one-line", required=True)
    p_new.add_argument("--out", type=Path)
    p_new.add_argument("--force", action="store_true")
    p_check = sub.add_parser("check", help="check the README sections")
    p_check.add_argument("readme", type=Path)
    p_map = sub.add_parser("repo-map", help="refresh the repo map table")
    p_map.add_argument("readme", type=Path)
    p_map.add_argument("--root", type=Path, default=None)
    p_map.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "new":
        text = skeleton(args.title, args.one_line)
        if args.out is None:
            sys.stdout.write(text)
        elif args.out.exists() and not args.force:
            print(f"{args.out} already exists; use --force to replace it")
            return 1
        else:
            args.out.write_text(text, encoding="utf-8", newline="\n")
        return 0

    text = args.readme.read_text(encoding="utf-8")
    if args.cmd == "check":
        problems = check_readme(text)
        for p in problems:
            print(f"{args.readme}: {p}")
        print(f"README check: {len(problems)} problem(s)")
        return 1 if problems else 0

    root = args.root or args.readme.parent
    try:
        new = update_repo_map(text, root)
    except ValueError as exc:
        print(f"{args.readme}: {exc}")
        return 1
    if args.check:
        todo = new[new.find(MAP_START) : new.find(MAP_END)].count(TODO)
        if new != text:
            print(f"{args.readme}: repo map is out of date; run without --check")
            return 1
        if todo:
            print(f"{args.readme}: repo map has {todo} row(s) still marked '{TODO}'")
            return 1
        print(f"{args.readme}: repo map is up to date")
        return 0
    args.readme.write_text(new, encoding="utf-8", newline="\n")
    print(f"{args.readme}: repo map updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
