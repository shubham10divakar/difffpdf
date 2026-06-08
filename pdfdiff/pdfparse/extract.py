"""Public extraction entry point: PDF path -> structured blocks.

Ties the parser stages together: load document -> per page build fonts, decode
the content stream, interpret it into positioned runs, then reconstruct lines
and paragraph/heading blocks in reading order.
"""

from __future__ import annotations

from .content import ContentInterpreter
from .document import PDFDocument
from .fonts import build_font
from .layout import Block, _runs_to_lines, lines_to_blocks


def _page_fonts(page: dict, doc: PDFDocument) -> dict:
    resources = doc.resolve(page.get("Resources")) or {}
    font_dict = doc.resolve(resources.get("Font")) or {}
    fonts = {}
    if isinstance(font_dict, dict):
        for name, ref in font_dict.items():
            fd = doc.resolve(ref)
            if isinstance(fd, dict):
                try:
                    fonts[name] = build_font(fd, doc)
                except Exception:
                    continue
    return fonts


def extract_blocks(path: str) -> list[Block]:
    """Extract paragraph/heading blocks across all pages, in reading order."""
    doc = PDFDocument.from_path(path)
    blocks: list[Block] = []
    for page_no, page in enumerate(doc.pages(), start=1):
        fonts = _page_fonts(page, doc)
        try:
            content = doc.page_content(page)
            runs = ContentInterpreter(fonts).run(content)
        except Exception:
            continue
        lines = _runs_to_lines(runs)
        blocks.extend(lines_to_blocks(lines, page_no))
    return blocks
