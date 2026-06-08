"""Reconstruct reading-order structure from positioned text runs.

Runs -> lines (same baseline) -> blocks (paragraphs). Headings are detected by a
font size noticeably larger than the page's body text. PDF y grows upward, so
reading order is descending y then ascending x.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .content import TextRun


@dataclass
class Line:
    y: float
    x0: float
    size: float
    text: str


@dataclass
class Block:
    text: str
    page: int
    is_heading: bool = False
    x: float = 0.0
    y: float = 0.0
    size: float = 0.0
    lines: list[Line] = field(default_factory=list)


def _runs_to_lines(runs: list[TextRun]) -> list[Line]:
    runs = [r for r in runs if r.text and r.text.strip()]
    if not runs:
        return []
    # Top-to-bottom, then left-to-right.
    runs.sort(key=lambda r: (-round(r.y, 1), r.x))

    lines: list[Line] = []
    cur: list[TextRun] = []
    cur_y = None
    for r in runs:
        tol = max(2.0, 0.5 * (r.size or 10))
        if cur_y is None or abs(r.y - cur_y) <= tol:
            cur.append(r)
            cur_y = r.y if cur_y is None else (cur_y + r.y) / 2
        else:
            lines.append(_assemble_line(cur))
            cur = [r]
            cur_y = r.y
    if cur:
        lines.append(_assemble_line(cur))
    return lines


def _assemble_line(runs: list[TextRun]) -> Line:
    runs.sort(key=lambda r: r.x)
    parts: list[str] = []
    prev_end = None
    for r in runs:
        # Insert a space when there's a visible gap and neither side has one.
        if prev_end is not None and r.x - prev_end > 0.3 * (r.size or 10):
            if parts and not parts[-1].endswith(" ") and not r.text.startswith(" "):
                parts.append(" ")
        parts.append(r.text)
        prev_end = r.x + 0.5 * (r.size or 10) * len(r.text)
    text = "".join(parts).strip()
    size = max((r.size for r in runs), default=0.0)
    return Line(y=runs[0].y, x0=runs[0].x, size=size, text=text)


def lines_to_blocks(lines: list[Line], page: int) -> list[Block]:
    lines = [ln for ln in lines if ln.text]
    if not lines:
        return []
    body = statistics.median([ln.size for ln in lines]) or 10.0
    heading_cut = 1.2 * body

    blocks: list[Block] = []
    cur: list[Line] = []

    def flush():
        if not cur:
            return
        text = " ".join(ln.text for ln in cur).strip()
        if text:
            top = cur[0]
            blocks.append(Block(
                text=text, page=page,
                is_heading=top.size >= heading_cut and len(cur) == 1,
                x=top.x0, y=top.y, size=top.size, lines=list(cur),
            ))
        cur.clear()

    for ln in lines:
        is_heading = ln.size >= heading_cut
        if not cur:
            cur.append(ln)
            if is_heading:
                flush()
            continue
        prev = cur[-1]
        gap = prev.y - ln.y                       # positive going down the page
        line_h = max(prev.size, ln.size, 1.0)
        same_para = (
            not is_heading
            and 0 <= gap <= 1.8 * line_h
            and abs(ln.x0 - cur[0].x0) <= 2.0 * line_h
        )
        if same_para:
            cur.append(ln)
        else:
            flush()
            cur.append(ln)
            if is_heading:
                flush()
    flush()
    return blocks
