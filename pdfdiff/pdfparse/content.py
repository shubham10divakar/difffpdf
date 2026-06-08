"""Interpret a page content stream into positioned text runs.

We execute just the operators that affect text placement — the graphics-state
stack (q/Q/cm), the text object (BT/ET), positioning (Td/TD/Tm/T*/TL) and the
show operators (Tj/TJ/'/") — tracking the current transformation matrix and the
text matrix so every run carries its page-space (x, y) and effective font size.
Everything else (paths, colours, images) is skipped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .fonts import Font
from .lexer import Keyword, Lexer
from .objects import Name

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


@dataclass
class TextRun:
    text: str
    x: float          # page-space origin
    y: float
    size: float       # effective font size in page units
    font: str


class ContentInterpreter:
    def __init__(self, fonts: dict[str, Font]):
        self.fonts = fonts
        self.runs: list[TextRun] = []

    def run(self, data: bytes) -> list[TextRun]:
        ctm = IDENTITY
        gstack: list[tuple] = []
        font_name = ""
        font_size = 0.0
        tm = lm = IDENTITY
        leading = 0.0
        char_sp = 0.0
        word_sp = 0.0

        ops: list = []
        lex = Lexer(data, 0)
        n = len(data)

        def cur_font() -> Font | None:
            return self.fonts.get(font_name)

        def show(text: str, matrix):
            trm = mat_mul(matrix, ctm)
            scale = math.sqrt(abs(trm[0] * trm[3] - trm[1] * trm[2])) or 1.0
            self.runs.append(TextRun(text, trm[4], trm[5], font_size * scale, font_name))

        def advance(width_text_space):
            nonlocal tm
            tm = mat_mul((1.0, 0.0, 0.0, 1.0, width_text_space, 0.0), tm)

        def text_width(s: str) -> float:
            # No glyph metrics: approximate so multi-run lines keep x order.
            return (0.5 * font_size * len(s)) + char_sp * len(s) + word_sp * s.count(" ")

        while lex.pos < n:
            lex.skip_ws()
            if lex.pos >= n:
                break
            try:
                tok = lex.parse_object()
            except (ValueError, EOFError, IndexError):
                lex.pos += 1
                continue

            if not isinstance(tok, Keyword):
                ops.append(tok)
                continue

            op = tok.value

            if op == "q":
                gstack.append((ctm, font_name, font_size))
            elif op == "Q":
                if gstack:
                    ctm, font_name, font_size = gstack.pop()
            elif op == "cm" and len(ops) == 6:
                ctm = mat_mul(tuple(map(float, ops)), ctm)
            elif op == "BT":
                tm = lm = IDENTITY
            elif op == "ET":
                pass
            elif op == "Tf" and len(ops) == 2:
                font_name = str(ops[0])
                font_size = float(ops[1])
            elif op == "Td" and len(ops) == 2:
                lm = mat_mul((1.0, 0.0, 0.0, 1.0, float(ops[0]), float(ops[1])), lm)
                tm = lm
            elif op == "TD" and len(ops) == 2:
                leading = -float(ops[1])
                lm = mat_mul((1.0, 0.0, 0.0, 1.0, float(ops[0]), float(ops[1])), lm)
                tm = lm
            elif op == "Tm" and len(ops) == 6:
                tm = lm = tuple(map(float, ops))
            elif op == "T*":
                lm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), lm)
                tm = lm
            elif op == "TL" and ops:
                leading = float(ops[-1])
            elif op == "Tc" and ops:
                char_sp = float(ops[-1])
            elif op == "Tw" and ops:
                word_sp = float(ops[-1])
            elif op in ("Tj", "'", '"') and ops:
                if op == "'":
                    lm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), lm)
                    tm = lm
                elif op == '"' and len(ops) == 3:
                    word_sp, char_sp = float(ops[0]), float(ops[1])
                    lm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), lm)
                    tm = lm
                raw = ops[-1]
                if isinstance(raw, bytes):
                    f = cur_font()
                    text = f.decode(raw) if f else raw.decode("cp1252", "replace")
                    show(text, tm)
                    advance(text_width(text))
            elif op == "TJ" and ops and isinstance(ops[0], list):
                f = cur_font()
                parts: list[str] = []
                start_tm = tm
                for el in ops[0]:
                    if isinstance(el, bytes):
                        parts.append(f.decode(el) if f else el.decode("cp1252", "replace"))
                    elif isinstance(el, (int, float)):
                        # Large negative adjustment ≈ an inter-word space.
                        if -el / 1000.0 * font_size > 0.18 * (font_size or 1):
                            parts.append(" ")
                text = "".join(parts)
                show(text, start_tm)
                advance(text_width(text))
            elif op == "BI":
                # Inline image: skip its binary payload entirely (up to 'EI').
                ei = data.find(b"EI", lex.pos)
                lex.pos = (ei + 2) if ei != -1 else n

            ops = []

        return self.runs
