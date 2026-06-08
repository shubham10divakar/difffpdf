"""Shared data structures passed between pipeline stages.

The pipeline is: extract -> chunk -> embed -> match -> judge -> score -> report.
Each stage consumes and produces these plain dataclasses so stages stay
decoupled and individually testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Granularity(str, Enum):
    """The unit at which two documents are compared."""

    SECTION = "section"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"


@dataclass
class Chunk:
    """A comparable unit of text from one document.

    ``weight`` drives the length-weighting in scoring so a changed 10-line
    paragraph counts more than a changed one-liner. We use a token-ish word
    count rather than characters so wording, not whitespace, sets the weight.
    """

    doc: str            # "A" or "B" — which document this came from
    index: int          # position within its document, at this granularity
    text: str
    page: int           # 1-based source page (best effort)
    section: str = ""   # nearest heading/section label, if detected
    embedding: Optional[list[float]] = None

    @property
    def weight(self) -> float:
        # Word count, floored at 1 so empty/degenerate chunks never vanish.
        return float(max(1, len(self.text.split())))


class ChangeKind(str, Enum):
    CHANGED = "changed"   # matched pair whose meaning differs (sim below threshold)
    SAME = "same"         # matched pair judged semantically equivalent
    DELETED = "deleted"   # present in A, no counterpart in B
    ADDED = "added"       # present in B, no counterpart in A


@dataclass
class Change:
    """One entry in the detailed diff list."""

    kind: ChangeKind
    similarity: float          # 0..1; 1.0 == identical meaning. N/A for add/del -> 0.0
    weight: float              # contribution mass used by the scorer
    a: Optional[Chunk] = None  # source chunk in A (None for ADDED)
    b: Optional[Chunk] = None  # source chunk in B (None for DELETED)
    explanation: str = ""      # one-line "what changed", from a generative judge


@dataclass
class GranularityResult:
    """Full result of comparing at a single granularity."""

    granularity: Granularity
    similarity_pct: float            # 0..100, the headline number
    difference_pct: float            # 100 - similarity_pct
    changes: list[Change] = field(default_factory=list)

    # Bookkeeping for the report / debugging.
    n_chunks_a: int = 0
    n_chunks_b: int = 0
    judged_pairs: int = 0            # how many pairs actually hit the judge


@dataclass
class CompareResult:
    """Top-level result: one entry per granularity that was computed."""

    pdf_a: str
    pdf_b: str
    embed_backend: str
    judge_backend: str
    per_granularity: dict[Granularity, GranularityResult] = field(default_factory=dict)
    primary: Optional[Granularity] = None  # which one the user asked to feature
