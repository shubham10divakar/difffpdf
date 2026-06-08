"""Stage 6 — combine matches + judgments into the headline %% and diff list.

Length-weighted formula (w = word count; w̄ = mean weight of a matched pair):

    difference = [ Σ_pairs (1-s)·w̄  +  Σ_deleted w_A  +  Σ_added w_B ]
                 ---------------------------------------------------------
                 [ Σ_pairs w̄        +  Σ_deleted w_A  +  Σ_added w_B ]

    similarity% = 100 · (1 - difference)

So a faithful reword (s≈1) adds ~0 to the numerator, while a negation flip on a
big clause (low s, high w̄) moves the number a lot. The denominator is the total
content mass of both documents, keeping the result in 0..100.
"""

from __future__ import annotations

import math

from .judge import Judge
from .types import (
    Change,
    ChangeKind,
    Chunk,
    Granularity,
    GranularityResult,
)


def _avg_weight(a: Chunk, b: Chunk) -> float:
    return (a.weight + b.weight) / 2.0


def score_granularity(
    granularity: Granularity,
    pairs: list[tuple[Chunk, Chunk, float]],
    deleted: list[Chunk],
    added: list[Chunk],
    judge: Judge,
    judge_band: tuple[float, float],
    sim_threshold: float,
    n_a: int,
    n_b: int,
) -> GranularityResult:
    lo, hi = judge_band

    # Decide which pairs the judge re-scores: ambiguous middle only. Exact-ish
    # duplicates (sim>hi) and weak matches (sim<lo) keep their embedding score.
    to_judge_idx: list[int] = []
    if judge.name != "none":
        for i, (_a, _b, s) in enumerate(pairs):
            if lo <= s <= hi:
                to_judge_idx.append(i)

    judged: dict[int, tuple[float, str]] = {}
    if to_judge_idx:
        texts = [(pairs[i][0].text, pairs[i][1].text) for i in to_judge_idx]
        results = judge.judge_batch(texts)
        for i, (sim, expl) in zip(to_judge_idx, results):
            # A judge that errored returns NaN; fall back to the embedding score.
            if not math.isnan(sim):
                judged[i] = (sim, expl)
            else:
                judged[i] = (pairs[i][2], expl)

    changes: list[Change] = []
    num = 0.0   # accumulated "changed mass"
    den = 0.0   # accumulated total mass

    for i, (ca, cb, embed_s) in enumerate(pairs):
        sim, expl = judged.get(i, (embed_s, ""))
        w = _avg_weight(ca, cb)
        num += (1.0 - sim) * w
        den += w
        kind = ChangeKind.SAME if sim >= sim_threshold else ChangeKind.CHANGED
        changes.append(
            Change(kind=kind, similarity=sim, weight=w, a=ca, b=cb, explanation=expl)
        )

    for ca in deleted:
        num += ca.weight
        den += ca.weight
        changes.append(
            Change(kind=ChangeKind.DELETED, similarity=0.0, weight=ca.weight, a=ca)
        )

    for cb in added:
        num += cb.weight
        den += cb.weight
        changes.append(
            Change(kind=ChangeKind.ADDED, similarity=0.0, weight=cb.weight, b=cb)
        )

    difference = (num / den) if den else 0.0
    similarity_pct = 100.0 * (1.0 - difference)

    return GranularityResult(
        granularity=granularity,
        similarity_pct=similarity_pct,
        difference_pct=100.0 - similarity_pct,
        changes=changes,
        n_chunks_a=n_a,
        n_chunks_b=n_b,
        judged_pairs=len(to_judge_idx),
    )
