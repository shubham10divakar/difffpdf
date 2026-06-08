"""A small, dependency-free PDF text extractor.

Built from scratch on the Python standard library (only ``zlib`` for stream
decompression). It targets the common case — digital PDFs using classic or
xref-stream cross-references, FlateDecode streams, and simple/Type0 fonts — and
reconstructs page *structure* (reading-order blocks, paragraphs, headings) so
the rest of the pipeline can chunk on real layout instead of guessing.

It is deliberately not a full PDF implementation: encrypted files, scanned
images (no OCR), and exotic font encodings without a ToUnicode map are out of
scope. See ``extract.py`` for the public ``extract_blocks`` entry point.
"""

from .document import PDFDocument, PDFParseError

__all__ = ["PDFDocument", "PDFParseError"]
