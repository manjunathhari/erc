"""The vector index: finds units by meaning.

The model is handed in from outside: an object with a name, a version, a dim and an embed(texts) function that
returns one vector per text. The index keeps numbers and a fingerprint only, never the text, and keeps no
vectors in working memory between searches.
"""
from __future__ import annotations

import numpy as np

from ._common import AddReport, Hit, Store, allowed, check_search, fingerprint, ranked


class VectorIndex(Store):
    TABLES = ("CREATE TABLE units(id TEXT PRIMARY KEY, kind TEXT NOT NULL, day TEXT, "
              "digest TEXT NOT NULL, vec BLOB NOT NULL);")

    def __init__(self, path, embedder):
        self.embedder = embedder
        self.dim = int(embedder.dim)
        if self.dim <= 0:
            raise ValueError("the model's dim must be positive")
        super().__init__(path, {"model": embedder.name, "version": embedder.version, "dim": self.dim})

    def _unit_vectors(self, texts):
        """One unit-length vector per text, or None where the model fails or returns something unusable."""
        try:
            got = np.asarray(self.embedder.embed(list(texts)), dtype=np.float32)
            if got.ndim != 2 or got.shape[0] != len(texts):
                raise ValueError("the model did not return one vector per text")
        except Exception:
            if len(texts) == 1:
                return [None]
            return [self._unit_vectors([text])[0] for text in texts]
        out = []
        for vector in got:
            length = float(np.linalg.norm(vector)) if vector.shape == (self.dim,) else float("nan")
            usable = np.isfinite(length) and length > 0 and bool(np.all(np.isfinite(vector)))
            out.append(vector / length if usable else None)
        return out

    def add(self, units):
        new, report = self.not_yet_held(list(units)), AddReport()
        if not new:
            return report
        vectors = self._unit_vectors([unit.text for unit in new])
        with self.db:
            for unit, vector in zip(new, vectors):
                if vector is None:
                    report.failed.append(unit.id)
                    continue
                self.db.execute("INSERT INTO units VALUES(?, ?, ?, ?, ?)",
                                (unit.id, unit.kind, unit.day, fingerprint(unit.text), vector.astype(np.float32).tobytes()))
                report.embedded.append(unit.id)
        return report

    def remove(self, ids):
        with self.db:
            removed = sum(self.db.execute("DELETE FROM units WHERE id = ?", (id,)).rowcount for id in ids)
        return removed

    def _load(self):
        """Every unit and its vector, read from the file on each search.

        Nothing is kept between searches (Amendment 1, 1A9), so a change made through another object on the same
        file is always seen, a removal above all (1A2). A cache would need its own numbered amendment."""
        rows = self.db.execute("SELECT id, kind, day, vec FROM units").fetchall()
        matrix = np.frombuffer(b"".join(row[3] for row in rows), dtype=np.float32).reshape(len(rows), self.dim)
        return [row[:3] for row in rows], matrix

    def search(self, text, k, kinds=None, day_from=None, day_to=None):
        kinds, first, last = check_search(k, kinds, day_from, day_to)
        question = self._unit_vectors([text])[0] if isinstance(text, str) and text.strip() else None
        if question is None:
            raise ValueError("the question could not be embedded")
        units, matrix = self._load()
        if not units:
            return []
        scores = matrix @ question
        hits = [Hit(id, kind, float(score)) for (id, kind, day), score in zip(units, scores)
                if allowed(kind, day, kinds, first, last)]
        return ranked(hits, k)
