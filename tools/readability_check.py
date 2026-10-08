"""Check that prose is easy to read, and that glossary terms are linked on first use.

Usage: python tools/readability_check.py [options] PATH [PATH ...]

Grade limits use the Flesch-Kincaid grade level from the textstat package.
- A section headed "In plain words" must score at or below --plain-max (default 9).
- A file that matches a --plain-glob pattern (default: notes/*.md and */notes/*.md)
  must score at or below --plain-max as a whole.
- All other prose in a file must score at or below --max (default 12).
Text with fewer than --min-words words (default 20) is too short to score, so it is
reported and skipped.

Before scoring, the check removes code, tables, headings, HTML, images and link
targets. Each list item and each paragraph counts as its own sentence.

With --glossary docs/glossary.md, each term in the glossary (one heading per term)
must be a link to the glossary the first time it appears in each file. A heading like
"Area under the curve (AUC)" defines two terms: the full name and "AUC".

Exit code 0 means every check passed. Exit code 1 means at least one failed.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import textstat

from _markdown import (
    INLINE_LINK_RE,
    heading,
    iter_markdown_files,
    prose_lines,
    strip_inline_code,
    strip_link_targets,
)

PLAIN_HEADING = "in plain words"
DEFAULT_PLAIN_GLOBS = ["notes/*.md", "*/notes/*.md"]
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass
class Score:
    label: str
    grade: float | None  # None when the text is too short to score
    words: int
    limit: float

    @property
    def ok(self) -> bool:
        return self.grade is None or self.grade <= self.limit


def clean_prose(lines: list[str]) -> str:
    """Turn Markdown lines into plain sentences for scoring."""
    sentences: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            sentences.append(" ".join(para))
            para.clear()

    for raw in lines:
        if not raw.strip() or heading(raw) or raw.lstrip().startswith("|"):
            flush()
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw)  # images
        line = strip_link_targets(strip_inline_code(line, "code"))
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", line)
        if LIST_ITEM_RE.match(line):
            flush()
            line = LIST_ITEM_RE.sub("", line)
        if line.startswith(">"):
            line = line.lstrip("> ")
        if line.strip():
            para.append(line.strip())
    flush()
    out = []
    for s in sentences:
        s = re.sub(r"\s+", " ", s).strip()
        if s and s[-1] not in ".!?:;":
            s += "."
        if s:
            out.append(s)
    return " ".join(out)


def score(text: str, label: str, limit: float, min_words: int) -> Score:
    words = textstat.lexicon_count(text)
    if words < min_words:
        return Score(label, None, words, limit)
    return Score(label, float(textstat.flesch_kincaid_grade(text)), words, limit)


def split_sections(text: str) -> tuple[list[str], list[str]]:
    """Split a file into lines inside "In plain words" sections and all other lines."""
    plain: list[str] = []
    rest: list[str] = []
    plain_level: int | None = None
    for _, line in prose_lines(text):
        h = heading(line)
        if h:
            level, title = h
            if plain_level is not None and level <= plain_level:
                plain_level = None
            if re.sub(r"[^a-z ]", "", title.lower()).strip() == PLAIN_HEADING:
                plain_level = level
        (plain if plain_level is not None else rest).append(line)
    return plain, rest


def check_file(
    path: Path, plain_max: float, rest_max: float, min_words: int, plain_globs: list[str]
) -> list[Score]:
    text = path.read_text(encoding="utf-8")
    posix = path.as_posix()
    if any(fnmatch(posix, g) or fnmatch(path.name, g) for g in plain_globs):
        lines = [line for _, line in prose_lines(text)]
        return [score(clean_prose(lines), "whole file (plain)", plain_max, min_words)]
    plain, rest = split_sections(text)
    scores = []
    if plain:
        scores.append(score(clean_prose(plain), "In plain words", plain_max, min_words))
    scores.append(score(clean_prose(rest), "rest of file", rest_max, min_words))
    return scores


def glossary_terms(glossary: Path) -> list[str]:
    """Terms are the headings (level 2 or lower) of the glossary file."""
    terms: list[str] = []
    for _, line in prose_lines(glossary.read_text(encoding="utf-8")):
        h = heading(line)
        if not h or h[0] < 2:
            continue
        title = strip_inline_code(h[1], r"\2").strip()
        m = re.match(r"^(.*?)\s*\(([^)]+)\)$", title)
        terms.extend([m.group(1), m.group(2)] if m else [title])
    return [t for t in terms if t]


def term_regex(term: str) -> re.Pattern[str]:
    flags = 0 if term.isupper() else re.I  # "AUC" is case-sensitive, "baseline" is not
    return re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", flags)


def check_glossary_links(path: Path, terms: list[str]) -> list[str]:
    """Return one message per term whose first use in the file is not a glossary link."""
    problems = []
    lines = [
        (n, strip_inline_code(line, lambda m: " " * len(m.group(0))))
        for n, line in prose_lines(path.read_text(encoding="utf-8"))
        if not heading(line)
    ]
    for term in terms:
        pattern = term_regex(term)
        for n, line in lines:
            linked = [
                (m.start(2), m.end(2))
                for m in INLINE_LINK_RE.finditer(line)
                if "glossary" in m.group(3).lower()
            ]
            targets = [(m.start(3), m.end(3)) for m in INLINE_LINK_RE.finditer(line)]
            hits = [
                m for m in pattern.finditer(line) if not any(a <= m.start() < b for a, b in targets)
            ]
            if not hits:
                continue
            first = hits[0].start()
            if not any(a <= first < b for a, b in linked):
                problems.append(f"{path}:{n}: first use of '{term}' is not linked to the glossary")
            break
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="Markdown files or folders")
    parser.add_argument("--plain-max", type=float, default=9.0)
    parser.add_argument("--max", type=float, default=12.0, dest="rest_max")
    parser.add_argument("--min-words", type=int, default=20)
    parser.add_argument(
        "--plain-glob",
        action="append",
        dest="plain_globs",
        help="files that must be plain as a whole (repeatable)",
    )
    parser.add_argument("--glossary", type=Path, default=None)
    args = parser.parse_args(argv)
    plain_globs = args.plain_globs or DEFAULT_PLAIN_GLOBS

    terms = glossary_terms(args.glossary) if args.glossary else []
    failures = 0
    for path in iter_markdown_files(args.paths):
        for s in check_file(path, args.plain_max, args.rest_max, args.min_words, plain_globs):
            if s.grade is None:
                print(f"{path}: {s.label}: skipped, only {s.words} words")
                continue
            status = "ok" if s.ok else "FAIL"
            print(f"{path}: {s.label}: grade {s.grade:.1f} (limit {s.limit:g}) {status}")
            failures += not s.ok
        if terms and args.glossary.resolve() != path.resolve():
            for problem in check_glossary_links(path, terms):
                print(problem)
                failures += 1
    print(f"readability check: {failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
