"""The keyword index: finds units by the words they use, scored by BM25.

It keeps, for each unit, which words appear and how many times. It keeps no sentence, no word order and no
verbatim text. Those word counts reveal which words a unit used, so this file is derived personal data and every
deletion must reach it.
"""
from __future__ import annotations

import math
import re

from ._common import AddReport, Hit, Store, allowed, check_search, fingerprint, ranked

_WORD = re.compile(r"[a-z0-9]+")


def words_of(text):
    return _WORD.findall(text.lower())


class LexicalIndex(Store):
    # postings is kept in word order, then unit, with no row numbers: the order words were said in is not stored.
    TABLES = ("CREATE TABLE units(id TEXT PRIMARY KEY, kind TEXT NOT NULL, day TEXT, "
              "digest TEXT NOT NULL, length INTEGER NOT NULL);"
              "CREATE TABLE postings(term TEXT NOT NULL, id TEXT NOT NULL, tf INTEGER NOT NULL, "
              "PRIMARY KEY(term, id)) WITHOUT ROWID;"
              "CREATE INDEX postings_by_unit ON postings(id);")

    def __init__(self, path, k1=1.2, b=0.75):
        self.k1, self.b = float(k1), float(b)
        if not (math.isfinite(self.k1) and self.k1 >= 0) or not 0 <= self.b <= 1:
            raise ValueError("k1 must not be negative and b must lie between 0 and 1")
        super().__init__(path, {"k1": repr(self.k1), "b": repr(self.b), "tokens": "a-z0-9"})

    def add(self, units):
        new, report = self.not_yet_held(list(units)), AddReport()
        with self.db:
            for unit in new:
                words = words_of(unit.text)
                counts = {word: words.count(word) for word in set(words)}
                self.db.execute("INSERT INTO units VALUES(?, ?, ?, ?, ?)",
                                (unit.id, unit.kind, unit.day, fingerprint(unit.text), len(words)))
                self.db.executemany("INSERT INTO postings VALUES(?, ?, ?)",
                                    [(word, unit.id, counts[word]) for word in sorted(counts)])
                report.embedded.append(unit.id)
        return report

    def remove(self, ids):
        removed = 0
        with self.db:
            for id in ids:
                removed += self.db.execute("DELETE FROM units WHERE id = ?", (id,)).rowcount
                self.db.execute("DELETE FROM postings WHERE id = ?", (id,))
        return removed

    def search(self, text, k, kinds=None, day_from=None, day_to=None):
        kinds, first, last = check_search(k, kinds, day_from, day_to)
        if not isinstance(text, str):
            raise ValueError("the question must be text")
        count, total = self.db.execute("SELECT COUNT(*), COALESCE(SUM(length), 0) FROM units").fetchone()
        if not count:
            return []
        average = total / count
        score, about = {}, {}
        for word in dict.fromkeys(words_of(text)):
            rows = self.db.execute("SELECT p.id, p.tf, u.length, u.kind, u.day FROM postings p "
                                   "JOIN units u ON u.id = p.id WHERE p.term = ?", (word,)).fetchall()
            if not rows:
                continue
            # How rare the word is in the whole index. A filter chooses what may be returned and does not change this.
            rarity = math.log(1 + (count - len(rows) + 0.5) / (len(rows) + 0.5))
            for id, tf, length, kind, day in rows:
                gain = rarity * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / average))
                score[id] = score.get(id, 0.0) + gain
                about[id] = (kind, day)
        hits = [Hit(id, about[id][0], value) for id, value in score.items()
                if value > 0 and allowed(about[id][0], about[id][1], kinds, first, last)]
        return ranked(hits, k)
