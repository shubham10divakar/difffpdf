"""Stage 2 — split extracted pages into comparable chunks.

We produce three granularities from the same page text:

  section   — text grouped under a detected heading
  paragraph — blank-line / layout separated blocks
  sentence  — individual sentences

The caller decides which to feature; computing all three lets the report show
a coarse-to-fine picture (e.g. "sections 92%, paragraphs 88%, sentences 81%").
"""

from __future__ import annotations

import regex as re

from .extract import Page
from .types import Chunk, Granularity


# A line that looks like a heading: short, no trailing sentence punctuation, and
# either ALL CAPS, a numbered clause (1.2.3), or Title Case. Deliberately
# conservative — false headings just merge sections, which is harmless.
_HEADING = re.compile(
    r"""^\s*(
        (\d+(\.\d+)*\.?\s+\S.*)            # 1.  /  2.3  Numbered clause
        | ([A-Z0-9][A-Z0-9 \-/&,]{2,60})  # ALL CAPS heading
        | (([A-Z][\w'-]*)(\s+[A-Z][\w'-]*){0,8})  # Title Case heading
    )\s*$""",
    re.VERBOSE,
)

# Sentence boundary: punctuation + space + capital/quote, but not after a
# common abbreviation. Lightweight; good enough for prose without dragging in
# an NLP model.
_ABBREV = r"(?<!\b(?:Mr|Mrs|Ms|Dr|Inc|Ltd|Co|No|St|vs|etc|e\.g|i\.e|Fig|Art|Sec|cf|al))"
_SENT_SPLIT = re.compile(rf"{_ABBREV}(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])")


# A line that begins a new logical block. Many PDFs wrap a block across several
# lines with NO blank line between blocks, so blank-line splitting alone merges
# the whole document into one chunk. We also break when a line clearly starts a
# new unit: a numbered/"Section X.Y" clause, optionally prefixed by a bracketed
# change tag like "[UPDATED: ...]", or a "... - Page N" running header.
_BLOCK_START = re.compile(
    r"""^\s*(
        (\[[^\]]*\]\s*)?            # optional leading [TAG: ...] annotation
        (Section\s+)?\d+(\.\d+)*[:.)]?\s+\S   # 1.  2.3  Section 3.3:  ...
      | \[[A-Z][^\]]*\]             # a standalone bracketed tag line
    )""",
    re.VERBOSE,
)
_PAGE_HEADER = re.compile(r"-\s*Page\s+\d+\s*$", re.IGNORECASE)

# "Section X.Y" label used to group blocks for the SECTION granularity / report.
_SECTION_LABEL = re.compile(r"Section\s+\d+(\.\d+)*", re.IGNORECASE)


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 80:
        return False
    if line.endswith((".", ",", ";", ":")) and not re.match(r"^\d+(\.\d+)*\.?\s", line):
        return False
    return bool(_HEADING.match(line))


def _starts_block(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return bool(
        _BLOCK_START.match(s)
        or _PAGE_HEADER.search(s)
        or _looks_like_heading(s)
    )


def _section_label(line: str) -> str:
    m = _SECTION_LABEL.search(line)
    return m.group(0) if m else ""


def _full_text_with_pages(pages: list[Page]) -> list[tuple[str, int]]:
    """Flatten pages into (line, page_number) keeping page provenance."""
    out: list[tuple[str, int]] = []
    for p in pages:
        for line in p.text.split("\n"):
            out.append((line, p.number))
    return out


def _paragraph_blocks(pages: list[Page]) -> list[tuple[str, int, str]]:
    """Yield (paragraph_text, page, section_label).

    A new block starts at a blank line OR a block-start marker, so documents
    without blank-line separators still split correctly. Wrapped continuation
    lines are joined into the current block. Each block carries its nearest
    "Section X.Y" label for the report and for section grouping.
    """
    blocks: list[tuple[str, int, str]] = []
    cur: list[str] = []
    cur_page = 1
    cur_section = ""

    def flush():
        nonlocal cur
        if cur:
            text = " ".join(s.strip() for s in cur).strip()
            if text:
                blocks.append((text, cur_page, cur_section))
        cur = []

    for line, page in _full_text_with_pages(pages):
        if not line.strip():
            flush()
            continue
        if cur and _starts_block(line):
            flush()
        if not cur:
            cur_page = page
            cur_section = _section_label(line)
        cur.append(line)
    flush()
    return blocks


def chunk_pages(pages: list[Page], granularity: Granularity, doc: str) -> list[Chunk]:
    """Produce chunks at the requested granularity for one document."""
    blocks = _paragraph_blocks(pages)

    if granularity is Granularity.PARAGRAPH:
        return [
            Chunk(doc=doc, index=i, text=text, page=page, section=section)
            for i, (text, page, section) in enumerate(blocks)
        ]

    if granularity is Granularity.SECTION:
        # Merge consecutive blocks sharing a section label into one chunk.
        merged: list[Chunk] = []
        buf: list[str] = []
        buf_page = 1
        buf_section = ""
        for text, page, section in blocks:
            if section != buf_section and buf:
                merged.append(
                    Chunk(doc=doc, index=len(merged), text=" ".join(buf),
                          page=buf_page, section=buf_section)
                )
                buf = []
            if not buf:
                buf_page, buf_section = page, section
            buf.append(text)
        if buf:
            merged.append(
                Chunk(doc=doc, index=len(merged), text=" ".join(buf),
                      page=buf_page, section=buf_section)
            )
        return merged

    if granularity is Granularity.SENTENCE:
        out: list[Chunk] = []
        for text, page, section in blocks:
            for sent in _SENT_SPLIT.split(text):
                sent = sent.strip()
                if sent:
                    out.append(Chunk(doc=doc, index=len(out), text=sent,
                                     page=page, section=section))
        return out

    raise ValueError(f"unknown granularity: {granularity}")
