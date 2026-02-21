from __future__ import annotations

from abc import ABC, abstractmethod
import json
from pathlib import Path

import hnswlib
import numpy as np


class SemanticIndex(ABC):
    @abstractmethod
    def upsert(self, topic_id: str, vector: list[float]) -> None: ...

    @abstractmethod
    def search(self, query_vector: list[float], k: int) -> list[tuple[str, float]]: ...

    @abstractmethod
    def save(self) -> None: ...

    @abstractmethod
    def load(self) -> None: ...


class HnswlibSemanticIndex(SemanticIndex):
    def __init__(self, base_dir: Path, dim: int, space: str = "cosine"):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.space = space
        self.index_path = self.base_dir / "index.bin"
        self.meta_path = self.base_dir / "meta.json"
        self.topic_to_int: dict[str, int] = {}
        self.int_to_topic: dict[int, str] = {}
        self.next_id = 0

        self.index = hnswlib.Index(space=self.space, dim=self.dim)
        self._initialized = False

    def _init(self, max_elements: int = 10000) -> None:
        self.index.init_index(max_elements=max_elements, ef_construction=200, M=16, allow_replace_deleted=True)
        self.index.set_ef(100)
        self._initialized = True

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self._init()

    def upsert(self, topic_id: str, vector: list[float]) -> None:
        self._ensure_initialized()
        if topic_id not in self.topic_to_int:
            int_id = self.next_id
            self.next_id += 1
            self.topic_to_int[topic_id] = int_id
            self.int_to_topic[int_id] = topic_id
        int_id = self.topic_to_int[topic_id]
        arr = np.array([vector], dtype=np.float32)
        self.index.add_items(arr, np.array([int_id], dtype=np.int64))

    def search(self, query_vector: list[float], k: int) -> list[tuple[str, float]]:
        if not self._initialized or len(self.topic_to_int) == 0:
            return []
        kk = min(k, len(self.topic_to_int))
        labels, distances = self.index.knn_query(np.array([query_vector], dtype=np.float32), k=kk)
        out: list[tuple[str, float]] = []
        for int_id, distance in zip(labels[0], distances[0]):
            topic_id = self.int_to_topic.get(int(int_id))
            if topic_id is None:
                continue
            score = float(1.0 - distance)
            out.append((topic_id, score))
        return out

    def save(self) -> None:
        if not self._initialized:
            return
        self.index.save_index(str(self.index_path))
        self.meta_path.write_text(
            json.dumps(
                {
                    "dim": self.dim,
                    "space": self.space,
                    "next_id": self.next_id,
                    "topic_to_int": self.topic_to_int,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def load(self) -> None:
        if not self.index_path.exists() or not self.meta_path.exists():
            self._init()
            return
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.dim = int(meta["dim"])
        self.space = str(meta["space"])
        self.next_id = int(meta["next_id"])
        self.topic_to_int = {str(k): int(v) for k, v in meta.get("topic_to_int", {}).items()}
        self.int_to_topic = {v: k for k, v in self.topic_to_int.items()}

        self.index = hnswlib.Index(space=self.space, dim=self.dim)
        self.index.load_index(str(self.index_path), max_elements=max(self.next_id + 1, 10000))
        self.index.set_ef(100)
        self._initialized = True
