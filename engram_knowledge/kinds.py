"""Stage 2, Increment 5: entity kinds. The five kinds, the word lists W-A, W-P, W-O and W-T with their plurals, the head word,
and the reading of "our" or "my" + an animal or thing word (steps 1', 10a and 10b).

Frozen specification: claude/engram-stage2-inc5-spec-draft5.md (SHA-256 8f412ee09161b5334858badaca2d081f6f2eb2dba335c5727de30775cc4f7988),
sections 3, 4.1, 5 and 7; contract Amendment 10 (claude/engram-wr-amendment10.md, SHA-256
19b13eebdb6a26b0d1c1174c2cf061086a60bbaefebb9ce27579e41b61207ca0), items 10A1, 10A2 and 10A5. Fixed word lists, matched on whole
words with case ignored. Any change to a list is an amendment. Nothing here reads or writes the store.
"""
from dataclasses import dataclass

from . import relations as R

# ---------- 3.1: the values (K-1, K-8). Only these five count; anything else is no kind (3.4, check 1)
KINDS = ("person", "animal", "place", "organisation", "thing")
NOT_PERSON = ("animal", "place", "organisation", "thing")


def valid(value):
    """3.4, check (1); P-2, P-4, P-5: the value when it is exactly one of the five, otherwise None (no kind)."""
    return value if isinstance(value, str) and value in KINDS else None


# ---------- section 5: the reason texts, exact (D-10a, D-10b). Steps 1', 10a and 10b reuse Increment 2's texts unchanged.
def no_kind(subject):                                                               # 3.5, K-10
    return f"the kind of '{subject}' is not known"


BORROWED = "a borrowed name must be a person's"                                     # section 7

# ---------- 3.3: the word lists, exactly as approved (D-13a, D-13b)
W_A = ("dog puppy pup cat kitten kitty pet bird parrot budgie fish goldfish turtle tortoise rabbit bunny hamster", "guinea pig",
       "mouse rat horse pony snake lizard frog cow goat sheep chicken hen duck")
W_P = ("city town village country state neighbourhood neighborhood street park beach lake river mountain hospital clinic school "
       "college university library museum gym church temple mosque restaurant cafe bar hotel airport station office",)
W_O = ("company firm employer charity club band union government council ministry bank startup",)
W_T = ("car bike bicycle scooter motorbike phone laptop computer tablet camera watch guitar piano violin book novel painting photo "
       "blog website app project screenplay song album game recipe plant house home flat apartment room garden store shop business biz",)


def _entries(parts):
    """The list's entries: single words split on spaces; a part that is a two-word entry ("guinea pig") is kept whole."""
    return tuple(w for p in parts for w in ((p,) if p == "guinea pig" else p.split()))


LISTS = {"animal": _entries(W_A), "place": _entries(W_P), "organisation": _entries(W_O), "thing": _entries(W_T)}

# E-2: plurals by Increment 2's ordinary rule, except these by hand; "biz" has no plural form.
BY_HAND = {"mouse": "mice", "guinea pig": "guinea pigs"}
SAME_PLURAL = {"fish", "sheep", "goldfish"}                                         # the plural is the same word
NO_PLURAL = {"biz"}


def plural(word):
    if word in SAME_PLURAL: return word
    return BY_HAND.get(word) or R._plural(word)


@dataclass(frozen=True)
class Form:
    kind: str         # animal, place, organisation or thing
    word: str         # the listed word ("dog", "guinea pig")
    group: bool       # a plural form: "turtles", "mice", and fish, sheep and goldfish (10b)


FORMS = {}
for _kind, _words in LISTS.items():
    for _w in _words:
        FORMS[_w] = Form(_kind, _w, _w in SAME_PLURAL)
for _kind, _words in LISTS.items():
    for _w in _words:
        if _w not in NO_PLURAL and _w not in SAME_PLURAL: FORMS.setdefault(plural(_w), Form(_kind, _w, True))

DETERMINERS = {"my", "our", "the", "a", "an"}
OWN_KINDS = ("animal", "thing")                                                     # steps 1', 10a and 10b


def _is_name(word):
    """A capitalised word, as Increment 2 reads a relation's name (D1-12.9)."""
    return word[:1].isupper() and word.replace("-", "").replace("'", "").isalpha()


def _form_at(words, i):
    """The listed form starting at words[i], a two-word entry matched as a pair first (O-1): (Form, the next index) or None."""
    pair = " ".join(w.lower() for w in words[i:i + 2])
    if len(words) >= i + 2 and pair in FORMS: return FORMS[pair], i + 2
    if i < len(words) and words[i].lower() in FORMS: return FORMS[words[i].lower()], i + 1
    return None


def head(subject):
    """O-1: the head word of a subject, its last word before any name, after "my", "our", "the", "a" or "an" and any describing
    words of Increment 2's list L6; a two-word entry is matched as a pair before the single last word. Returns the listed Form,
    or None when the head word is on no list (or the subject is a bare name, with no head word)."""
    words = [w for w in R._words(subject) if w != ","]
    if words and words[0].lower() in DETERMINERS: words = words[1:]
    while words and words[0].lower() in R.DESCRIBING: words = words[1:]
    end = len(words)
    while end and _is_name(words[end - 1]): end -= 1
    body = words[:end]
    if not body: return None
    if len(body) >= 2 and " ".join(w.lower() for w in body[-2:]) in FORMS: return FORMS[" ".join(w.lower() for w in body[-2:])]
    return FORMS.get(body[-1].lower())


def kind_of(subject):
    """3.3: the kind the lists give a subject by its head word, or "" when the head word is on no list."""
    f = head(subject)
    return f.kind if f else ""


def our_own(subject):
    """Step 1': "our" + [describing words] + an animal or thing word (W-A, W-T, or a plural). As Increment 2's step 1 reads
    "our" + a person word: the first word after any describing words decides."""
    words = [w for w in R._words(subject) if w != ","]
    if len(words) < 2 or words[0].lower() != "our": return False
    i = 1
    while i < len(words) and words[i].lower() in R.DESCRIBING and not _form_at(words, i): i += 1
    hit = _form_at(words, i)
    return bool(hit) and hit[0].kind in OWN_KINDS


@dataclass(frozen=True)
class Own:
    """Steps 10a and 10b: "my" + [describing words] + an animal or thing word + [a name]."""
    relation: R.Relation    # kind "several" (10a: identity by steps 8a to 8f) or "family" (10b: one group, step 7's pattern)
    kind: str               # animal or thing


def read_own(subject):
    """Steps 10a and 10b. An Own for "my" + [describing words of L6] + a W-A or W-T form + [a name], else None. The name is
    the capitalised words directly after the head word (O-2, as D1-12.9); one lower-case word there is not taken, as
    Increment 2 reads "my sister sara". Anything else after the head word ("my dog and I") is not this step (step 11)."""
    words = R._words(subject)
    if len(words) < 2 or words[0].lower() != "my" or "," in words: return None
    i = 1
    while i < len(words) and words[i].lower() in R.DESCRIBING and not _form_at(words, i): i += 1
    hit = _form_at(words, i)
    if not hit or hit[0].kind not in OWN_KINDS: return None
    form, nxt = hit
    rest = words[nxt:]
    if rest and all(_is_name(w) for w in rest): name = " ".join(rest)
    elif not rest or (len(rest) == 1 and rest[0].isalpha() and rest[0].islower()): name = ""
    else: return None
    written = " ".join(w.lower() for w in words[i:nxt])
    if form.group: return Own(R.Relation("family", written, name), form.kind)        # 10b: "turtles", "goldfish"
    return Own(R.Relation("several", form.word, name), form.kind)                      # 10a: "dog"


def decide(who, writer_kind=None, given=None):
    """3.2 to 3.5 and P-6, for a fact that would create a new entity: the kind fixed by rule or by the lists (carried on the
    resolution, D-9: the list wins silently; a speaker's name is a person), else the writer's valid kind, else a valid kind
    given on approval. None when no kind is decided (3.5: held, nothing stored)."""
    return valid(who.kind) or valid(writer_kind) or valid(given)
