"""Relations: how a sentence becomes (entity, relation, value, polarity). Base 2 applies this once, when a fact is filed,
so every record in P1 carries a real relation in `predicate` and its polarity in metadata; nothing has to re-read the
sentence later. Moved here from engram_erc_adapter (pass 2), where it ran at read time.

The table is data: a pattern, a relation name, which group is the entity (FIRST = the speaker) and which the value.
First match wins. A sentence no pattern matches keeps base 2's version key as its relation (less linkable, never lost).
"""
from __future__ import annotations

import re
import unicodedata

RELATIONS_VERSION = "relations-1"
FIRST = "__speaker__"

RELATIONS: list[tuple[str, str, int | str, int]] = [
    # preferences (multi-valued, polarity-bearing). "likes-" = the same claim with polarity false (a retraction).
    (r"^I (?:no longer|don'?t|do not) (?:like|enjoy|drink|eat|use|watch|read|play) (.+?)(?: any ?more| any longer)?\.?$", "likes-", FIRST, 1),
    (r"^I (?:stopped|quit|gave up) (?:liking |drinking |eating |using |watching |reading |playing )?(.+?)\.?$", "likes-", FIRST, 1),
    (r"^I used to (?:like|enjoy) (.+?)\.?$", "likes-", FIRST, 1),
    (r"^I (?:really |absolutely )?(?:like|love|enjoy|adore|am a fan of|am fond of) (.+?)\.?$", "likes", FIRST, 1),
    (r"^I prefer (.+?)\.?$", "prefers", FIRST, 1),
    (r"^I (?:dislike|hate|can'?t stand) (.+?)\.?$", "dislikes", FIRST, 1),
    (r"^I (?:usually |always |often )?(?:drink|eat|order|take) (.+?)\.?$", "likes", FIRST, 1),
    (r"^My favou?rite (.+?) is (.+?)\.?$", "favourite", FIRST, "1+2"),
    # plans
    (r"^I (?:plan|am planning|intend|want) to (.+?)\.?$", "plans", FIRST, 1),
    # first-person states (functional)
    (r"^I live in (.+?)\.?$", "lives_in", FIRST, 1),
    (r"^I (?:moved|have moved) to (.+?)\.?$", "lives_in", FIRST, 1),
    (r"^I work (?:at|for) (.+?)\.?$", "works_at", FIRST, 1),
    (r"^I (?:drive|own|have) (?:a |an )?(.+?)\.?$", "owns", FIRST, 1),
    (r"^My (sister|brother|wife|husband|partner|mother|father|son|daughter|boss|manager|doctor|dog|cat) is (?:called |named )?(.+?)\.?$", "rel", FIRST, "1+2"),
    (r"^My (sister|brother|wife|husband|partner|mother|father|son|daughter|boss|manager|doctor)'?s name is (.+?)\.?$", "rel", FIRST, "1+2"),
    # third-person states (functional)
    (r"^(.+?) lives in (.+?)\.?$", "lives_in", 1, 2),
    (r"^(.+?) (?:moved|has moved) to (.+?)\.?$", "lives_in", 1, 2),
    (r"^(.+?) works (?:at|for) (.+?)\.?$", "works_at", 1, 2),
    (r"^(.+?) is (?:now )?(?:the )?(?:CEO|head|manager|director|chairperson|coach|lead) of (.+?)\.?$", "leads", 1, 2),
    (r"^(.+?) is (?:head)?quartered in (.+?)\.?$", "headquarters", 1, 2),
    (r"^The headquarters of (.+?) (?:is|are) (?:located )?in (.+?)\.?$", "headquarters", 1, 2),
    (r"^(.+?) is married to (.+?)\.?$", "spouse", 1, 2),
    (r"^(.+?) is in (.+?)\.?$", "located_in", 1, 2),
    (r"^(.+?) was born in (.+?)\.?$", "birthplace", 1, 2),
    (r"^(.+?) speaks (.+?)\.?$", "speaks", 1, 2),
    (r"^(.+?) (?:drives|owns|has) (?:a |an )?(.+?)\.?$", "owns", 1, 2),
    (r"^(.+?) is (?:a |an )?(.+?) by profession\.?$", "profession", 1, 2),
    (r"^(.+?) is (?:a |an )(.+?)\.?$", "is_a", 1, 2),
    (r"^The capital of (.+?) is (.+?)\.?$", "capital", 1, 2),
    (r"^(.+?)'s (\w+) is (.+?)\.?$", "poss", 1, "2+3"),
]
_RELATIONS = [(re.compile(p, re.I), rel, e, v) for p, rel, e, v in RELATIONS]

# A multi-valued relation holds several values at once: a second value is not a new version of the first.
MULTI_VALUED = frozenset({"likes", "dislikes", "prefers", "plans", "speaks", "owns", "visited", "works_on", "favourite"})
PROFILE_TYPES = ("preference",)
CARRIERS = re.compile(r"^(?:the )?(?:country|city|sport|religion|language|field|position|continent) of ", re.I)

# words in a question that point at a relation (used by the adapter's question-guided walk)
RELATION_WORDS = {"works_at": ("work", "works", "working", "company", "employer", "job"), "headquarters": ("headquartered", "headquarters", "hq", "based"),
                  "located_in": ("state", "country", "region", "located"), "lives_in": ("live", "lives", "living", "city", "where"),
                  "spouse": ("married", "spouse", "wife", "husband", "partner"), "capital": ("capital",), "leads": ("ceo", "head", "leads", "runs"),
                  "birthplace": ("born", "birthplace"), "owns": ("own", "owns", "drive", "drives", "car"), "speaks": ("speak", "speaks", "language"),
                  "profession": ("profession", "job", "do"), "is_a": ("what is", "who is")}


def is_multi_valued(relation: str) -> bool:
    return relation in MULTI_VALUED or relation.startswith(("likes", "dislikes", "prefers", "plans", "favourite"))


def norm(text: str) -> str:
    """Lower-case, no diacritics, no punctuation, no articles, no carrier words ("the country of Italy" -> "italy")."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = CARRIERS.sub("", t.strip())
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower().replace("'s ", " "))
    return " ".join(w for w in t.split() if w not in ("a", "an", "the"))


def relate(sentence: str, speaker: str) -> tuple[str, str, str, bool] | None:
    """(entity, relation, value, polarity) from one sentence, or None when no pattern matches.
    entity and value are normalised; the caller keeps the sentence's own words for display."""
    s = (sentence or "").strip()
    for rx, rel, eg, vg in _RELATIONS:
        m = rx.match(s)
        if not m: continue
        ent = speaker if eg == FIRST else m.group(eg)
        if isinstance(vg, str):  # "1+2": the relation gets the first group, the value the second
            a, b = vg.split("+"); rel = f"{rel}:{norm(m.group(int(a)))}"; val = m.group(int(b))
        else:
            val = m.group(vg)
        pol = not rel.endswith("-")
        return norm(ent), rel.rstrip("-"), norm(val), pol
    return None


def raw_value(sentence: str) -> str | None:
    """The value as written in the sentence (for the word-for-word copy rule), or None when no pattern matches."""
    s = (sentence or "").strip()
    for rx, rel, eg, vg in _RELATIONS:
        m = rx.match(s)
        if m: return m.group(int(vg.split("+")[1]) if isinstance(vg, str) else vg).strip()
    return None


__all__ = ["RELATIONS", "RELATIONS_VERSION", "MULTI_VALUED", "PROFILE_TYPES", "RELATION_WORDS", "FIRST", "is_multi_valued", "norm", "relate", "raw_value"]
