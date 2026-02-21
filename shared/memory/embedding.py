from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class DeterministicHashEmbeddingProvider(EmbeddingProvider):
    """Small local embedding for tests/dev; no network calls."""

    def __init__(self, dim: int = 64):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
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
