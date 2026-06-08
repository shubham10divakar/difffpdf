"""Stage 4 — align chunks of A with chunks of B using embedding similarity.

We build the cosine-similarity matrix and greedily pair the most-similar
A/B chunks first, above a floor. Greedy (vs. optimal assignment) is simple,
fast, order-independent — so reordered content still matches — and good enough
because the judge re-scores the pairs anyway. Leftovers become DELETED (A) or
ADDED (B).
"""

from __future__ import annotations

import math

from .types import Chunk


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# A pair must clear this embedding similarity to be considered "the same point"
# at all. Below it, the two chunks are unrelated -> treat as add/delete, not a
# weak match the judge would have to reject anyway.
_MATCH_FLOOR = 0.45


def match_chunks(
    a: list[Chunk], b: list[Chunk], floor: float = _MATCH_FLOOR
) -> tuple[list[tuple[Chunk, Chunk, float]], list[Chunk], list[Chunk]]:
    """Return (matched_pairs, deleted, added).

    matched_pairs: (chunk_a, chunk_b, embedding_similarity)
    deleted:       chunks of A with no partner
    added:         chunks of B with no partner
    """
    if not a or not b:
        return [], list(a), list(b)

    # Score every cross pair once; sort high-to-low and claim greedily.
    candidates: list[tuple[float, int, int]] = []
    for i, ca in enumerate(a):
        if ca.embedding is None:
            continue
        for j, cb in enumerate(b):
            if cb.embedding is None:
                continue
            s = cosine(ca.embedding, cb.embedding)
            if s >= floor:
                candidates.append((s, i, j))

    candidates.sort(reverse=True)

    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[Chunk, Chunk, float]] = []
    for s, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((a[i], b[j], s))

    deleted = [ca for i, ca in enumerate(a) if i not in used_a]
    added = [cb for j, cb in enumerate(b) if j not in used_b]
    # Keep pairs in A's reading order for a stable, readable report.
    pairs.sort(key=lambda p: p[0].index)
    return pairs, deleted, added
