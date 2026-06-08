"""PDF object model.

PDF has eight object types. We map them to Python as follows:

  null            -> None
  boolean         -> True / False
  integer / real  -> int / float
  string          -> bytes        (literal "(...)" and hex "<...>")
  name            -> Name          (str subclass, e.g. Name("Font") for /Font)
  array           -> list
  dictionary      -> dict[str, obj]  (keys are the name strings, sans slash)
  stream          -> Stream(dict, raw_bytes)

Indirect references ("12 0 R") become Ref(num, gen) and are resolved lazily by
the document, so we never load more of the file than we need.
"""

from __future__ import annotations

from dataclasses import dataclass


class Name(str):
    """A PDF name like ``/Type``. A ``str`` subclass (value without the slash)
    so it compares equal to plain dict keys, but distinguishable by type."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"/{str.__str__(self)}"


@dataclass(frozen=True)
class Ref:
    """An indirect reference: ``num gen R``."""

    num: int
    gen: int = 0

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"{self.num} {self.gen} R"


@dataclass
class Stream:
    """A stream object: its dictionary plus the raw (still-encoded) bytes.

    Decoding happens on demand via the document so filters and resolution stay
    in one place.
    """

    dict: dict
    raw: bytes

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Stream(len={len(self.raw)}, keys={list(self.dict)})"
