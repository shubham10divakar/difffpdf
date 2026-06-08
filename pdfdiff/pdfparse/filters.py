"""Stream decode filters.

FlateDecode (zlib) covers the overwhelming majority of digital PDFs and is all
the stdlib gives us for free. We also implement ASCII85/ASCIIHex (cheap, pure
Python) and the PNG/TIFF predictors that FlateDecode streams sometimes apply
(notably xref streams). LZW and image-specific filters (DCT/JPX/CCITT) are out
of scope — those are images, which this text extractor ignores.
"""

from __future__ import annotations

import struct
import zlib

from .objects import Name


class FilterError(Exception):
    pass


def _flate_decode(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        # Some writers emit a stray leading/trailing byte or omit the zlib
        # header. Retry raw-deflate and a one-byte-trimmed variant before giving
        # up — this rescues a surprising number of real files.
        for attempt in (data[1:], data[:-1]):
            try:
                return zlib.decompress(attempt)
            except zlib.error:
                pass
        try:
            return zlib.decompressobj(-zlib.MAX_WBITS).decompress(data)
        except zlib.error as e:
            raise FilterError(f"FlateDecode failed: {e}") from e


def _ascii85_decode(data: bytes) -> bytes:
    # Strip a leading "<~" if present; decode up to the "~>" terminator.
    if data[:2] == b"<~":
        data = data[2:]
    end = data.find(b"~>")
    if end != -1:
        data = data[:end]
    import base64

    return base64.a85decode(data, adobe=False, ignorechars=b" \t\r\n\v\f")


def _asciihex_decode(data: bytes) -> bytes:
    end = data.find(b">")
    if end != -1:
        data = data[:end]
    hexstr = bytes(c for c in data if c not in b" \t\r\n\v\f")
    if len(hexstr) % 2:  # odd length: last nibble assumed 0
        hexstr += b"0"
    return bytes.fromhex(hexstr.decode("latin-1"))


def _apply_predictor(data: bytes, params: dict) -> bytes:
    """Undo PNG/TIFF predictors applied before FlateDecode (DecodeParms)."""
    predictor = int(params.get("Predictor", 1))
    if predictor <= 1:
        return data
    colors = int(params.get("Colors", 1))
    bpc = int(params.get("BitsPerComponent", 8))
    columns = int(params.get("Columns", 1))
    bpp = max(1, (colors * bpc + 7) // 8)        # bytes per pixel
    row_len = (colors * bpc * columns + 7) // 8  # bytes per row (no filter tag)

    if predictor == 2:  # TIFF predictor 2
        out = bytearray(data)
        for r in range(0, len(out), row_len):
            row = out[r : r + row_len]
            for i in range(bpp, len(row)):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
            out[r : r + row_len] = row
        return bytes(out)

    # PNG predictors: each row is prefixed by a filter-type byte.
    out = bytearray()
    prev = bytearray(row_len)
    stride = row_len + 1
    for r in range(0, len(data), stride):
        ftype = data[r]
        row = bytearray(data[r + 1 : r + stride])
        if len(row) < row_len:
            row.extend(b"\x00" * (row_len - len(row)))
        for i in range(row_len):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            x = row[i]
            if ftype == 0:
                pass
            elif ftype == 1:
                x += a
            elif ftype == 2:
                x += b
            elif ftype == 3:
                x += (a + b) >> 1
            elif ftype == 4:  # Paeth
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                x += a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            else:
                raise FilterError(f"bad PNG predictor row type {ftype}")
            row[i] = x & 0xFF
        out.extend(row)
        prev = row
    return bytes(out)


_DECODERS = {
    "FlateDecode": _flate_decode,
    "Fl": _flate_decode,
    "ASCII85Decode": _ascii85_decode,
    "A85": _ascii85_decode,
    "ASCIIHexDecode": _asciihex_decode,
    "AHx": _asciihex_decode,
}

# Image/compression filters we knowingly skip — the caller treats the stream as
# opaque (an image), not text.
IMAGE_FILTERS = {"DCTDecode", "JPXDecode", "JBIG2Decode", "CCITTFaxDecode", "LZWDecode"}


def decode_stream(raw: bytes, filters, parms) -> bytes:
    """Apply a filter chain. ``filters``/``parms`` may be a single value or a
    list (PDF allows both). Raises FilterError if an image-only filter is hit.
    """
    if filters is None:
        return raw
    if isinstance(filters, (str, Name)):
        filters = [filters]
    if parms is None or isinstance(parms, dict):
        parms = [parms] * len(filters)
    elif not isinstance(parms, list):
        parms = [parms]
    # Pad parms to match filters.
    parms = list(parms) + [None] * (len(filters) - len(parms))

    data = raw
    for filt, parm in zip(filters, parms):
        name = str(filt)
        if name in IMAGE_FILTERS:
            raise FilterError(f"image/binary filter {name} — not text")
        dec = _DECODERS.get(name)
        if dec is None:
            raise FilterError(f"unsupported filter {name}")
        data = dec(data)
        if isinstance(parm, dict) and int(parm.get("Predictor", 1)) > 1:
            data = _apply_predictor(data, parm)
    return data
