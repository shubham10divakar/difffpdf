"""Scoring + matching tests that run on the standard library alone — no torch,
no PDFs, no network. They lock in the formula and the two cases that motivated
the whole tool: faithful rewords must NOT inflate the diff, negation flips MUST.
"""

import math

from pdfdiff.match import match_chunks, cosine
from pdfdiff.score import score_granularity
from pdfdiff.types import ChangeKind, Chunk, Granularity


class FakeJudge:
    """Returns a preset similarity per (a_text, b_text) so we can test the
    scorer deterministically without a real model."""

    name = "fake"
    gives_explanation = True

    def __init__(self, table):
        self.table = table

    def judge_batch(self, pairs):
        return [self.table.get((a, b), (0.5, "?")) for a, b in pairs]


def _chunk(doc, i, text, emb):
    c = Chunk(doc=doc, index=i, text=text, page=1)
    c.embedding = emb
    return c


def test_identical_docs_score_100():
    a = [_chunk("A", 0, "the cat sat", [1.0, 0.0])]
    b = [_chunk("B", 0, "the cat sat", [1.0, 0.0])]
    pairs, deleted, added = match_chunks(a, b)
    res = score_granularity(
        Granularity.SENTENCE, pairs, deleted, added,
        judge=FakeJudge({("the cat sat", "the cat sat"): (1.0, "equivalent")}),
        judge_band=(0.5, 0.99), sim_threshold=0.95, n_a=1, n_b=1,
    )
    assert res.similarity_pct == 100.0
    assert all(c.kind is ChangeKind.SAME for c in res.changes)


def test_faithful_reword_stays_high():
    # Different words, judge says same meaning -> diff should be tiny.
    a = [_chunk("A", 0, "payment due in 30 days", [1.0, 0.0])]
    b = [_chunk("B", 0, "must be paid within thirty days", [0.8, 0.3])]
    pairs, deleted, added = match_chunks(a, b)
    res = score_granularity(
        Granularity.SENTENCE, pairs, deleted, added,
        judge=FakeJudge({
            ("payment due in 30 days", "must be paid within thirty days"):
                (0.98, "equivalent")
        }),
        judge_band=(0.5, 0.99), sim_threshold=0.95, n_a=1, n_b=1,
    )
    assert res.similarity_pct > 95.0
    assert res.changes[0].kind is ChangeKind.SAME


def test_negation_flip_scores_low():
    # Near-identical text, opposite meaning. High embedding sim, but the judge
    # (in-band) drops it -> must register as a real CHANGED with low similarity.
    a = [_chunk("A", 0, "the tenant must pay the deposit", [1.0, 0.0])]
    b = [_chunk("B", 0, "the tenant must not pay the deposit", [0.9, 0.2])]
    pairs, deleted, added = match_chunks(a, b)
    # embedding sim is high but < 0.99, so it falls inside the judge band.
    res = score_granularity(
        Granularity.SENTENCE, pairs, deleted, added,
        judge=FakeJudge({
            ("the tenant must pay the deposit",
             "the tenant must not pay the deposit"): (0.1, "obligation inverted")
        }),
        judge_band=(0.5, 0.99), sim_threshold=0.95, n_a=1, n_b=1,
    )
    assert res.similarity_pct < 50.0
    assert res.changes[0].kind is ChangeKind.CHANGED
    assert "inverted" in res.changes[0].explanation


def test_added_and_deleted_count_full_weight():
    a = [_chunk("A", 0, "alpha beta gamma", [1.0, 0.0])]          # deleted
    b = [_chunk("B", 0, "delta epsilon zeta", [0.0, 1.0])]        # added
    pairs, deleted, added = match_chunks(a, b)  # no match: orthogonal vectors
    assert not pairs and len(deleted) == 1 and len(added) == 1
    res = score_granularity(
        Granularity.SENTENCE, pairs, deleted, added,
        judge=FakeJudge({}), judge_band=(0.5, 0.99),
        sim_threshold=0.95, n_a=1, n_b=1,
    )
    # Everything changed -> 0% similar.
    assert res.similarity_pct == 0.0
    kinds = {c.kind for c in res.changes}
    assert kinds == {ChangeKind.DELETED, ChangeKind.ADDED}


def test_weighting_big_change_dominates_small():
    # A tiny changed sentence and a big unchanged one: similarity stays high
    # because weight follows length.
    a = [
        _chunk("A", 0, "ok", [1.0, 0.0]),
        _chunk("A", 1, " ".join(["word"] * 50), [0.0, 1.0]),
    ]
    b = [
        _chunk("B", 0, "no", [0.8, 0.3]),
        _chunk("B", 1, " ".join(["word"] * 50), [0.0, 1.0]),
    ]
    pairs, deleted, added = match_chunks(a, b)
    res = score_granularity(
        Granularity.SENTENCE, pairs, deleted, added,
        judge=FakeJudge({
            ("ok", "no"): (0.0, "changed"),
            (" ".join(["word"] * 50), " ".join(["word"] * 50)): (1.0, "same"),
        }),
        judge_band=(0.5, 0.99), sim_threshold=0.95, n_a=2, n_b=2,
    )
    # 1 changed word out of ~51 total mass -> ~98% similar.
    assert res.similarity_pct > 95.0


def test_cosine_basic():
    assert math.isclose(cosine([1, 0], [1, 0]), 1.0)
    assert math.isclose(cosine([1, 0], [0, 1]), 0.0)
