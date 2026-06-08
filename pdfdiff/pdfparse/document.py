"""Load a PDF into a resolvable object graph and expose its pages.

We locate indirect objects by scanning sequentially for "N G obj" definitions
rather than trusting the xref table's byte offsets. Sequential scanning is far
more robust on hand-written or lightly-corrupted files, and because parsing a
stream object advances the cursor past ``endstream``, we never mis-read an
"N G obj" pattern that happens to occur inside binary stream data.
"""

from __future__ import annotations

import re

from .filters import decode_stream
from .lexer import Lexer
from .objects import Name, Ref, Stream

_OBJ_DEF = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_TRAILER = re.compile(rb"trailer\b")


class PDFParseError(Exception):
    pass


class PDFDocument:
    def __init__(self, data: bytes):
        if not data[:5] == b"%PDF-":
            # Some files have leading junk; tolerate a header within the first KB.
            head = data[:1024].find(b"%PDF-")
            if head == -1:
                raise PDFParseError("not a PDF (no %PDF- header)")
            data = data[head:]
        self.data = data
        self.objects: dict[int, object] = {}   # object number -> parsed value
        self._scan_objects()
        self.root = self._find_root()

    @classmethod
    def from_path(cls, path: str) -> "PDFDocument":
        with open(path, "rb") as f:
            return cls(f.read())

    # -- object table ------------------------------------------------------
    def _scan_objects(self) -> None:
        data = self.data
        pos = 0
        while True:
            m = _OBJ_DEF.search(data, pos)
            if not m:
                break
            num = int(m.group(1))
            lex = Lexer(data, m.end())
            try:
                obj = lex.parse_object()
            except (ValueError, EOFError, IndexError):
                # Skip a malformed definition; resume just past this header.
                pos = m.end()
                continue
            # Later definitions (incremental updates) supersede earlier ones.
            self.objects[num] = obj
            pos = max(lex.pos, m.end())

    def _find_root(self):
        # Prefer an explicit trailer /Root (classic xref) ...
        for m in _TRAILER.finditer(self.data):
            lex = Lexer(self.data, m.end())
            try:
                trailer = lex.parse_object()
            except (ValueError, EOFError, IndexError):
                continue
            if isinstance(trailer, dict) and "Root" in trailer:
                root = self.resolve(trailer["Root"])
                if isinstance(root, dict):
                    return root
        # ... then an xref-stream trailer (object of /Type /XRef with /Root) ...
        for obj in self.objects.values():
            if isinstance(obj, Stream) and obj.dict.get("Type") == "XRef" and "Root" in obj.dict:
                root = self.resolve(obj.dict["Root"])
                if isinstance(root, dict):
                    return root
        # ... finally, any /Type /Catalog object.
        for obj in self.objects.values():
            if isinstance(obj, dict) and obj.get("Type") == "Catalog":
                return obj
        raise PDFParseError("no document catalog (/Root) found")

    # -- resolution & streams ---------------------------------------------
    def resolve(self, obj):
        """Follow indirect references to a concrete value (with cycle guard)."""
        seen = set()
        while isinstance(obj, Ref):
            if obj.num in seen:
                return None
            seen.add(obj.num)
            obj = self.objects.get(obj.num)
        return obj

    def get_stream_bytes(self, stream: Stream) -> bytes:
        """Decode a stream's content through its filter chain."""
        filters = self.resolve(stream.dict.get("Filter"))
        parms = self.resolve(stream.dict.get("DecodeParms") or stream.dict.get("DP"))
        if isinstance(parms, list):
            parms = [self.resolve(p) for p in parms]
        return decode_stream(stream.raw, filters, parms)

    # -- page tree ---------------------------------------------------------
    def pages(self) -> list[dict]:
        """Return page dictionaries in document order, with /Resources,
        /MediaBox and /Rotate inherited from ancestors per the spec."""
        pages_root = self.resolve(self.root.get("Pages"))
        if not isinstance(pages_root, dict):
            # Degenerate file: treat every /Type /Page object as a page.
            return [o for o in self.objects.values()
                    if isinstance(o, dict) and o.get("Type") == "Page"]
        out: list[dict] = []
        self._walk_pages(pages_root, {}, out, set())
        return out

    _INHERITED = ("Resources", "MediaBox", "CropBox", "Rotate")

    def _walk_pages(self, node, inherited, out, seen):
        node = self.resolve(node)
        if not isinstance(node, dict):
            return
        node_id = id(node)
        if node_id in seen:  # guard against cyclic /Kids
            return
        seen.add(node_id)

        merged = dict(inherited)
        for key in self._INHERITED:
            if key in node:
                merged[key] = node[key]

        ntype = node.get("Type")
        kids = self.resolve(node.get("Kids"))
        if ntype == "Pages" or isinstance(kids, list):
            for kid in kids or []:
                self._walk_pages(kid, merged, out, seen)
        else:
            # A leaf page: stitch inherited attributes onto a shallow copy.
            page = dict(node)
            for key, val in merged.items():
                page.setdefault(key, val)
            out.append(page)

    def page_content(self, page: dict) -> bytes:
        """Concatenate a page's content stream(s) into one decoded byte string."""
        contents = self.resolve(page.get("Contents"))
        streams = contents if isinstance(contents, list) else [contents]
        chunks: list[bytes] = []
        for s in streams:
            s = self.resolve(s)
            if isinstance(s, Stream):
                try:
                    chunks.append(self.get_stream_bytes(s))
                except Exception:
                    continue
        # Streams are logically separated by whitespace.
        return b"\n".join(chunks)
