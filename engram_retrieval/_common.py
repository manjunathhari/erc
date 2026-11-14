"""Shared parts: the unit, the hit, the argument checks, and the small file each index keeps.

Nothing here reads an Engram table or imports an Engram or ERC module.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass, field

KINDS = ("sentence", "fact")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class IndexMismatch(Exception):
    """The file was made by another model or with other settings, or is not an index of this kind."""


def check_day(day):
    """A day is written YYYY-MM-DD and must be a real date. None means the day is not known."""
    if day is None:
        return None
    if not isinstance(day, str) or not _DAY.fullmatch(day):
        raise ValueError(f"a day must be written YYYY-MM-DD, or be None: {day!r}")
    datetime.date.fromisoformat(day)
    return day


@dataclass(frozen=True)
class Unit:
    """One thing to index: its id, its kind, its text, and the day it carries or None."""
    id: str
    kind: str
    text: str
    day: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("a unit needs an id")
        if self.kind not in KINDS:
            raise ValueError(f"a unit's kind must be one of {KINDS}: {self.kind!r}")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("a unit needs some text")
        check_day(self.day)


@dataclass(frozen=True)
class Hit:
    """One result. parts is filled by HybridSearch: what each channel gave, scaled to between 0 and 1."""
    id: str
    kind: str
    score: float
    parts: dict | None = None


@dataclass
class AddReport:
    """What an add did: the ids that went in, and the ids the model could not embed."""
    embedded: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def fingerprint(text):
    """Stands in for the text, so an index can tell a unit it already holds without keeping what it said."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_search(k, kinds, day_from, day_to):
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive whole number")
    if kinds is not None:
        kinds = tuple(kinds)
        if any(kind not in KINDS for kind in kinds):
            raise ValueError(f"kinds must be among {KINDS}")
    first, last = check_day(day_from), check_day(day_to)
    if first and last and last < first:
        raise ValueError("the range of days ends before it starts")
    return kinds, first, last


def allowed(kind, day, kinds, first, last):
    """Whether a unit may be returned. A unit with no day is left out of a search limited to days."""
    if kinds is not None and kind not in kinds:
        return False
    if first or last:
        if day is None:
            return False
        if first and day < first:
            return False
        if last and day > last:
            return False
    return True


def ranked(hits, k):
    """Best first. Equal scores are ordered by id, so the same question always gives the same answer."""
    return sorted(hits, key=lambda hit: (-hit.score, hit.id))[:k]


class Store:
    """The file an index keeps. It remembers what made it and refuses to open under anything else.

    Only a path with no file makes a new index. An existing file is never turned into one, even an empty file:
    it is refused as a mismatch and left exactly as it was (Amendment 1, 1A1).

    An index is closed by close(). It is not used in a `with` block (1A8)."""
    TABLES = ""

    def __init__(self, path, settings):
        self.path = str(path)
        settings = {str(key): str(value) for key, value in settings.items()}
        exists = os.path.exists(self.path)
        if exists:
            self._refuse_unless_made_with(settings)
        self.db = sqlite3.connect(self.path)
        if not exists:
            with self.db:
                self.db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);" + self.TABLES)
                self.db.executemany("INSERT INTO meta VALUES(?, ?)", sorted(settings.items()))

    def _refuse_unless_made_with(self, settings):
        """Looks without writing, so a refused file is left exactly as it was."""
        try:
            probe = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            try:
                made_with = dict(probe.execute("SELECT key, value FROM meta").fetchall())
            finally:
                probe.close()
        except sqlite3.DatabaseError as error:
            raise IndexMismatch(f"{self.path} is not an index of this kind ({error})") from None
        if made_with != settings:
            raise IndexMismatch(f"{self.path} was made with {made_with}, not {settings}")

    def close(self):
        self.db.close()

    def __len__(self):
        return self.db.execute("SELECT COUNT(*) FROM units").fetchone()[0]

    def ids(self):
        return [row[0] for row in self.db.execute("SELECT id FROM units ORDER BY id")]

    def status(self, id):
        """'embedded' if the index holds the unit, otherwise None."""
        return "embedded" if self.db.execute("SELECT 1 FROM units WHERE id = ?", (id,)).fetchone() else None

    def not_yet_held(self, units):
        """The units to add. Raises before anything is written if an id is offered with different text."""
        new, seen = [], {}
        for unit in units:
            if not isinstance(unit, Unit):
                raise ValueError("only a Unit can be added")
            mark = fingerprint(unit.text)
            held = self.db.execute("SELECT digest FROM units WHERE id = ?", (unit.id,)).fetchone()
            held = held[0] if held else seen.get(unit.id)
            if held is None:
                seen[unit.id] = mark
                new.append(unit)
            elif held != mark:
                raise ValueError(f"{unit.id} is already held with different text; remove it first")
        return new
