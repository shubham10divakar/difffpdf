"""Stage 2 — split structured blocks into comparable chunks.

The extractor already gives us reading-order blocks with heading flags, so we
no longer guess paragraph boundaries from blank lines. Three granularities:

  section   — heading + the blocks beneath it, merged
  paragraph — one chunk per block
  sentence  — blocks split into sentences

Computing all three lets the report show a coarse-to-fine picture.
"""

from __future__ import annotations

import regex as re

from .pdfparse.layout import Block
from .types import Chunk, Granularity

# Sentence boundary: punctuation + space + capital/quote, but not after a common
# abbreviation. Lightweight; good enough for prose without an NLP model.
_ABBREV = r"(?<!\b(?:Mr|Mrs|Ms|Dr|Inc|Ltd|Co|No|St|vs|etc|e\.g|i\.e|Fig|Art|Sec|cf|al))"
_SENT_SPLIT = re.compile(rf"{_ABBREV}(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])")

# A "Section X.Y" prefix used as a readable label in the report.
_SECTION_LABEL = re.compile(r"Section\s+\d+(\.\d+)*", re.IGNORECASE)


def _label(text: str, heading: str) -> str:
    m = _SECTION_LABEL.search(text)
    if m:
        return m.group(0)
    return heading


def chunk_blocks(blocks: list[Block], granularity: Granularity, doc: str) -> list[Chunk]:
    """Produce chunks at the requested granularity for one document."""
    if granularity is Granularity.PARAGRAPH:
        chunks: list[Chunk] = []
        heading = ""
        for b in blocks:
            if b.is_heading:
                heading = b.text
            chunks.append(Chunk(doc=doc, index=len(chunks), text=b.text,
                                page=b.page, section=_label(b.text, heading)))
        return chunks

    if granularity is Granularity.SECTION:
        chunks = []
        buf: list[str] = []
        sec = ""
        page = 1
        for b in blocks:
            if b.is_heading:
                if buf:
                    chunks.append(Chunk(doc=doc, index=len(chunks), text=" ".join(buf),
                                        page=page, section=sec))
                buf = [b.text]
                sec = b.text
                page = b.page
            else:
                if not buf:
                    page = b.page
                    sec = _label(b.text, sec)
                buf.append(b.text)
        if buf:
            chunks.append(Chunk(doc=doc, index=len(chunks), text=" ".join(buf),
                                page=page, section=sec))
        # No headings at all: fall back to one chunk per block.
        return chunks or chunk_blocks(blocks, Granularity.PARAGRAPH, doc)

    if granularity is Granularity.SENTENCE:
        chunks = []
        heading = ""
        for b in blocks:
            if b.is_heading:
                heading = b.text
            label = _label(b.text, heading)
            for sent in _SENT_SPLIT.split(b.text):
                sent = sent.strip()
                if sent:
                    chunks.append(Chunk(doc=doc, index=len(chunks), text=sent,
                                        page=b.page, section=label))
        return chunks

    raise ValueError(f"unknown granularity: {granularity}")
