"""Render a CompareResult as text, JSON, or Markdown.

The detailed diff list shows only non-trivial changes (CHANGED/ADDED/DELETED);
SAME pairs are summarised as a count so reworded-but-equivalent content doesn't
bury the real differences.
"""

from __future__ import annotations

import json
import textwrap

from .types import Change, ChangeKind, CompareResult, GranularityResult


def _trim(text: str, width: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _sort_changes(changes: list[Change]) -> list[Change]:
    # Loudest first: biggest changed mass at the top.
    order = {ChangeKind.CHANGED: 0, ChangeKind.DELETED: 1, ChangeKind.ADDED: 2}
    real = [c for c in changes if c.kind is not ChangeKind.SAME]
    return sorted(real, key=lambda c: (order[c.kind], -c.weight * (1 - c.similarity)))


def _section(c: Change) -> str:
    src = c.a or c.b
    return src.section if src and src.section else f"p{src.page}" if src else "?"


def _render_change_text(c: Change) -> str:
    tag = c.kind.value.upper()
    sec = _section(c)
    if c.kind is ChangeKind.CHANGED:
        head = f"[CHANGED · sim {c.similarity:.2f} · {c.weight:.0f}w · {sec}]"
        body = f"  A: \"{_trim(c.a.text)}\"\n  B: \"{_trim(c.b.text)}\""
        if c.explanation:
            body += f"\n  → {c.explanation}"
        return f"{head}\n{body}"
    if c.kind is ChangeKind.DELETED:
        return f"[DELETED · {sec}] \"{_trim(c.a.text)}\""
    return f"[ADDED · {sec}] \"{_trim(c.b.text)}\""


def _render_granularity_text(g: GranularityResult, primary: bool) -> str:
    star = " ★" if primary else ""
    lines = [
        f"── {g.granularity.value.upper()}{star} "
        f"────────────────────────────────────────",
        f"  similarity: {g.similarity_pct:5.1f}%   "
        f"difference: {g.difference_pct:5.1f}%",
        f"  chunks: A={g.n_chunks_a} B={g.n_chunks_b}   "
        f"judged pairs: {g.judged_pairs}",
    ]
    real = _sort_changes(g.changes)
    same = sum(1 for c in g.changes if c.kind is ChangeKind.SAME)
    lines.append(f"  equivalent (unchanged in meaning): {same}")
    if real:
        lines.append("")
        for c in real:
            lines.append(textwrap.indent(_render_change_text(c), "  "))
    return "\n".join(lines)


def render_text(result: CompareResult) -> str:
    out = [
        "PDF semantic comparison",
        f"  A: {result.pdf_a}",
        f"  B: {result.pdf_b}",
        f"  embed: {result.embed_backend}   judge: {result.judge_backend}",
        "",
    ]
    # Coarse-to-fine headline line.
    headline = "  ".join(
        f"{g.value}={result.per_granularity[g].similarity_pct:.1f}%"
        for g in result.per_granularity
    )
    out.append(f"SIMILARITY  {headline}")
    out.append("")
    for g, gr in result.per_granularity.items():
        out.append(_render_granularity_text(gr, g == result.primary))
        out.append("")
    return "\n".join(out)


def _change_to_dict(c: Change) -> dict:
    return {
        "kind": c.kind.value,
        "similarity": None if c.kind in (ChangeKind.ADDED, ChangeKind.DELETED) else round(c.similarity, 4),
        "weight": c.weight,
        "section": _section(c),
        "a": c.a.text if c.a else None,
        "b": c.b.text if c.b else None,
        "explanation": c.explanation or None,
    }


def render_json(result: CompareResult) -> str:
    payload = {
        "pdf_a": result.pdf_a,
        "pdf_b": result.pdf_b,
        "embed_backend": result.embed_backend,
        "judge_backend": result.judge_backend,
        "primary": result.primary.value if result.primary else None,
        "granularities": {
            g.value: {
                "similarity_pct": round(gr.similarity_pct, 2),
                "difference_pct": round(gr.difference_pct, 2),
                "n_chunks_a": gr.n_chunks_a,
                "n_chunks_b": gr.n_chunks_b,
                "judged_pairs": gr.judged_pairs,
                "changes": [
                    _change_to_dict(c)
                    for c in _sort_changes(gr.changes)
                ],
            }
            for g, gr in result.per_granularity.items()
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_markdown(result: CompareResult) -> str:
    out = [
        "# PDF semantic comparison",
        "",
        f"- **A:** `{result.pdf_a}`",
        f"- **B:** `{result.pdf_b}`",
        f"- **embed:** {result.embed_backend} · **judge:** {result.judge_backend}",
        "",
        "## Similarity",
        "",
        "| Granularity | Similarity | Difference |",
        "| --- | --- | --- |",
    ]
    for g, gr in result.per_granularity.items():
        mark = " ★" if g == result.primary else ""
        out.append(
            f"| {g.value}{mark} | {gr.similarity_pct:.1f}% | {gr.difference_pct:.1f}% |"
        )
    out.append("")
    for g, gr in result.per_granularity.items():
        out.append(f"## Changes — {g.value}")
        out.append("")
        real = _sort_changes(gr.changes)
        if not real:
            out.append("_No material differences._\n")
            continue
        for c in real:
            sec = _section(c)
            if c.kind is ChangeKind.CHANGED:
                out.append(f"- **CHANGED** · sim {c.similarity:.2f} · {sec}")
                out.append(f"  - A: {_trim(c.a.text)}")
                out.append(f"  - B: {_trim(c.b.text)}")
                if c.explanation:
                    out.append(f"  - → {c.explanation}")
            elif c.kind is ChangeKind.DELETED:
                out.append(f"- **DELETED** · {sec}: {_trim(c.a.text)}")
            else:
                out.append(f"- **ADDED** · {sec}: {_trim(c.b.text)}")
        out.append("")
    return "\n".join(out)


def render(result: CompareResult, fmt: str) -> str:
    if fmt == "text":
        return render_text(result)
    if fmt == "json":
        return render_json(result)
    if fmt == "md":
        return render_markdown(result)
    raise ValueError(f"unknown output format: {fmt!r}")
