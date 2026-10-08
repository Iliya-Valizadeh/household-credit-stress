"""Small Markdown helpers shared by the checks in this folder.

These are not a full Markdown parser. They handle the parts the checks need:
fenced code, front matter, HTML comments, inline code, links and headings.
Only the Python standard library is used, so each tool runs with plain `python`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

MARKDOWN_SUFFIXES = {".md", ".markdown"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# [text](target "title") and ![alt](target). Text may hold one level of brackets.
INLINE_LINK_RE = re.compile(
    r"(!?)\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*(<[^>]*>|[^)\s]*)(?:\s+[\"'(][^)]*)?\)"
)
REF_DEF_RE = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]*>|\S+)")
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
BARE_URL_RE = re.compile(r"https?://[^\s)>\]]+")


def iter_markdown_files(paths: Iterable[str | Path]) -> Iterator[Path]:
    """Yield Markdown files from a mix of file and folder paths, in a stable order."""
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for found in sorted(path.rglob("*")):
                if found.suffix.lower() in MARKDOWN_SUFFIXES and found.is_file():
                    if not SKIP_DIRS.intersection(found.relative_to(path).parts):
                        yield found
        else:
            yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return (line number, line) pairs that are prose.

    Fenced code blocks, YAML front matter and HTML comments are blanked out.
    Line numbers start at 1 and match the original file.
    """
    text = HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    fence: str | None = None
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in {"---", "..."}:
                start = i + 1
                break
    for i in range(start, len(lines)):
        line = lines[i]
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)[0] * 3
            continue
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        out.append((i + 1, line))
    return out


def strip_inline_code(line: str, replacement: str | Callable[[re.Match[str]], str] = "") -> str:
    return INLINE_CODE_RE.sub(replacement, line)


def strip_link_targets(line: str) -> str:
    """Keep link text, drop link targets, reference definitions and bare URLs."""
    if REF_DEF_RE.match(line):
        return ""
    line = INLINE_LINK_RE.sub(lambda m: m.group(2), line)
    line = AUTOLINK_RE.sub("", line)
    return BARE_URL_RE.sub("", line)


def heading(line: str) -> tuple[int, str] | None:
    """Return (level, text) if the line is an ATX heading."""
    m = HEADING_RE.match(line)
    if not m:
        return None
    return len(m.group(1)), m.group(2)


def github_slug(text: str) -> str:
    """Turn heading text into the anchor GitHub gives it (before duplicate numbering)."""
    text = strip_inline_code(text, r"\2")
    text = INLINE_LINK_RE.sub(lambda m: m.group(2), text)
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    kept = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in {" ", "-", "_"} or cat[0] in {"L", "N"} or cat == "Mn":
            kept.append(ch)
    return "".join(kept).replace(" ", "-")


def anchors(text: str) -> set[str]:
    """All anchors a Markdown file offers: heading slugs (with -1, -2 for repeats)
    and explicit id or name attributes in HTML tags."""
    seen: dict[str, int] = {}
    found: set[str] = set()
    for _, line in prose_lines(text):
        h = heading(line)
        if h:
            slug = github_slug(h[1])
            if slug in seen:
                seen[slug] += 1
                found.add(f"{slug}-{seen[slug]}")
            else:
                seen[slug] = 0
                found.add(slug)
    for m in re.finditer(r"<[a-zA-Z][^>]*\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", text):
        found.add(m.group(1))
    return found
