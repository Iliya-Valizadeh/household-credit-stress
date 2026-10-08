"""Flag patterns listed on https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing.

Usage: python tools/ai_signs_check.py PATH [PATH ...]

PATH can be a file or a folder (folders are searched for Markdown files).
Exit code 0 means zero flags. Exit code 1 means at least one flag.

Code blocks, inline code, front matter, HTML comments and link targets are skipped,
because they are not prose. Only the mechanical signs can be caught this way.
Rule-of-three lists, shallow analysis and puffery in new words still need a human read.

Adapted from the earlier `_portfolio_upgrade/ai_signs_check.py`. The word list and
patterns are the same; this version also skips code and URLs and accepts folders.
It also fixes two patterns ("overall," and "certainly!") that could never match before,
because a word boundary was required right after the punctuation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _markdown import (
    heading,
    iter_markdown_files,
    prose_lines,
    strip_inline_code,
    strip_link_targets,
)

# "High density of AI vocabulary words" (all eras), plus copula dodges and others.
VOCAB = r"""additionally|align(?:s|ed)? with|boasts?|bolstered|crucial|deep dive|delve[sd]?|
emphasi[sz]ing|enduring|enhanc(?:e|es|ed|ing)|foster(?:s|ed|ing)?|garner(?:s|ed)?|
highlight(?:s|ed|ing)?|interplay|intricate|intricacies|landscape|meticulous(?:ly)?|pivotal|
robust|showcas(?:e|es|ed|ing)|tapestry|testament|underscor(?:e|es|ed|ing)|valuable|vibrant|
seamless(?:ly)?|cutting-edge|leverag(?:e|es|ed|ing)|comprehensive|empower(?:s|ed|ing)?|
groundbreaking|renowned|profound|commitment to|nestled|in the heart of|diverse array|
utili[sz](?:e|es|ed|ing)|in order to|the fact that"""

PATTERNS: dict[str, str] = {
    "AI vocabulary": r"\b(?:" + re.sub(r"\s+", "", VOCAB) + r")\b",
    "key as adjective": (
        r"\bkey (?:role|factor|finding|insight|takeaway|point|feature|metric|moment|driver)s?\b"
    ),
    "copula avoidance": (
        r"\b(?:serves as|stands as|functions as|acts as|marks a|represents a|refers to)\b"
    ),
    "negative parallelism": r"\bnot (?:just|only|merely)\b|\bit'?s not\b[^.]*\bit'?s\b"
    r"|\bno [a-z]+, no [a-z]+\b",
    "superficial -ing tail": (
        r",\s(?:highlighting|underscoring|emphasi[sz]ing|ensuring|reflecting|symboli[sz]ing"
        r"|contributing to|cultivating|fostering|encompassing|showcasing)\b"
    ),
    "weasel attribution": (
        r"\b(?:experts (?:say|argue)|observers|some critics|industry reports|several sources)\b"
    ),
    "didactic / summary": (
        r"\b(?:it'?s (?:important|crucial|critical) to (?:note|remember)|worth noting"
        r"|in summary|in conclusion|overall,)"
    ),
    "challenges formula": (
        r"\b(?:despite (?:its|these) (?:challenges|limitations)|future (?:outlook|prospects))\b"
    ),
    "chatbot address": r"\b(?:i hope this helps|let me know|certainly!|here is a|would you like)",
    "vague association": r"\b(?:in connection with|associated with|connected to)\b",
    "em dash": "—",
    "curly quote": "[“”‘’]",
    "emoji": "[\U0001f300-\U0001faff☀-➿]",
    "thematic break": r"^(?:---|\*\*\*|___)\s*$",
    "inline-header list item": r"^\s*(?:[-*]|\d+\.)\s+\*\*[^*]+\*\*\s*:?",
    "bold lead-in paragraph": r"^\*\*[^*]{2,80}\*\*",
}
COMPILED = {name: re.compile(pat, re.I | re.M) for name, pat in PATTERNS.items()}
SMALL_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "in",
    "on",
    "to",
    "for",
    "by",
    "vs",
    "at",
    "with",
}

Flag = tuple[int, str, str]


def title_case_heading(line: str) -> bool:
    """True if a heading capitalises two or more of its non-first, non-small words
    and all of them are capitalised (for example "## Model Training Results")."""
    h = heading(line)
    if not h:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", strip_inline_code(h[1]))
    long_words = [w for w in words[1:] if w.lower() not in SMALL_WORDS]
    return len(long_words) >= 2 and all(w[0].isupper() for w in long_words)


def check_text(text: str) -> list[Flag]:
    """Return (line number, pattern name, matched text) for every flag in the text."""
    hits: list[Flag] = []
    for n, raw in prose_lines(text):
        line = strip_link_targets(strip_inline_code(raw))
        for name, pat in COMPILED.items():
            for m in pat.finditer(line):
                hits.append((n, name, m.group(0).strip()))
        if title_case_heading(raw):
            hits.append((n, "title-case heading", raw.strip()))
    return hits


def check(path: Path) -> tuple[list[Flag], int]:
    """Return the flags for one file and its count of bold spans (for information)."""
    text = path.read_text(encoding="utf-8")
    bold = len(re.findall(r"\*\*[^*]+\*\*", text))
    return check_text(text), bold


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    total = 0
    for p in iter_markdown_files(args):
        hits, bold = check(p)
        total += len(hits)
        print(f"== {p}: {len(hits)} flags, {bold} bold spans")
        for n, name, text in hits:
            print(f"  {n:4d} {name}: {text[:90]}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
