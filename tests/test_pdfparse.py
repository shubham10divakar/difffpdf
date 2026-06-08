"""Tests for the from-scratch PDF parser.

The lexer/filter tests are self-contained (stdlib only). The extraction test
runs against the committed sample PDFs if present, and is skipped otherwise.
"""

import os
import zlib

import pytest

from pdfdiff.pdfparse.filters import decode_stream
from pdfdiff.pdfparse.lexer import Lexer
from pdfdiff.pdfparse.objects import Name, Ref, Stream

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "largepdfs1", "large_test_document_v1.pdf")


# -- lexer -----------------------------------------------------------------

def test_lexer_primitives():
    assert Lexer(b"/Name").parse_object() == Name("Name")
    assert Lexer(b"123").parse_object() == 123
    assert Lexer(b"-4.5").parse_object() == -4.5
    assert Lexer(b"true").parse_object() is True
    assert Lexer(b"null").parse_object() is None


def test_lexer_strings():
    assert Lexer(b"(hello)").parse_object() == b"hello"
    assert Lexer(rb"(a\(b\)c)").parse_object() == b"a(b)c"
    assert Lexer(rb"(line\nbreak)").parse_object() == b"line\nbreak"
    assert Lexer(b"<48656c6c6f>").parse_object() == b"Hello"


def test_lexer_array_and_ref():
    obj = Lexer(b"[1 2 3 R /X]").parse_object()
    assert obj == [1, Ref(2, 3), Name("X")]


def test_lexer_dict_and_stream():
    d = Lexer(b"<< /Type /Page /Count 3 >>").parse_object()
    assert d == {"Type": Name("Page"), "Count": 3}

    raw = b"<< /Length 5 >>\nstream\nABCDE\nendstream"
    s = Lexer(raw).parse_object()
    assert isinstance(s, Stream)
    assert s.raw == b"ABCDE"
    assert s.dict["Length"] == 5


# -- filters ---------------------------------------------------------------

def test_flate_decode_roundtrip():
    data = b"the quick brown fox" * 10
    assert decode_stream(zlib.compress(data), Name("FlateDecode"), None) == data


def test_ascii_filters():
    import base64
    payload = b"Hello, PDF!"
    a85 = base64.a85encode(payload)
    assert decode_stream(a85, Name("ASCII85Decode"), None) == payload
    ahx = payload.hex().encode() + b">"
    assert decode_stream(ahx, Name("ASCIIHexDecode"), None) == payload


# -- end-to-end extraction -------------------------------------------------

def test_table_reconstruction():
    from pdfdiff.pdfparse.content import TextRun
    from pdfdiff.pdfparse.layout import build_blocks

    # Three aligned rows (a table) followed by a normal paragraph run.
    runs = [
        TextRun("Service", 10, 100, 10, "F1"),
        TextRun("SLA", 60, 100, 10, "F1"),
        TextRun("Owner", 110, 100, 10, "F1"),
        TextRun("API", 10, 85, 10, "F1"),
        TextRun("99.5%", 60, 85, 10, "F1"),
        TextRun("Platform", 110, 85, 10, "F1"),
        TextRun("DB", 10, 70, 10, "F1"),
        TextRun("99.9%", 60, 70, 10, "F1"),
        TextRun("Infra", 110, 70, 10, "F1"),
        TextRun("A normal paragraph sentence here.", 10, 40, 10, "F1"),
    ]
    blocks = build_blocks(runs, page=1)

    tables = [b for b in blocks if b.table]
    assert len(tables) == 1
    assert tables[0].table == [
        ["Service", "SLA", "Owner"],
        ["API", "99.5%", "Platform"],
        ["DB", "99.9%", "Infra"],
    ]
    # The paragraph is a separate, non-table block.
    assert any(not b.table and "normal paragraph" in b.text for b in blocks)


@pytest.mark.skipif(not os.path.exists(SAMPLE), reason="sample PDF not available")
def test_extract_blocks_structure():
    from pdfdiff.pdfparse.extract import extract_blocks

    blocks = extract_blocks(SAMPLE)
    assert len(blocks) > 50

    text = " ".join(b.text for b in blocks)
    assert "Section 1.1" in text
    assert "infrastructure" in text

    # The page title is larger than body text and flagged as a heading.
    headings = [b for b in blocks if b.is_heading]
    assert headings
    assert any("System Design Review" in h.text for h in headings)

    # Blocks carry 1-based page provenance in reading order.
    assert blocks[0].page == 1
    assert all(b.page >= 1 for b in blocks)
