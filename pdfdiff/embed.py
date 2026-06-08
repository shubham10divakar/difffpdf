"""Stage 3 — turn chunks into vectors so we can cheaply match A against B.

Embeddings do the *matching* (which chunk in A corresponds to which in B) and,
when --judge none, also provide the similarity score directly. The semantic
judging of ambiguous pairs happens later in judge.py.

Backends behind one interface:
  local   — sentence-transformers (free, offline; needs the [local] extra/torch)
  openai  — OpenAI embeddings API        (needs OPENAI_API_KEY)
  voyage  — Voyage AI embeddings API     (Anthropic's recommended embeddings;
                                          needs VOYAGE_API_KEY)

Keys come from the environment, never the CLI, so they don't leak into history.
"""

from __future__ import annotations

import os
from typing import Protocol

from .types import Chunk


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbedder:
    """Zero-dependency hashing bag-of-words embedder.

    Hashes tokens into a fixed-width vector with term-frequency weighting, then
    L2-normalises. Cosine of two such vectors is lexical overlap — not true
    semantics, but a solid, install-free way to *match* chunks (the judge adds
    the meaning). Always available, so the tool runs on any Python with no ML
    stack. Good default when torch isn't installed.
    """

    def __init__(self, dim: int = 1024):
        self.name = f"hash:{dim}"
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import math
        import zlib

        import regex as re

        token = re.compile(r"\p{L}+|\p{N}+")
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * self._dim
            for tok in token.findall(t.lower()):
                # Deterministic (process-independent) bucket; sign spreads
                # collisions so unrelated tokens cancel rather than pile up.
                h = zlib.crc32(tok.encode("utf-8"))
                vec[h % self._dim] += 1.0 if (h >> 16) & 1 else -1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm:
                vec = [v / norm for v in vec]
            out.append(vec)
        return out


class LocalEmbedder:
    """sentence-transformers bi-encoder. Lazy-loads the model on first use."""

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        self.name = f"local:{model}"
        self._model_name = model
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise RuntimeError(
                    "Local embeddings need sentence-transformers. Install with: "
                    'pip install "pdfdiff[local]"  (on Python 3.14 use a 3.12 venv '
                    "if torch has no wheel yet), or pick --embed-backend openai/voyage."
                ) from e
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [v.tolist() for v in vecs]


class _HttpEmbedder:
    """Shared logic for OpenAI-compatible / Voyage embedding HTTP APIs."""

    def __init__(self, name, url, model, api_key, key_env):
        if not api_key:
            raise RuntimeError(
                f"{name} embeddings need {key_env} set in the environment."
            )
        self.name = name
        self._url = url
        self._model = model
        self._key = api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        out: list[list[float]] = []
        # Batch to keep request bodies sane on large docs.
        for i in range(0, len(texts), 128):
            batch = texts[i : i + 128]
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "input": batch},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            out.extend(item["embedding"] for item in data)
        return out


def get_embedder(backend: str, model: str | None = None) -> Embedder:
    if backend == "hash":
        return HashEmbedder()
    if backend == "local":
        return LocalEmbedder(model or "all-MiniLM-L6-v2")
    if backend == "openai":
        return _HttpEmbedder(
            name=f"openai:{model or 'text-embedding-3-small'}",
            url="https://api.openai.com/v1/embeddings",
            model=model or "text-embedding-3-small",
            api_key=os.environ.get("OPENAI_API_KEY"),
            key_env="OPENAI_API_KEY",
        )
    if backend == "voyage":
        return _HttpEmbedder(
            name=f"voyage:{model or 'voyage-3'}",
            url="https://api.voyageai.com/v1/embeddings",
            model=model or "voyage-3",
            api_key=os.environ.get("VOYAGE_API_KEY"),
            key_env="VOYAGE_API_KEY",
        )
    raise ValueError(f"unknown embed backend: {backend!r}")


def embed_chunks(chunks: list[Chunk], embedder: Embedder) -> None:
    """Embed in place. No-op for an empty list."""
    if not chunks:
        return
    vecs = embedder.embed([c.text for c in chunks])
    for c, v in zip(chunks, vecs):
        c.embedding = v
