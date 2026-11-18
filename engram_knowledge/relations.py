"""Stage 2, Increment 2: who a fact is about. The word lists L1 to L6 and the reading of a subject's words.

Frozen specification: claude/engram-stage2-inc2-spec-draft7.md (SHA-256 657351b2dfbf3c1d4a7faf4fa8e8a32e1fd7836043a5563abc5f956f6d3160b0),
sections 4 and 5; contract Amendment 8 (8A1, 8A2). Fixed word lists, matched on whole words with case ignored. Any change to a
list is an amendment. Nothing here reads or writes the store.
"""
import re
from dataclasses import dataclass

# ---------- the fixed reason texts (sections 3.1 and 4)
OUR = "'our' does not say whose"                                                    # step 1
INDEFINITE = "an indefinite person is not stored"                                   # step 2
DEMONSTRATIVE = "'these friends' and the like do not say who"                       # step 3
MIDDLE = "a friend, colleague or the like does not say which one"                   # step 5a
GROUP = "a group other than family is not stored"                                   # step 6
DIFFERENT_NAME = "a different name from the one stored for this relation"           # step 7
OTHER_SPEAKERS = "the name belongs to another speaker's relation"                   # section 3.1, step 4


def another(relation):                                                              # step 8a
    return f"may be another {relation}: no name links it to the one already stored"


def already(relation):                                                              # steps 8c and 8f
    return f"may be the {relation} already stored: no name links them"


def not_a_speaker(name):                                                            # step 9
    return f"'{name}' is not a speaker in this conversation"


# ---------- section 5: the word lists, exactly as approved (D1-6a to D1-6h)
def _forms(table):
    """{base: (forms...)} -> {form: base}."""
    return {f: base for base, forms in table.items() for f in forms}


# L2a one-person relations (D1-6b)
ONE_PERSON = _forms({
    "mother": ("mom", "mum", "mother", "mama", "ma", "mommy"), "father": ("dad", "father", "papa", "daddy", "pa"),
    "husband": ("husband", "hubby"), "wife": ("wife",), "partner": ("partner",), "boyfriend": ("boyfriend",),
    "girlfriend": ("girlfriend",), "fiance": ("fiance", "fiancee", "fiancé", "fiancée"),
    "mother-in-law": ("mother-in-law",), "father-in-law": ("father-in-law",)})
# L2b several-person relations (D1-6c)
SEVERAL = _forms({
    "sister": ("sister",), "brother": ("brother",), "son": ("son",), "daughter": ("daughter",), "child": ("child", "kid", "baby"),
    "cousin": ("cousin",), "aunt": ("aunt",), "uncle": ("uncle",), "niece": ("niece",), "nephew": ("nephew",),
    "grandmother": ("grandma", "grandmother", "granny", "nana"), "grandfather": ("grandpa", "grandfather", "grandad"),
    "grandson": ("grandson",), "granddaughter": ("granddaughter",), "sister-in-law": ("sister-in-law",),
    "brother-in-law": ("brother-in-law",), "son-in-law": ("son-in-law",), "daughter-in-law": ("daughter-in-law",)})


def _plural(word):
    if "-in-law" in word: return word.replace("-in-law", "s-in-law")
    if word.endswith("y") and word[-2:-1] not in "aeiou": return word[:-1] + "ies"
    if word.endswith(("s", "ch", "sh", "x")): return word + "es"
    return word + "s"


# L3a family groups (D1-6d): the listed groups, and the plural of any L2b word (one group per speaker, its own entity)
FAMILY = _forms({"family": ("family", "fam", "folks"), "parents": ("parents",), "kids": ("kids", "children"), "siblings": ("siblings",),
                 "grandparents": ("grandparents",), "grandchildren": ("grandkids", "grandchildren"), "relatives": ("relatives",)})
for _form, _base in SEVERAL.items():
    FAMILY.setdefault(_plural(_form), _plural(_base) if _base != "child" else "kids")
# L3b other groups (D1-6e)
OTHER_GROUPS = set("friends buddies pals mates colleagues coworkers co-workers team teammates group crew students classmates "
                   "neighbors neighbours roommates clients people guys girls".split())
# L4 the middle case (D1-6f)
MIDDLE_CASE = set("friend buddy pal mate bestie colleague coworker co-worker neighbor neighbour roommate classmate teammate "
                  "mentor teacher coach doctor therapist student client boss manager".split())
# L5 change words (D1-6g). They count only directly before a relation word (describing words may stand between).
CHANGE = {"ex", "former", "late", "step", "new", "first", "second", "previous"}
# L6 describing words, ignored (D1-6h)
DESCRIBING = set("older oldest elder eldest younger youngest little big baby twin best good close dear beloved lovely sweet own "
                 "current biological adopted old".split())
# L1 indefinite descriptions (D1-6a)
INDEFINITE_STARTS = {"a", "an", "another", "some", "any", "several"}
NUMBER_STARTS = set("one two three four five six seven eight nine ten eleven twelve dozen".split())
PARTITIVE = ("one of", "some of", "a few of", "a couple of", "many of", "most of", "all of", "both of", "two of", "three of")
INDEFINITE_WHOLE = {"someone", "somebody", "anyone", "anybody", "people", "a guy", "a girl"}
DEMONSTRATIVES = {"this", "that", "these", "those"}

# Words that name a person or a group, for steps 1 to 3 ("our" / an indefinite / "this" + a person or group word): every word
# on L2a to L4, and the person words L1 itself names ("guy", "girl", "people") with their other number.
PERSON_WORDS = set(ONE_PERSON) | set(SEVERAL) | set(FAMILY) | OTHER_GROUPS | MIDDLE_CASE | {_plural(w) for w in MIDDLE_CASE} \
    | {"guy", "girl", "people", "person"}
# Words that make a subject a joint subject with the speaker ("my wife and I"): D1-9, it follows the existing rules.
WITH_SPEAKER = {"i", "me", "myself", "we", "us"}


@dataclass(frozen=True)
class Relation:
    """A subject read as "<owner> + [change words] + [describing words] + a person word + [a name]"."""
    kind: str          # one (L2a), several (L2b), family (L3a), group (L3b), middle (L4)
    relation: str      # the base word with any change word: "sister", "mother", "ex husband", "stepmother", "family"
    name: str = ""     # the capitalised words directly after the relation word (D1-12.9), "" when none


def _words(text):
    """The subject's words with their case kept; punctuation next to a word is taken off, a comma is kept as its own word."""
    out = []
    for raw in (text or "").replace("’", "'").split():
        core = raw.strip(".!?;:\"()")
        if core.endswith(","): out += [core[:-1], ","] if core[:-1] else [","]
        elif core: out.append(core)
    return out


def _person(word):
    """(kind, base) for a person word, or None. A change word joined to it ("ex-husband", "stepmom") is split off first."""
    w = word.lower()
    for table, kind in ((ONE_PERSON, "one"), (SEVERAL, "several"), (FAMILY, "family")):
        if w in table: return kind, table[w], ""
    if w in OTHER_GROUPS: return "group", w, ""
    if w in MIDDLE_CASE: return "middle", w, ""
    if w.startswith("ex-") and _person(w[3:]): return _person(w[3:])[:2] + ("ex",)
    if w.startswith("step") and len(w) > 4 and _person(w[4:]) and not _person(w[4:])[2]: return _person(w[4:])[:2] + ("step",)
    return None


def _with_change(changes, base):
    rel = base
    for c in reversed(changes):
        rel = "step" + rel if c == "step" else f"{c} {rel}"
    return rel


def read_relation(words):
    """Steps 4 to 8: the words after "my" (or after "<Name>'s"). Returns a Relation, or None when the words are not a
    relation subject (a thing, "my dog"; a joint subject, "my wife and I": step 11, unchanged)."""
    changes, i = [], 0
    while i < len(words):
        low = words[i].lower()
        hit = _person(low)
        if hit and not (low == "baby" and i + 1 < len(words) and _person(words[i + 1].lower())):   # "my baby brother"
            kind, base, joined = hit
            rest = words[i + 1:]
            if {w.lower() for w in rest} & WITH_SPEAKER: return None                                  # D1-9: a joint subject
            if joined: changes = changes + [joined]
            relation = _with_change(changes, base)
            if kind == "group": return Relation(kind, relation)                                       # a mixed group led by L3b: held whole
            if not rest: return Relation(kind, relation)
            if all(w[:1].isupper() and w.replace("-", "").replace("'", "").isalpha() for w in rest):
                return Relation(kind, relation, " ".join(rest))                                       # D1-12.9: the name
            if all(w.isalpha() and w.islower() for w in rest) and len(rest) == 1:
                return Relation(kind, relation)                                                       # "my sister sara": not taken
            return None
        if low in CHANGE: changes.append(low)
        elif low in DESCRIBING: pass
        else: return None
        i += 1
    return None


def display_name(owner, rel):
    """D1-1, D1-12.1: "<owner>'s <relation>[ <Name>]"."""
    return f"{owner}'s {rel.relation}" + (f" {rel.name}" if rel.name else "")


def _starts(low, phrase):
    return low == phrase or low.startswith(phrase + " ")


def _person_after(words):
    """True if, after any describing words, the next word names a person or a group."""
    for w in words:
        w = w.lower().strip(",")
        if w in DESCRIBING and w not in PERSON_WORDS: continue
        return w in PERSON_WORDS or bool(_person(w))
    return False


def hold_before_relations(subject):
    """Steps 1 to 3. The reason when the subject is held, else ""."""
    words = _words(subject)
    low = " ".join(w.lower() for w in words if w != ",")
    if not words: return ""
    first = words[0].lower()
    if first == "our" and _person_after(words[1:]): return OUR                                        # step 1
    if low in INDEFINITE_WHOLE or " of mine" in f" {low} " or " of ours" in f" {low} ": return INDEFINITE   # step 2
    if any(_starts(low, p + " my") or _starts(low, p + " our") for p in PARTITIVE): return INDEFINITE
    if (first in INDEFINITE_STARTS or first in NUMBER_STARTS or first.isdigit()) and _person_after(words[1:]): return INDEFINITE
    if first in DEMONSTRATIVES and _person_after(words[1:]): return DEMONSTRATIVE                   # step 3
    return ""


_OWNED = re.compile(r"^((?:[A-Z][\w-]*)(?: [A-Z][\w-]*)*)'s (.+)$")


def read_subject(subject):
    """("my", None, Relation) for "my ..."; ("named", Name, Relation) for "<Name>'s ..." (step 9); None otherwise."""
    text = " ".join((subject or "").replace("’", "'").split())
    words = _words(text)
    if len(words) >= 2 and words[0].lower() == "my":
        rel = read_relation(words[1:])
        return ("my", None, rel) if rel else None
    m = _OWNED.match(text)
    if m:
        rel = read_relation(_words(m[2]))
        return ("named", m[1], rel) if rel else None
    return None
