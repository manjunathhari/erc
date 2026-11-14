"""The two channels together: each channel's scores scaled to between 0 and 1, then combined by weight."""
from __future__ import annotations

from ._common import Hit, check_search, ranked


def scaled(hits):
    """Each hit's score as a share of the channel's range. A channel with one hit, or all equal, gives 1."""
    if not hits:
        return {}
    low, high = min(hit.score for hit in hits), max(hit.score for hit in hits)
    return {hit.id: 1.0 if high == low else (hit.score - low) / (high - low) for hit in hits}


class HybridSearch:
    def __init__(self, vector, lexical, w_vector=0.5, w_lexical=0.5):
        if w_vector < 0 or w_lexical < 0 or w_vector + w_lexical <= 0:
            raise ValueError("weights must not be negative, and must not both be zero")
        self.vector, self.lexical = vector, lexical
        self.w_vector, self.w_lexical = float(w_vector), float(w_lexical)

    def add(self, units):
        """Adds to both. A unit the model cannot embed is reported as failed and is still found by its words."""
        units = list(units)
        self.vector.not_yet_held(units)
        self.lexical.not_yet_held(units)
        report = self.vector.add(units)
        self.lexical.add(units)
        return report

    def remove(self, ids):
        """Removes from both. Returns how many of the ids either index held."""
        ids = list(ids)
        held = {id for id in ids if self.vector.status(id) or self.lexical.status(id)}
        self.vector.remove(ids)
        self.lexical.remove(ids)
        return len(held)

    def search(self, text, k, kinds=None, day_from=None, day_to=None, pool=50):
        check_search(k, kinds, day_from, day_to)
        if isinstance(pool, bool) or not isinstance(pool, int) or pool <= 0:
            raise ValueError("pool must be a positive whole number")
        # A channel with weight zero is not asked at all.
        from_vector = self.vector.search(text, pool, kinds, day_from, day_to) if self.w_vector > 0 else []
        from_lexical = self.lexical.search(text, pool, kinds, day_from, day_to) if self.w_lexical > 0 else []
        by_meaning, by_words = scaled(from_vector), scaled(from_lexical)
        kind = {hit.id: hit.kind for hit in from_vector + from_lexical}
        whole = self.w_vector + self.w_lexical
        hits = []
        for id in kind:
            parts = {"vector": by_meaning.get(id, 0.0), "lexical": by_words.get(id, 0.0)}
            fused = (self.w_vector * parts["vector"] + self.w_lexical * parts["lexical"]) / whole
            hits.append(Hit(id, kind[id], fused, parts))
        return ranked(hits, k)
