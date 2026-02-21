from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievalConfig:
    light_alias_k: int = 5
    light_semantic_k: int = 5
    deep_alias_k: int = 20
    deep_semantic_k: int = 20

    alias_boost: float = 0.35
    time_window_boost: float = 0.30

    low_conf_semantic_threshold: float = 0.35
    low_conf_margin: float = 0.05

    deep_expand_top_n: int = 5
    deep_expand_min_weight: float = 0.5
    deep_neighbor_bonus: float = 0.12
