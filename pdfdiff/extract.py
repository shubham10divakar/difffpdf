"""Stage 1 — extract structured text from a PDF.

Backed by the dependency-free parser in ``pdfdiff.pdfparse`` (stdlib only). It
returns reading-order paragraph/heading *blocks* so the chunker can work off
real document structure instead of guessing from blank lines.

Scanned/image-only PDFs are not supported (no OCR): pages with no text layer
simply yield no blocks.
"""

from __future__ import annotations

from .pdfparse.document import PDFParseError
from .pdfparse.extract import extract_blocks
from .pdfparse.layout import Block

__all__ = ["extract_blocks", "Block", "PDFParseError"]
