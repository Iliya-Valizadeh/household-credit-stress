"""Check links between local files in Markdown, with no network access.

Usage: python tools/links_check.py [--root DIR] PATH [PATH ...]

For every link or image in the given Markdown files (inline links, reference
definitions and HTML href or src attributes), the check makes sure that:
- a relative path points to a file or folder that exists
- a path starting with "/" exists under --root (default: the current folder),
  which is how GitHub reads such links
- a "#section" part matches a heading or an id in the target Markdown file

Web links (http, https, mailto and similar) are skipped here. lychee checks them
with the settings in tools/lychee.toml.

Exit code 0 means every local link works. Exit code 1 means at least one is broken.
Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from _markdown import (
    INLINE_LINK_RE,
    MARKDOWN_SUFFIXES,
    REF_DEF_RE,
    anchors,
    iter_markdown_files,
    prose_lines,
    strip_inline_code,
)

SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
HTML_ATTR_RE = re.compile(r"<[a-zA-Z][^>]*\b(?:href|src)\s*=\s*[\"']([^\"']*)[\"']")


def extract_links(text: str) -> list[tuple[int, str]]:
    """Return (line number, target) for every link in the prose of a Markdown file."""
    found = []
    for n, raw in prose_lines(text):
        line = strip_inline_code(raw)
        ref = REF_DEF_RE.match(line)
        if ref:
            found.append((n, ref.group(2)))
            continue
        found.extend((n, m.group(3)) for m in INLINE_LINK_RE.finditer(line))
        found.extend((n, m.group(1)) for m in HTML_ATTR_RE.finditer(line))
    return [(n, t.strip("<>")) for n, t in found if t.strip("<>")]


def check_link(source: Path, target: str, root: Path) -> str | None:
    """Return a problem message, or None if the link works or is not local."""
    if SCHEME_RE.match(target) or target.startswith("//"):
        return None
    path_part, _, fragment = target.partition("#")
    path_part = unquote(path_part.split("?", 1)[0])
    if not path_part:
        dest = source
    elif path_part.startswith("/"):
        dest = root / path_part.lstrip("/")
    else:
        dest = source.parent / path_part
    if not dest.exists():
        return f"missing file: {target}"
    if fragment and dest.is_file() and dest.suffix.lower() in MARKDOWN_SUFFIXES:
        if unquote(fragment) not in anchors(dest.read_text(encoding="utf-8")):
            return f"missing section: {target}"
    return None


def check(paths: list[str], root: Path) -> list[str]:
    problems = []
    for path in iter_markdown_files(paths):
        for n, target in extract_links(path.read_text(encoding="utf-8")):
            problem = check_link(path, target, root)
            if problem:
                problems.append(f"{path}:{n}: {problem}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="Markdown files or folders")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    problems = check(args.paths, args.root)
    for p in problems:
        print(p)
    print(f"local link check: {len(problems)} broken link(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
