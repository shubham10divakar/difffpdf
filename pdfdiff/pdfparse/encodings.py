"""Character-code -> Unicode mapping for simple PDF fonts.

Most digital PDFs use WinAnsiEncoding, which is byte-compatible with CP1252 —
so we lean on Python's built-in ``cp1252`` codec for the base table and only
need a glyph-name map to apply a font's /Differences overrides. StandardEncoding
and MacRomanEncoding are approximated (Latin-1 / mac_roman) since they're rare
in modern output.
"""

from __future__ import annotations


def base_table(encoding_name: str) -> dict[int, str]:
    """Return a {code: char} table for a named base encoding (codes 0-255)."""
    codec = {
        "WinAnsiEncoding": "cp1252",
        "MacRomanEncoding": "mac_roman",
        "StandardEncoding": "latin-1",
        "PDFDocEncoding": "cp1252",
    }.get(encoding_name, "cp1252")
    table: dict[int, str] = {}
    for code in range(256):
        try:
            table[code] = bytes([code]).decode(codec)
        except UnicodeDecodeError:
            continue
    return table


# Minimal Adobe Glyph List subset — enough to resolve /Differences entries that
# standard fonts actually emit. Anything else falls back to uniXXXX / '?'.
_AGL = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#",
    "dollar": "$", "percent": "%", "ampersand": "&", "quotesingle": "'",
    "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+",
    "comma": ",", "hyphen": "-", "period": ".", "slash": "/",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "colon": ":", "semicolon": ";", "less": "<", "equal": "=",
    "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^",
    "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|",
    "braceright": "}", "asciitilde": "~", "quoteleft": "‘",
    "quoteright": "’", "quotedblleft": "“", "quotedblright": "”",
    "bullet": "•", "endash": "–", "emdash": "—",
    "fi": "fi", "fl": "fl", "trademark": "™", "copyright": "©",
    "registered": "®", "degree": "°", "nbspace": " ",
}


def glyph_to_unicode(name: str) -> str:
    """Map a PostScript glyph name to a string (often one char)."""
    if name in _AGL:
        return _AGL[name]
    # uniXXXX / uXXXXXX forms.
    if name.startswith("uni") and len(name) >= 7:
        try:
            return chr(int(name[3:7], 16))
        except ValueError:
            pass
    if name.startswith("u") and 5 <= len(name) <= 7:
        try:
            return chr(int(name[1:], 16))
        except ValueError:
            pass
    # "gNN" / ".notdef" / unknown -> nothing printable.
    if name in (".notdef", ""):
        return ""
    # Last resort: a single-letter glyph name is its own character.
    return name if len(name) == 1 else ""
