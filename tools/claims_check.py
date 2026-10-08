"""Check that every number in the docs traces to a generated file.

Usage: python tools/claims_check.py [--claims CLAIMS.md] [--root DIR] [PATH ...]

It runs two checks.

1. Every claim in CLAIMS.md matches its source. CLAIMS.md holds a Markdown table
   with at least the columns Value, Source and Command. For example:

       | Claim | Value | Source | Command |
       |---|---|---|---|
       | Test AUC | 0.58 (0.55 to 0.61) | `reports/metrics.json#auc` | `make eval` |

   Source is a path relative to --root (default: the folder that holds CLAIMS.md).
   For a JSON file, an optional `#dotted.key` picks one value or one object inside it.
   Every number in the Value cell must equal some number in that source after
   rounding to the same number of decimal places. A value like "58%" also matches
   a source value of 0.58.

2. Every number in the Markdown files given as PATH appears in a CLAIMS.md Value
   cell. These numbers are not treated as claims and are skipped:
   - numbers inside code, link targets, HTML comments and front matter
   - years from 1900 to 2099, and ISO dates
   - whole numbers from 0 to 10 without a percent sign (counts like "three steps")
   - numbers glued to letters on the left, such as v1.0, F1, p95, hit@5 or top-20
   - version strings such as 3.11.2, and list markers such as "1."
   - any line that contains the comment <!-- not-a-claim -->

Exit code 0 means every check passed. Exit code 1 means at least one failed.
Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from _markdown import iter_markdown_files, prose_lines, strip_inline_code, strip_link_targets

SKIP_MARKER = "<!-- not-a-claim -->"
NUMBER_RE = re.compile(
    r"(?<![\w.@#/:])(?<![A-Za-z]-)"  # not glued to a word, path, version or "top-"
    r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)"
    r"(?!@|\.\d|[:/]\d|\d)"  # not the start of a version, time or path
)
SOURCE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s")
FOOTNOTE_RE = re.compile(r"\[\^[^\]]*\]")
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Number:
    """A number as written in the docs."""

    text: str
    value: Decimal
    decimals: int
    percent: bool

    def forms(self) -> set[Decimal]:
        """Values this number may stand for. "58%" may mean 58 or 0.58."""
        out = {self.value}
        if self.percent:
            out.add(self.value / 100)
        return {v.normalize() for v in out}


@dataclass
class Claim:
    line: int
    value_cell: str
    source: str
    command: str


def parse_numbers(text: str) -> list[Number]:
    """Find every number in a piece of text, with no filtering."""
    found = []
    for m in NUMBER_RE.finditer(text):
        whole, frac, pct = m.group(1), m.group(2) or "", m.group(3)
        value = Decimal(whole.replace(",", "") + frac)
        found.append(Number(m.group(0), value, max(len(frac) - 1, 0), bool(pct)))
    return found


def is_claim_like(num: Number) -> bool:
    """False for years and small counts, which are not treated as claims."""
    if num.percent or num.decimals:
        return True
    if len(num.text) == 4 and 1900 <= num.value <= 2099:
        return False
    return num.value > 10


def prose_numbers(text: str) -> list[tuple[int, Number]]:
    """Claim-like numbers in the prose of one Markdown file, with line numbers."""
    raw_lines = text.splitlines()
    out: list[tuple[int, Number]] = []
    for n, line in prose_lines(text):
        if SKIP_MARKER in raw_lines[n - 1]:
            continue
        line = strip_link_targets(strip_inline_code(line))
        line = FOOTNOTE_RE.sub(" ", HTML_TAG_RE.sub(" ", line))
        line = LIST_MARKER_RE.sub(" ", ISO_DATE_RE.sub(" ", line))
        out.extend((n, num) for num in parse_numbers(line) if is_claim_like(num))
    return out


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def parse_claims(text: str) -> tuple[list[Claim], list[str]]:
    """Read every claims table in CLAIMS.md. Return the claims and any format errors."""
    claims: list[Claim] = []
    errors: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        is_table = (
            lines[i].lstrip().startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1])
        )
        if not is_table:
            i += 1
            continue
        header = [h.lower().strip("`* ") for h in split_row(lines[i])]
        start = i
        i += 2
        rows = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            rows.append((i + 1, split_row(lines[i])))
            i += 1
        if "value" not in header and "source" not in header:
            continue  # some other table, not a claims table
        missing = [c for c in ("value", "source", "command") if c not in header]
        if missing:
            errors.append(f"line {start + 1}: claims table has no column(s): {', '.join(missing)}")
            continue
        v, s, c = (header.index(k) for k in ("value", "source", "command"))
        for n, cells in rows:
            cells += [""] * (len(header) - len(cells))
            claims.append(Claim(n, cells[v], cells[s].strip("` "), cells[c].strip("` ")))
    return claims, errors


def _json_numbers(node: Any) -> list[Decimal]:
    if isinstance(node, bool):
        return []
    if isinstance(node, int | float):
        return [Decimal(repr(node))]
    if isinstance(node, dict):
        return [x for v in node.values() for x in _json_numbers(v)]
    if isinstance(node, list):
        return [x for v in node for x in _json_numbers(v)]
    return []


def source_numbers(root: Path, source: str) -> list[Decimal]:
    """All numbers in a source file, or under one key of a JSON file.

    Raises ValueError with a readable message if the source cannot be read.
    """
    path_part, _, key = source.partition("#")
    path = root / path_part
    if not path.is_file():
        raise ValueError(f"source file not found: {path_part}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        node: Any = json.loads(text)
        for part in [p for p in key.split(".") if p]:
            if isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            elif isinstance(node, dict) and part in node:
                node = node[part]
            else:
                raise ValueError(f"key '{key}' not found in {path_part}")
        return _json_numbers(node)
    if key:
        raise ValueError(f"a #key only works for JSON sources: {source}")
    out = []
    for m in SOURCE_NUMBER_RE.finditer(text):
        try:
            out.append(Decimal(m.group(0)))
        except InvalidOperation:  # pragma: no cover - the regex only finds valid numbers
            pass
    return out


def matches(num: Number, source_value: Decimal) -> bool:
    """True if the source value, rounded like the written number, equals it."""
    step = Decimal(1).scaleb(-num.decimals)
    candidates = [abs(source_value)]
    if num.percent:
        candidates.append(abs(source_value) * 100)
    for x in candidates:
        for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN):
            if x.quantize(step, rounding=mode) == num.value:
                return True
    return False


def check_claims(claims: list[Claim], root: Path) -> list[str]:
    errors = []
    for claim in claims:
        where = f"CLAIMS.md line {claim.line}"
        if not claim.source or not claim.command:
            errors.append(f"{where}: every claim needs a Source and a Command")
            continue
        nums = parse_numbers(claim.value_cell)
        if not nums:
            errors.append(f"{where}: no number in Value cell '{claim.value_cell}'")
            continue
        try:
            values = source_numbers(root, claim.source)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{where}: {exc}")
            continue
        for num in nums:
            if not any(matches(num, x) for x in values):
                errors.append(f"{where}: {num.text} not found in {claim.source}")
    return errors


def check_coverage(paths: list[Path], claims: list[Claim], claims_path: Path) -> list[str]:
    claimed: set[Decimal] = set()
    for claim in claims:
        for num in parse_numbers(claim.value_cell):
            claimed |= num.forms()
    errors = []
    for path in paths:
        if path.resolve() == claims_path.resolve():
            continue
        for n, num in prose_numbers(path.read_text(encoding="utf-8")):
            if not num.forms() & claimed:
                errors.append(f"{path}:{n}: {num.text} is not in CLAIMS.md")
    return errors


def run(claims_path: Path, root: Path | None, paths: list[str]) -> list[str]:
    if not claims_path.is_file():
        return [f"{claims_path} not found"]
    claims, errors = parse_claims(claims_path.read_text(encoding="utf-8"))
    errors = [f"{claims_path}: {e}" for e in errors]
    errors += check_claims(claims, root or claims_path.parent)
    errors += check_coverage(list(iter_markdown_files(paths)), claims, claims_path)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="Markdown files or folders to scan")
    parser.add_argument("--claims", default="CLAIMS.md", type=Path)
    parser.add_argument(
        "--root", type=Path, default=None, help="folder that source paths are relative to"
    )
    args = parser.parse_args(argv)
    errors = run(args.claims, args.root, args.paths)
    for e in errors:
        print(e)
    print(f"claims check: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
