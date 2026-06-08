"""Reconstruct reading-order structure from positioned text runs.

Runs -> rows (same baseline) -> segments. A segment is either:
  * a *table* — two or more vertically-adjacent rows that each hold several
    cells aligned into shared columns, or
  * *text* — everything else, grouped into paragraphs with headings flagged by
    font size.

PDF y grows upward, so reading order is descending y then ascending x.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .content import TextRun


@dataclass
class Row:
    y: float
    cells: list[TextRun]   # left-to-right
    size: float


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
    table: list[list[str]] | None = None   # set => this block is a table grid


# -- runs -> rows ----------------------------------------------------------

def _runs_to_rows(runs: list[TextRun]) -> list[Row]:
    runs = [r for r in runs if r.text and r.text.strip()]
    if not runs:
        return []
    runs.sort(key=lambda r: (-round(r.y, 1), r.x))

    rows: list[Row] = []
    cur: list[TextRun] = []
    cur_y = None
    for r in runs:
        tol = max(2.0, 0.5 * (r.size or 10))
        if cur_y is None or abs(r.y - cur_y) <= tol:
            cur.append(r)
            cur_y = r.y if cur_y is None else (cur_y + r.y) / 2
        else:
            rows.append(_make_row(cur))
            cur = [r]
            cur_y = r.y
    if cur:
        rows.append(_make_row(cur))
    return rows


def _make_row(runs: list[TextRun]) -> Row:
    runs.sort(key=lambda r: r.x)
    return Row(y=runs[0].y, cells=list(runs), size=max(r.size for r in runs))


# -- table detection -------------------------------------------------------

def _column_centers(rows: list[Row], tol: float) -> list[float]:
    """Cluster left-edge x positions across rows into column anchors."""
    xs = sorted(c.x for r in rows for c in r.cells)
    cols: list[list[float]] = []
    for x in xs:
        if cols and x - cols[-1][-1] <= tol:
            cols[-1].append(x)
        else:
            cols.append([x])
    return [min(c) for c in cols]


def _is_table_group(rows: list[Row], col_tol: float) -> bool:
    if len(rows) < 2:
        return False
    if sum(1 for r in rows if len(r.cells) >= 2) < 2:
        return False
    centers = _column_centers(rows, col_tol)
    if len(centers) < 2:
        return False
    # Most rows should distribute their cells across >=2 distinct columns.
    multi = 0
    for r in rows:
        used = {min(range(len(centers)), key=lambda i: abs(c.x - centers[i]))
                for c in r.cells}
        if len(used) >= 2:
            multi += 1
    return multi >= 2


def _build_table(rows: list[Row], col_tol: float):
    centers = _column_centers(rows, col_tol)
    grid: list[list[str]] = []
    for r in rows:
        cells = [""] * len(centers)
        for c in r.cells:
            i = min(range(len(centers)), key=lambda k: abs(c.x - centers[k]))
            cells[i] = (cells[i] + " " + c.text).strip() if cells[i] else c.text
        grid.append(cells)
    return grid, centers


def _segment(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    """Split rows into ('table', rows) / ('text', rows) segments in order."""
    segments: list[tuple[str, list[Row]]] = []
    i = 0
    n = len(rows)
    while i < n:
        # Grow a candidate block of adjacent multi-cell rows.
        if len(rows[i].cells) >= 2:
            j = i + 1
            while j < n and len(rows[j].cells) >= 2:
                gap = rows[j - 1].y - rows[j].y
                if gap < 0 or gap > 3.0 * max(rows[j].size, 1.0):
                    break
                j += 1
            group = rows[i:j]
            col_tol = max(12.0, 1.2 * (group[0].size or 10))
            if _is_table_group(group, col_tol):
                segments.append(("table", group))
                i = j
                continue
        # Otherwise this row is plain text.
        if segments and segments[-1][0] == "text":
            segments[-1][1].append(rows[i])
        else:
            segments.append(("text", [rows[i]]))
        i += 1
    return segments


# -- text rows -> lines/blocks --------------------------------------------

def _row_to_line(row: Row) -> Line:
    parts: list[str] = []
    prev_end = None
    for r in row.cells:
        if prev_end is not None and r.x - prev_end > 0.3 * (r.size or 10):
            if parts and not parts[-1].endswith(" ") and not r.text.startswith(" "):
                parts.append(" ")
        parts.append(r.text)
        prev_end = r.x + 0.5 * (r.size or 10) * len(r.text)
    return Line(y=row.y, x0=row.cells[0].x, size=row.size, text="".join(parts).strip())


def _lines_to_blocks(lines: list[Line], page: int, body: float) -> list[Block]:
    lines = [ln for ln in lines if ln.text]
    if not lines:
        return []
    heading_cut = 1.2 * body
    blocks: list[Block] = []
    cur: list[Line] = []

    def flush():
        if not cur:
            return
        text = " ".join(ln.text for ln in cur).strip()
        if text:
            top = cur[0]
            blocks.append(Block(text=text, page=page,
                                is_heading=top.size >= heading_cut and len(cur) == 1,
                                x=top.x0, y=top.y, size=top.size, lines=list(cur)))
        cur.clear()

    for ln in lines:
        is_heading = ln.size >= heading_cut
        if not cur:
            cur.append(ln)
            if is_heading:
                flush()
            continue
        prev = cur[-1]
        gap = prev.y - ln.y
        line_h = max(prev.size, ln.size, 1.0)
        if (not is_heading and 0 <= gap <= 1.8 * line_h
                and abs(ln.x0 - cur[0].x0) <= 2.0 * line_h):
            cur.append(ln)
        else:
            flush()
            cur.append(ln)
            if is_heading:
                flush()
    flush()
    return blocks


def _table_block(grid: list[list[str]], rows: list[Row], page: int) -> Block:
    # Flatten for comparison/chunking compatibility (cells row-major, spaced).
    flat = " ".join(c for row in grid for c in row if c)
    return Block(text=flat, page=page, x=rows[0].cells[0].x, y=rows[0].y,
                 size=rows[0].size, table=grid)


def build_blocks(runs: list[TextRun], page: int) -> list[Block]:
    rows = _runs_to_rows(runs)
    if not rows:
        return []
    body = statistics.median([r.size for r in rows]) or 10.0

    blocks: list[Block] = []
    for kind, seg_rows in _segment(rows):
        if kind == "table":
            col_tol = max(12.0, 1.2 * (seg_rows[0].size or 10))
            grid, _ = _build_table(seg_rows, col_tol)
            blocks.append(_table_block(grid, seg_rows, page))
        else:
            lines = [_row_to_line(r) for r in seg_rows]
            blocks.extend(_lines_to_blocks(lines, page, body))
    return blocks
