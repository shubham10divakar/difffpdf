"""Stage 1 — extract text from a PDF, with an OCR fallback for scanned pages.

A PDF page can be 'real' selectable text, a scanned image with no text layer,
or a mix. We pull the text layer first; if a page yields essentially nothing
and OCR is permitted, we rasterise it and run Tesseract. All heavy/optional
imports (fitz, pytesseract) are lazy so importing this module never fails.
"""

from __future__ import annotations

from dataclasses import dataclass


# A page with fewer than this many word-characters is treated as "no real text"
# and is a candidate for OCR. Tuned to ignore stray page numbers / artifacts.
_MIN_TEXT_CHARS = 8


@dataclass
class Page:
    number: int        # 1-based
    text: str
    via_ocr: bool      # True if the text came from OCR rather than the text layer


def _require_fitz():
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "PyMuPDF is required to read PDFs. Install it with: pip install pymupdf"
        ) from e
    return fitz


def _ocr_page(page) -> str:
    """Rasterise a PyMuPDF page and OCR it. Raises a helpful error if the OCR
    extra isn't installed."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "OCR requested but dependencies are missing. Install with: "
            'pip install "pdfdiff[ocr]"  (and the Tesseract binary).'
        ) from e

    import io

    # 300 DPI-ish render gives Tesseract enough to work with.
    pix = page.get_pixmap(matrix=_ocr_matrix())
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _ocr_matrix():
    import fitz

    zoom = 300 / 72  # 72 is PDF's native DPI
    return fitz.Matrix(zoom, zoom)


def extract_pages(path: str, ocr: str = "auto") -> list[Page]:
    """Extract text per page.

    ocr: "auto"   -> OCR only pages whose text layer is effectively empty
         "never"  -> text layer only
         "always" -> OCR every page, ignore the text layer
    """
    if ocr not in {"auto", "never", "always"}:
        raise ValueError(f"invalid ocr mode: {ocr!r}")

    fitz = _require_fitz()
    pages: list[Page] = []

    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            if ocr == "always":
                pages.append(Page(i, _ocr_page(page).strip(), via_ocr=True))
                continue

            text = page.get_text("text").strip()

            if ocr == "auto" and len(text.replace("\n", "").strip()) < _MIN_TEXT_CHARS:
                ocr_text = _ocr_page(page).strip()
                # Only accept OCR if it actually found more than the text layer.
                if len(ocr_text) > len(text):
                    pages.append(Page(i, ocr_text, via_ocr=True))
                    continue

            pages.append(Page(i, text, via_ocr=False))

    return pages
