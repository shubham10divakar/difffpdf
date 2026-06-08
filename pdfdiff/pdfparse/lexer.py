"""PDF tokenizer + object parser.

Parses a single PDF object starting at a byte offset into the Python values
described in objects.py. Used both for indirect object bodies and for content
needs elsewhere. Indirect *definitions* ("N G obj ... endobj") are located by
the document; here we only resolve "N G R" references inside object bodies.
"""

from __future__ import annotations

from .objects import Name, Ref, Stream

WHITESPACE = b"\x00\t\n\f\r "
DELIMITERS = b"()<>[]{}/%"
_NUM_START = b"+-.0123456789"


def _is_ws(c: int) -> bool:
    return c in WHITESPACE


def _is_delim(c: int) -> bool:
    return c in DELIMITERS


class Lexer:
    def __init__(self, buf: bytes, pos: int = 0):
        self.buf = buf
        self.pos = pos
        self.n = len(buf)

    # -- low-level cursor helpers ------------------------------------------
    def skip_ws(self) -> None:
        buf, n = self.buf, self.n
        while self.pos < n:
            c = buf[self.pos]
            if c == 0x25:  # '%' comment runs to end of line
                while self.pos < n and buf[self.pos] not in b"\r\n":
                    self.pos += 1
            elif _is_ws(c):
                self.pos += 1
            else:
                break

    def _read_token(self) -> bytes:
        """Read a bare keyword/number token (stops at ws or delimiter)."""
        start = self.pos
        buf, n = self.buf, self.n
        while self.pos < n and not _is_ws(buf[self.pos]) and not _is_delim(buf[self.pos]):
            self.pos += 1
        return buf[start : self.pos]

    # -- object parsing ----------------------------------------------------
    def parse_object(self):
        self.skip_ws()
        if self.pos >= self.n:
            raise EOFError("unexpected end of PDF object")
        c = self.buf[self.pos]

        if c == 0x2F:  # '/'  name
            return self._read_name()
        if c == 0x28:  # '('  literal string
            return self._read_literal_string()
        if c == 0x3C:  # '<'  hex string or dict
            if self.pos + 1 < self.n and self.buf[self.pos + 1] == 0x3C:
                return self._read_dict_or_stream()
            return self._read_hex_string()
        if c == 0x5B:  # '['  array
            return self._read_array()
        if c in _NUM_START:
            return self._read_number_or_ref()

        # keyword: true / false / null  (or stray data)
        tok = self._read_token()
        if tok == b"true":
            return True
        if tok == b"false":
            return False
        if tok == b"null":
            return None
        if tok == b"":
            # A lone delimiter we don't handle here (e.g. ']' or '>>'): let the
            # container parsers deal with it.
            raise ValueError(f"unexpected byte {self.buf[self.pos]!r} at {self.pos}")
        # Unknown bare keyword — return as a Name-less marker string.
        return Keyword(tok.decode("latin-1"))

    def _read_name(self) -> Name:
        self.pos += 1  # skip '/'
        buf, n = self.buf, self.n
        out = bytearray()
        while self.pos < n:
            c = buf[self.pos]
            if _is_ws(c) or _is_delim(c):
                break
            if c == 0x23 and self.pos + 2 < n:  # '#XX' hex escape
                try:
                    out.append(int(buf[self.pos + 1 : self.pos + 3], 16))
                    self.pos += 3
                    continue
                except ValueError:
                    pass
            out.append(c)
            self.pos += 1
        return Name(out.decode("latin-1"))

    def _read_literal_string(self) -> bytes:
        self.pos += 1  # skip '('
        buf, n = self.buf, self.n
        out = bytearray()
        depth = 1
        while self.pos < n:
            c = buf[self.pos]
            self.pos += 1
            if c == 0x5C:  # backslash escape
                if self.pos >= n:
                    break
                e = buf[self.pos]
                self.pos += 1
                simple = {0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09, 0x62: 0x08, 0x66: 0x0C}
                if e in simple:
                    out.append(simple[e])
                elif e in b"()\\":
                    out.append(e)
                elif 0x30 <= e <= 0x37:  # octal, up to 3 digits
                    octal = bytes([e])
                    for _ in range(2):
                        if self.pos < n and 0x30 <= buf[self.pos] <= 0x37:
                            octal += bytes([buf[self.pos]])
                            self.pos += 1
                    out.append(int(octal, 8) & 0xFF)
                elif e in b"\r\n":  # line continuation
                    if e == 0x0D and self.pos < n and buf[self.pos] == 0x0A:
                        self.pos += 1
                else:
                    out.append(e)
            elif c == 0x28:  # nested '('
                depth += 1
                out.append(c)
            elif c == 0x29:  # ')'
                depth -= 1
                if depth == 0:
                    break
                out.append(c)
            else:
                out.append(c)
        return bytes(out)

    def _read_hex_string(self) -> bytes:
        self.pos += 1  # skip '<'
        buf, n = self.buf, self.n
        hexstr = bytearray()
        while self.pos < n and buf[self.pos] != 0x3E:  # until '>'
            c = buf[self.pos]
            if not _is_ws(c):
                hexstr.append(c)
            self.pos += 1
        self.pos += 1  # skip '>'
        if len(hexstr) % 2:
            hexstr.append(0x30)  # pad nibble
        try:
            return bytes.fromhex(hexstr.decode("latin-1"))
        except ValueError:
            return b""

    def _read_array(self) -> list:
        self.pos += 1  # skip '['
        out = []
        while True:
            self.skip_ws()
            if self.pos >= self.n:
                break
            if self.buf[self.pos] == 0x5D:  # ']'
                self.pos += 1
                break
            out.append(self.parse_object())
        return out

    def _read_dict_or_stream(self):
        self.pos += 2  # skip '<<'
        d: dict = {}
        while True:
            self.skip_ws()
            if self.pos >= self.n:
                break
            if self.buf[self.pos] == 0x3E and self.buf[self.pos + 1 : self.pos + 2] == b">":
                self.pos += 2  # skip '>>'
                break
            key = self.parse_object()
            if not isinstance(key, Name):
                # Malformed dict key; bail to avoid an infinite loop.
                raise ValueError(f"non-name dict key at {self.pos}")
            value = self.parse_object()
            d[str(key)] = value

        # A stream follows if the next keyword is 'stream'.
        save = self.pos
        self.skip_ws()
        if self.buf[self.pos : self.pos + 6] == b"stream":
            self.pos += 6
            # The spec: CRLF or LF after 'stream', never a bare CR.
            if self.buf[self.pos : self.pos + 2] == b"\r\n":
                self.pos += 2
            elif self.buf[self.pos : self.pos + 1] == b"\n":
                self.pos += 1
            start = self.pos
            end = self.buf.find(b"endstream", start)
            if end == -1:
                raise ValueError("stream without endstream")
            raw = self.buf[start:end]
            # Trim the single EOL that precedes 'endstream' if present.
            if raw.endswith(b"\r\n"):
                raw = raw[:-2]
            elif raw.endswith(b"\n") or raw.endswith(b"\r"):
                raw = raw[:-1]
            self.pos = end + len("endstream")
            return Stream(d, raw)

        self.pos = save
        return d

    def _read_number_or_ref(self):
        start = self.pos
        tok = self._read_token()
        try:
            if tok.lstrip(b"+-").isdigit():
                num = int(tok)
            else:
                # Real number; PDF allows leading dot, trailing dot, etc.
                num = float(tok)
                return num
        except ValueError:
            # Not actually a number (e.g. "1.2.3" garbage) — treat as 0.
            return 0

        # Possible "num gen R" reference: look ahead without committing.
        save = self.pos
        self.skip_ws()
        tok2 = self._read_token()
        if tok2.isdigit():
            self.skip_ws()
            tok3 = self._read_token()
            if tok3 == b"R":
                return Ref(num, int(tok2))
        self.pos = save
        return num


class Keyword:
    """A bare keyword token we don't otherwise model (e.g. content operators)."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, Keyword) and other.value == self.value or other == self.value

    def __hash__(self):
        return hash(self.value)

    def __repr__(self):  # pragma: no cover - debug aid
        return f"Keyword({self.value!r})"
