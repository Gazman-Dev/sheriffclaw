from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]


class LocalSemanticEmbeddingProvider(EmbeddingProvider):
    """Real semantic embeddings using local CPU-based sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("sentence-transformers is not installed. Run: pip install sentence-transformers") from e

        self.model = SentenceTransformer(model_name)
        self._dim = self.model.get_sentence_embedding_dimension()

    @property
    def dim(self) -> int:
        return self._dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Encodes the texts. Depending on version, returns numpy array or tensor.
        embeddings = self.model.encode(texts, convert_to_numpy=False)
        if not isinstance(embeddings, list):
            embeddings = embeddings.tolist()
        return [[float(v) for v in vec] for vec in embeddings]


class DeterministicHashEmbeddingProvider(EmbeddingProvider):
    """Small local embedding for tests/dev; no network calls."""

    def __init__(self, dim: int = 64):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        normalized = (text or "").strip().lower()
        if not normalized:
            return vec
        for token in normalized.split():
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]
