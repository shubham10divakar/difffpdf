"""Build a decoder that turns a font's byte codes into Unicode text.

Resolution order, best first:
  1. /ToUnicode CMap  — authoritative when present (any font type).
  2. simple-font /Encoding (base + /Differences) — the common Type1/TrueType case.
  3. Type0 Identity-H  — 2-byte codes; without a ToUnicode map we can only pass
     the code points through, so we fall back to a best-effort latin decode.
"""

from __future__ import annotations

import re

from .encodings import base_table, glyph_to_unicode
from .lexer import Lexer
from .objects import Name, Stream

_HEX = re.compile(rb"<([0-9A-Fa-f\s]*)>")


def _hex_to_int(h: bytes) -> int:
    h = bytes(c for c in h if not (c in b" \t\r\n"))
    return int(h, 16) if h else 0


def _hex_to_unicode(h: bytes) -> str:
    h = bytes(c for c in h if not (c in b" \t\r\n"))
    if len(h) % 2:
        h += b"0"
    raw = bytes.fromhex(h.decode("latin-1"))
    # ToUnicode destination strings are UTF-16BE.
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


def parse_tounicode(data: bytes) -> dict[int, str]:
    """Parse the bfchar/bfrange sections of a ToUnicode CMap stream."""
    table: dict[int, str] = {}

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]+)>", block):
            table[_hex_to_int(src)] = _hex_to_unicode(dst)

    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        # Form 1: <lo> <hi> <dststart>   Form 2: <lo> <hi> [<d1> <d2> ...]
        for m in re.finditer(
            rb"<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f\s]+>)",
            block,
        ):
            lo, hi, dst = _hex_to_int(m.group(1)), _hex_to_int(m.group(2)), m.group(3)
            if dst.startswith(b"["):
                items = _HEX.findall(dst)
                for i, code in enumerate(range(lo, hi + 1)):
                    if i < len(items):
                        table[code] = _hex_to_unicode(items[i])
            else:
                base = _hex_to_unicode(dst[1:-1])
                for i, code in enumerate(range(lo, hi + 1)):
                    if base:
                        table[code] = base[:-1] + chr(ord(base[-1]) + i)
    return table


class Font:
    def __init__(self, two_byte: bool, code_map: dict[int, str], fallback: str):
        self._two_byte = two_byte
        self._map = code_map
        self._fallback = fallback  # codec name for codes not in the map

    def decode(self, raw: bytes) -> str:
        if self._two_byte:
            out = []
            for i in range(0, len(raw) - 1, 2):
                code = (raw[i] << 8) | raw[i + 1]
                out.append(self._map.get(code, ""))
            return "".join(out)
        out = []
        for byte in raw:
            ch = self._map.get(byte)
            if ch is None:
                ch = bytes([byte]).decode(self._fallback, "replace")
            out.append(ch)
        return "".join(out)


def build_font(font_dict: dict, doc) -> Font:
    """Construct a Font decoder from a /Font dictionary."""
    subtype = str(doc.resolve(font_dict.get("Subtype")) or "")

    # 1. ToUnicode wins when available.
    tounicode = doc.resolve(font_dict.get("ToUnicode"))
    if isinstance(tounicode, Stream):
        try:
            cmap = parse_tounicode(doc.get_stream_bytes(tounicode))
            if cmap:
                return Font(two_byte=_is_two_byte(font_dict, doc), code_map=cmap,
                            fallback="cp1252")
        except Exception:
            pass

    # 2. Type0 without ToUnicode: pass codes through as best we can.
    if subtype == "Type0":
        return Font(two_byte=True, code_map={}, fallback="utf-16-be")

    # 3. Simple font: base encoding + /Differences.
    enc = doc.resolve(font_dict.get("Encoding"))
    base_name = "WinAnsiEncoding"
    differences = None
    if isinstance(enc, (str, Name)):
        base_name = str(enc)
    elif isinstance(enc, dict):
        if "BaseEncoding" in enc:
            base_name = str(doc.resolve(enc["BaseEncoding"]))
        differences = doc.resolve(enc.get("Differences"))

    table = base_table(base_name)
    if isinstance(differences, list):
        code = 0
        for item in differences:
            item = doc.resolve(item)
            if isinstance(item, (int, float)):
                code = int(item)
            elif isinstance(item, (str, Name)):
                table[code] = glyph_to_unicode(str(item))
                code += 1
    return Font(two_byte=False, code_map=table, fallback="cp1252")


def _is_two_byte(font_dict: dict, doc) -> bool:
    subtype = str(doc.resolve(font_dict.get("Subtype")) or "")
    return subtype == "Type0"
