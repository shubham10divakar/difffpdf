"""Command-line entry point.

    pdfdiff A.pdf B.pdf [options]

Keys are read from the environment (ANTHROPIC_API_KEY, OPENAI_API_KEY,
VOYAGE_API_KEY), never from flags, so they don't land in shell history.
"""

from __future__ import annotations

import argparse
import sys

from .types import Granularity


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="difffpdf",
        description="Measure how much two PDFs differ by meaning (not wording).",
    )
    p.add_argument("pdf_a", help="first PDF")
    p.add_argument("pdf_b", help="second PDF")

    p.add_argument(
        "--granularity",
        choices=["section", "paragraph", "sentence", "all"],
        default="all",
        help="comparison unit to feature; 'all' computes every level (default)",
    )
    p.add_argument(
        "--embed-backend",
        choices=["hash", "local", "openai", "voyage"],
        default="local",
        help="embeddings used for matching: hash (zero-dep lexical), local "
        "(sentence-transformers, default), openai, or voyage",
    )
    p.add_argument("--embed-model", default=None, help="override the embedding model")
    p.add_argument(
        "--judge",
        choices=["local", "ollama", "anthropic", "openai", "none"],
        default="local",
        help="meaning judge for ambiguous pairs (default: local cross-encoder)",
    )
    p.add_argument("--judge-model", default=None, help="override the judge model")
    p.add_argument(
        "--sim-threshold",
        type=float,
        default=0.95,
        help="matched pairs at/above this meaning-similarity count as unchanged",
    )
    p.add_argument(
        "--judge-band",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=[0.5, 0.99],
        help="only judge pairs whose embedding similarity is in [LO, HI]",
    )
    p.add_argument(
        "--match-floor",
        type=float,
        default=0.45,
        help="minimum embedding similarity to consider two chunks a match",
    )
    p.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="cap chunks per document per granularity (cost guard for huge PDFs)",
    )
    p.add_argument(
        "--output",
        choices=["text", "json", "md"],
        default="text",
        help="report format (default: text)",
    )
    return p


def _granularities(choice: str) -> tuple[list[Granularity], Granularity]:
    if choice == "all":
        order = [Granularity.SECTION, Granularity.PARAGRAPH, Granularity.SENTENCE]
        return order, Granularity.PARAGRAPH
    g = Granularity(choice)
    return [g], g


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Windows consoles default to cp1252 and can't encode the report's box/star
    # glyphs. Switch stdout to UTF-8 (replace as a last resort) so output never
    # crashes on encoding.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    grans, primary = _granularities(args.granularity)

    # Import the pipeline lazily so --help works without optional deps installed.
    from .pipeline import compare_pdfs
    from .report import render

    try:
        result = compare_pdfs(
            args.pdf_a,
            args.pdf_b,
            granularities=grans,
            primary=primary,
            embed_backend=args.embed_backend,
            embed_model=args.embed_model,
            judge_backend=args.judge,
            judge_model=args.judge_model,
            judge_band=tuple(args.judge_band),
            sim_threshold=args.sim_threshold,
            match_floor=args.match_floor,
            max_chunks=args.max_chunks,
        )
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(f"pdfdiff: {e}", file=sys.stderr)
        return 1

    print(render(result, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
