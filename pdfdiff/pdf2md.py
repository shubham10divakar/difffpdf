"""CLI: convert a PDF's text to Markdown, preserving structure.

    pdf2md input.pdf                 # print Markdown to stdout
    pdf2md input.pdf -o out.md       # write to a file
    pdf2md input.pdf --no-pages      # omit <!-- page N --> markers

Uses the dependency-free extractor in pdfdiff.pdfparse (no PyMuPDF, no OCR).
"""

from __future__ import annotations

import argparse
import sys

from .pdfparse.extract import extract_blocks
from .pdfparse.markdown import blocks_to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf2md",
        description="Convert a PDF's text to structured Markdown (headings + paragraphs).",
    )
    p.add_argument("pdf", help="input PDF file")
    p.add_argument("-o", "--output", default=None, help="output .md file (default: stdout)")
    p.add_argument("--no-pages", action="store_true", help="omit page-boundary markers")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    try:
        blocks = extract_blocks(args.pdf)
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as e:
        print(f"pdf2md: {e}", file=sys.stderr)
        return 1

    if not blocks:
        print("pdf2md: no extractable text (scanned/image PDF or unsupported encoding)",
              file=sys.stderr)
        return 1

    md = blocks_to_markdown(blocks, page_markers=not args.no_pages)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"wrote {args.output} ({md.count(chr(10)) + 1} lines)", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
