"""Render extracted blocks as Markdown, preserving document structure.

Headings (detected by font size) become Markdown headings — the largest size on
the page maps to ``#``, smaller headings to ``##``. Body blocks become plain
paragraphs separated by blank lines. Page boundaries are marked with an
unobtrusive HTML comment so the text stays "as is".
"""

from __future__ import annotations

from .layout import Block


def _heading_level(size: float, sizes: list[float]) -> int:
    """Map a heading's font size to a Markdown level (1-3): bigger -> shallower."""
    distinct = sorted({round(s, 1) for s in sizes}, reverse=True)
    try:
        rank = distinct.index(round(size, 1))
    except ValueError:
        rank = 0
    return min(3, rank + 1)


def _esc(cell: str) -> str:
    return " ".join(cell.split()).replace("|", "\\|")


def _render_table(grid: list[list[str]]) -> list[str]:
    """Render a 2D cell grid as a GitHub-flavoured Markdown table.

    The first row is treated as the header (the common case for extracted
    tables); a separator row follows.
    """
    ncols = max((len(r) for r in grid), default=0)
    if ncols == 0:
        return []
    rows = [[_esc(c) for c in r] + [""] * (ncols - len(r)) for r in grid]
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * ncols) + " |",
    ]
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return lines


def blocks_to_markdown(blocks: list[Block], page_markers: bool = True) -> str:
    heading_sizes = [b.size for b in blocks if b.is_heading]
    out: list[str] = []
    cur_page = None

    for b in blocks:
        if page_markers and b.page != cur_page:
            if cur_page is not None:
                out.append("")
            out.append(f"<!-- page {b.page} -->")
            cur_page = b.page

        if b.table:
            out.append("")
            out.extend(_render_table(b.table))
            out.append("")
            continue

        text = " ".join(b.text.split())  # normalise whitespace
        if not text:
            continue
        if b.is_heading:
            level = _heading_level(b.size, heading_sizes)
            out.append("")
            out.append(f"{'#' * level} {text}")
            out.append("")
        else:
            out.append(text)
            out.append("")

    # Collapse 3+ blank lines down to one.
    md_lines: list[str] = []
    blank = False
    for line in out:
        if line == "":
            if not blank:
                md_lines.append(line)
            blank = True
        else:
            md_lines.append(line)
            blank = False
    return "\n".join(md_lines).strip() + "\n"
