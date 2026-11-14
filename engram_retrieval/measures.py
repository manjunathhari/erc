"""Three measures of a ranked answer: recall at K, mean reciprocal rank, and NDCG."""
from __future__ import annotations

import math


def _positive(k):
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive whole number")


def recall_at_k(ranked, relevant, k):
    """The share of the relevant ids found in the first k."""
    relevant = set(relevant)
    if not relevant:
        raise ValueError("nothing is marked relevant")
    _positive(k)
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr(cases):
    """Mean over questions of 1 / the place of the first relevant id (0 when none is found).
    cases is a list of (ranked ids, relevant ids)."""
    cases = list(cases)
    if not cases:
        raise ValueError("there are no questions to average over")
    total = 0.0
    for ranked, relevant in cases:
        relevant = set(relevant)
        total += next((1 / place for place, id in enumerate(ranked, start=1) if id in relevant), 0.0)
    return total / len(cases)


def ndcg_at_k(ranked, gains, k):
    """How close the first k come to the best possible order. gains gives each id's worth; an id not listed is
    worth nothing. The best order is taken from every id in gains, not only from the ids that were returned."""
    _positive(k)
    found = sum(gains.get(id, 0) / math.log2(place + 1) for place, id in enumerate(ranked[:k], start=1))
    best = sum(gain / math.log2(place + 1) for place, gain in enumerate(sorted(gains.values(), reverse=True)[:k], start=1))
    return found / best if best > 0 else 0.0
