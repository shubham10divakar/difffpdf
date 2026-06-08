"""Orchestration — wire the stages together into a CompareResult.

Kept separate from the CLI so it can be called as a library too.
"""

from __future__ import annotations

from .chunk import chunk_pages
from .embed import embed_chunks, get_embedder
from .extract import extract_pages
from .judge import get_judge
from .match import match_chunks
from .score import score_granularity
from .types import CompareResult, Granularity


def compare_pdfs(
    pdf_a: str,
    pdf_b: str,
    *,
    granularities: list[Granularity],
    primary: Granularity,
    embed_backend: str = "local",
    embed_model: str | None = None,
    judge_backend: str = "local",
    judge_model: str | None = None,
    ocr: str = "auto",
    judge_band: tuple[float, float] = (0.5, 0.99),
    sim_threshold: float = 0.95,
    match_floor: float = 0.45,
    max_chunks: int | None = None,
) -> CompareResult:
    pages_a = extract_pages(pdf_a, ocr=ocr)
    pages_b = extract_pages(pdf_b, ocr=ocr)

    embedder = get_embedder(embed_backend, embed_model)
    judge = get_judge(judge_backend, judge_model)

    result = CompareResult(
        pdf_a=pdf_a,
        pdf_b=pdf_b,
        embed_backend=embedder.name,
        judge_backend=judge.name,
        primary=primary,
    )

    for gran in granularities:
        chunks_a = chunk_pages(pages_a, gran, "A")
        chunks_b = chunk_pages(pages_b, gran, "B")

        if max_chunks is not None:
            chunks_a = chunks_a[:max_chunks]
            chunks_b = chunks_b[:max_chunks]

        embed_chunks(chunks_a, embedder)
        embed_chunks(chunks_b, embedder)

        pairs, deleted, added = match_chunks(chunks_a, chunks_b, floor=match_floor)

        result.per_granularity[gran] = score_granularity(
            granularity=gran,
            pairs=pairs,
            deleted=deleted,
            added=added,
            judge=judge,
            judge_band=judge_band,
            sim_threshold=sim_threshold,
            n_a=len(chunks_a),
            n_b=len(chunks_b),
        )

    return result
