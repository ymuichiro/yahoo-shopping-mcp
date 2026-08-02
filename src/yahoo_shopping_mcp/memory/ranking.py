from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> list[tuple[str, float]]:
    if k <= 0:
        raise ValueError("k must be positive.")
    scores: dict[str, float] = defaultdict(float)
    for name, ranking in rankings.items():
        weight = 1.0 if weights is None else max(float(weights.get(name, 1.0)), 0.0)
        seen: set[str] = set()
        for rank, item_id in enumerate(ranking, start=1):
            if item_id in seen:
                continue
            seen.add(item_id)
            scores[item_id] += weight / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
