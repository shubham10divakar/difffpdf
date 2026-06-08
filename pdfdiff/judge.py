"""Stage 5 — judge how similar matched pairs are *in meaning*.

Embeddings are good at "these are about the same thing" but weak exactly where
it matters most: negation ("must" vs "must not") scores ~0.97 cosine yet means
the opposite, while a faithful reword scores only moderate cosine yet means the
same. The judge re-scores the ambiguous middle band to fix both.

Backends (selected with --judge):
  local     — sentence-transformers CrossEncoder. Strong similarity scores,
              free/offline. No prose explanation. (default)
  ollama    — local generative LLM. Score + explanation, free, needs Ollama.
  anthropic — Claude. Best score + explanation. Needs ANTHROPIC_API_KEY.
  openai    — GPT. Score + explanation. Needs OPENAI_API_KEY.
  none      — skip judging; the embedding similarity stands.

A judge returns (similarity in 0..1, explanation) per pair. Only pairs whose
embedding similarity falls inside --judge-band reach the judge; the rest keep
their embedding score, which bounds cost on large documents.
"""

from __future__ import annotations

import json
import os
from typing import Protocol


# Shared instruction for the generative judges. We ask for a strict JSON object
# so parsing is deterministic, and we name the failure modes embeddings miss.
_PROMPT = """You compare two text fragments from two versions of a document and \
judge how close they are IN MEANING, ignoring wording, formatting and order.

Return ONLY a JSON object: {{"similarity": <0.0-1.0>, "explanation": "<short>"}}
- 1.0 = identical meaning (even if reworded).
- Lower the score sharply for negation, changed numbers/dates/parties, added or
  removed obligations, or inverted logic — these are material even when the
  wording barely changes.
- "explanation": one short clause naming what changed, or "equivalent".

A: {a}
B: {b}"""


class Judge(Protocol):
    name: str
    gives_explanation: bool

    def judge_batch(self, pairs: list[tuple[str, str]]) -> list[tuple[float, str]]:
        ...


class NoneJudge:
    name = "none"
    gives_explanation = False

    def judge_batch(self, pairs):
        # Caller never sends pairs here (band logic skips judging), but be safe.
        return [(float("nan"), "") for _ in pairs]


class CrossEncoderJudge:
    name = "local:cross-encoder"
    gives_explanation = False

    def __init__(self, model: str = "cross-encoder/stsb-roberta-large"):
        self._model_name = model
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise RuntimeError(
                    "--judge local needs sentence-transformers. Install with: "
                    'pip install "pdfdiff[local]"  (use a Python 3.12 venv if torch '
                    "has no wheel for your version), or pick --judge ollama/anthropic."
                ) from e
            self._model = CrossEncoder(self._model_name)
        return self._model

    def judge_batch(self, pairs):
        if not pairs:
            return []
        scores = self._load().predict(list(pairs))
        out = []
        for s in scores:
            s = float(s)
            # STSb cross-encoders emit ~0..1; clamp defensively.
            s = max(0.0, min(1.0, s))
            out.append((s, ""))
        return out


class _GenerativeJudge:
    """Base for LLM judges: one request per pair, robust JSON parsing."""

    gives_explanation = True

    def _complete(self, a: str, b: str) -> str:
        raise NotImplementedError

    def judge_batch(self, pairs):
        out = []
        for a, b in pairs:
            try:
                raw = self._complete(a, b)
                sim, expl = _parse_judgment(raw)
            except Exception as e:  # never let one pair kill the run
                sim, expl = float("nan"), f"(judge error: {e})"
            out.append((sim, expl))
        return out


class OllamaJudge(_GenerativeJudge):
    def __init__(self, model: str = "llama3.1", host: str | None = None):
        self.name = f"ollama:{model}"
        self._model = model
        self._host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def _complete(self, a, b):
        import httpx

        resp = httpx.post(
            f"{self._host}/api/generate",
            json={
                "model": self._model,
                "prompt": _PROMPT.format(a=a, b=b),
                "format": "json",
                "stream": False,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["response"]


class AnthropicJudge(_GenerativeJudge):
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.name = f"anthropic:{model}"
        self._model = model
        self._key = os.environ.get("ANTHROPIC_API_KEY")
        if not self._key:
            raise RuntimeError("--judge anthropic needs ANTHROPIC_API_KEY set.")

    def _complete(self, a, b):
        import httpx

        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 256,
                "messages": [{"role": "user", "content": _PROMPT.format(a=a, b=b)}],
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


class OpenAIJudge(_GenerativeJudge):
    def __init__(self, model: str = "gpt-4o-mini"):
        self.name = f"openai:{model}"
        self._model = model
        self._key = os.environ.get("OPENAI_API_KEY")
        if not self._key:
            raise RuntimeError("--judge openai needs OPENAI_API_KEY set.")

    def _complete(self, a, b):
        import httpx

        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self._model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": _PROMPT.format(a=a, b=b)}],
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _parse_judgment(raw: str) -> tuple[float, str]:
    """Pull {similarity, explanation} out of a model response, tolerating
    code fences or stray prose around the JSON."""
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    sim = float(data.get("similarity"))
    sim = max(0.0, min(1.0, sim))
    return sim, str(data.get("explanation", "")).strip()


def get_judge(backend: str, model: str | None = None) -> Judge:
    if backend == "none":
        return NoneJudge()
    if backend == "local":
        return CrossEncoderJudge(model or "cross-encoder/stsb-roberta-large")
    if backend == "ollama":
        return OllamaJudge(model or "llama3.1")
    if backend == "anthropic":
        return AnthropicJudge(model or "claude-haiku-4-5-20251001")
    if backend == "openai":
        return OpenAIJudge(model or "gpt-4o-mini")
    raise ValueError(f"unknown judge backend: {backend!r}")
