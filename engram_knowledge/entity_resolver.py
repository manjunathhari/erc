"""Finds which entity a mention refers to. When it is not certain, it says so and never guesses.

Stage 2, Increment 2 (who a fact is about; contract Amendment 8): a relation the speaker describes ("my sister") is an entity of
its own, scoped to the speaker by the metadata keys relation_of (the speaker's entity_id) and relation; a bare name is looked up
first among the speaker's own relations, then among entities that are no one's relation, never through another speaker's
relation. Frozen specification: claude/engram-stage2-inc2-spec-draft7.md, sections 3, 3.1 and 4. The resolver only reads; what
a resolution describes is created by `entity_for` when, and only when, its fact is stored (a held fact creates nothing, D1-12.3).
"""
import re
from dataclasses import dataclass

from .models import Entity, EntityAlias, normalize_name, tidy
from . import relations as R

FIRST_PERSON = {"i", "me", "my", "myself", "user", "the user", "the speaker", "speaker"}
# Small words two different names can share without being alike ("my sister", "my brother").
LITTLE = {"my", "our", "your", "his", "her", "their", "its", "the", "a", "an", "of", "and"}
# Mentions that say nothing of who. "my friend" is no longer here: it is the middle case (step 5a), held with that step's reason.
UNCLEAR = {"he", "she", "they", "them", "him", "her", "his", "their", "it", "we", "us", "our", "you", "your", "someone", "somebody", "friend", "the person", "this person", "narrator", "the narrator"}


@dataclass(frozen=True)
class Resolution:
    status: str  # known, new, ambiguous, unresolved or absent
    name: str = ""
    entity_id: str | None = None
    why: str = ""
    # Stage 2, Increment 2. For a relation: its keys (section 3) and, when its owner has no entity yet, the owner's label
    # (D1-12.4). For any resolution: a name to record as a scoped alias of the entity when its fact is stored (D1-10).
    relation_of: str | None = None
    relation: str = ""
    owner: str = ""
    alias: str = ""


def _has_name(name, sentences):
    pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I)
    return any(normalize_name(s.speaker) == normalize_name(name) or pattern.search(s.text) for s in sentences)


def _bare_name(name):
    """Step 10: a bare name ("Sara", "Rob Smith"): capitalised words only, no possessive. "my dog" and "the hospital" are not (step 11)."""
    words = name.split()
    return bool(words) and all(w[:1].isupper() and "'" not in w and "’" not in w for w in words)


def entity_for(kb, who, sid):
    """The entity a stored fact goes to: the one resolved, or the one the resolution describes, created now. A relation's
    owner is created first when it has no entity yet (D1-12.4); a relation's name becomes a scoped alias (D1-10, D1-12.2)."""
    if who.entity_id:
        if who.alias: kb.add_alias(EntityAlias.create(who.entity_id, who.alias, "sentence", sid))
        return who.entity_id
    if who.relation:
        owner = who.relation_of or kb.add_entity(Entity.create(who.owner, "unknown")).entity_id
        made = kb.add_entity(Entity.create(who.name, "unknown", metadata=dict(relation_of=owner, relation=who.relation)))
    else:
        made = kb.add_entity(Entity.create(who.name, "unknown"))
    if who.alias: kb.add_alias(EntityAlias.create(made.entity_id, who.alias, "sentence", sid))
    return made.entity_id


class EntityResolver:
    def __init__(self, kb):
        self.kb = kb

    # ---------- reading the store (section 3.1)
    def _unscoped(self, key):
        """Entities that are no one's relation, known by this name or one of their aliases, oldest first."""
        rows = self.kb.db.execute(
            """SELECT entity_id FROM entities WHERE normalized_name=? AND json_extract(metadata, '$.relation_of') IS NULL
               UNION SELECT a.entity_id FROM entity_aliases a JOIN entities e ON e.entity_id = a.entity_id
               WHERE a.normalized_alias=? AND json_extract(e.metadata, '$.relation_of') IS NULL""", (key, key)).fetchall()
        ids = {r[0] for r in rows}
        return [r[0] for r in self.kb.db.execute("SELECT entity_id FROM entities ORDER BY created_at, entity_id").fetchall() if r[0] in ids]

    def _relations(self, owner_ids, relation=None):
        """The relation entities of these owners (of this relation identity, when given), oldest first."""
        if not owner_ids: return []
        marks = ",".join("?" * len(owner_ids))
        sql = f"SELECT entity_id FROM entities WHERE json_extract(metadata, '$.relation_of') IN ({marks})"
        args = list(owner_ids)
        if relation is not None: sql, args = sql + " AND json_extract(metadata, '$.relation') = ?", args + [relation]
        return [r[0] for r in self.kb.db.execute(sql + " ORDER BY created_at, entity_id", args).fetchall()]

    def _names(self, entity_id):
        """A relation's own names: its scoped aliases (D1-10). The display name is a label, not a name (D1-1)."""
        return {a.normalized_alias for a in self.kb.aliases(entity_id)}

    def _owner(self, label):
        """The speaker's stable identity (section 3): (entity_id, or None for none yet; the name to show), or "ambiguous"."""
        found = self._unscoped(normalize_name(label))
        if len(found) > 1: return "ambiguous"
        return (found[0], self.kb.entity(found[0]).canonical_name) if found else (None, tidy(label))

    def _speaks_in_chat(self, name, sentences):
        """D1-12.4: the name is the speaker of at least one sentence in the same chat as the source sentence."""
        for s in sentences:
            row = self.kb.db.execute("SELECT chat FROM sentences WHERE sid=?", (s.sid,)).fetchone()
            if row is None: continue
            for (sp,) in self.kb.db.execute("SELECT DISTINCT speaker FROM sentences WHERE chat IS ?", (row[0],)):
                if normalize_name(sp) == normalize_name(name): return True
        return False

    def _similar(self, name):
        """Entities that share a word with this name. These could be the same person, so a person must decide. A relation
        entity never takes part: it is reached only through its own speaker's scope (section 3.1)."""
        words = set(normalize_name(name).split()) - LITTLE
        if not words: return []
        free = "json_extract(e.metadata, '$.relation_of') IS NULL"
        rows = self.kb.db.execute(f"SELECT entity_id, normalized_name FROM entities e WHERE {free}").fetchall() + self.kb.db.execute(
            f"SELECT a.entity_id, a.normalized_alias FROM entity_aliases a JOIN entities e ON e.entity_id = a.entity_id WHERE {free}").fetchall()
        return sorted({r[0] for r in rows if words & set(r[1].split())})

    # ---------- the rules (section 4)
    def resolve(self, mention, sentences):
        name, key = tidy(mention), normalize_name(mention)
        if not key: return Resolution("unresolved", why="no subject")
        speakers = {tidy(s.speaker) for s in sentences}
        if key in FIRST_PERSON:                                                         # step 0
            if len(speakers) != 1: return Resolution("ambiguous", why="first person across different speakers")
            speaker = next(iter(speakers))
            if normalize_name(speaker) in FIRST_PERSON:  # a speaker literally called "User" is a name, not another "I"
                known = self.kb.resolve(speaker)
                return Resolution("known", self.kb.entity(known).canonical_name, known) if known else Resolution("new", speaker)
            return self.resolve(speaker, sentences)
        if key in UNCLEAR: return Resolution("unresolved", why=f"'{name}' does not say who")
        held = R.hold_before_relations(name)                                            # steps 1 to 3
        if held: return Resolution("unresolved", why=held)
        read = R.read_subject(name)
        if read:                                                                        # steps 4 to 9
            how, owner_name, rel = read
            if how == "named" and not self._speaks_in_chat(owner_name, sentences):     # step 9
                return Resolution("unresolved", why=R.not_a_speaker(owner_name))
            if rel.kind == "middle" and not rel.name: return Resolution("unresolved", why=R.MIDDLE)     # step 5a
            if rel.kind == "group": return Resolution("unresolved", why=R.GROUP)        # step 6
            if how == "my" and len(speakers) != 1: return Resolution("ambiguous", name, why="first person across different speakers", relation=rel.relation)
            owner_label = owner_name if how == "named" else next(iter(speakers))
            owner = self._owner(owner_label)
            if owner == "ambiguous": return Resolution("ambiguous", name, why=f"'{tidy(owner_label)}' names more than one known entity", relation=rel.relation)   # D1-12.5
            if not _has_name(name, sentences): return Resolution("absent", why=f"'{name}' is not in its source")   # D1-12.10
            return self._relation(rel, *owner)
        return self._bare(name, key, speakers, sentences)                                # steps 10 and 11

    def _relation(self, rel, owner_id, owner_label):
        """Steps 5b, 7 and 8a to 8f, for one owner. Every existence check looks only at that owner's entities of the same
        relation identity, the same base word and change marker (the clarification of 20:58 and 21:03, resting on 8A2)."""
        stored = self._relations([owner_id], rel.relation) if owner_id else []
        wanted = normalize_name(rel.name)
        new = Resolution("new", R.display_name(owner_label, rel), relation_of=owner_id, relation=rel.relation, owner=owner_label, alias=rel.name)

        def known(eid, alias=""):
            return Resolution("known", self.kb.entity(eid).canonical_name, eid, relation_of=owner_id, relation=rel.relation, alias=alias)

        named = {e: self._names(e) for e in stored}
        same = [e for e, n in named.items() if wanted and wanted in n]
        if len(same) > 1: return Resolution("ambiguous", rel.name, why=f"'{rel.name}' names {len(same)} known entities", relation=rel.relation)
        if rel.kind == "middle":                                                        # step 5b: the name says which one
            return known(same[0]) if same else new
        if rel.kind in ("one", "family"):                                               # step 7: one entity per (speaker, relation)
            if not stored: return new
            eid = stored[0]
            if not wanted or same: return known(eid)
            if not named[eid]: return known(eid, alias=rel.name)                        # a name learned later: an alias, no rename
            return Resolution("unresolved", why=R.DIFFERENT_NAME)
        if not wanted: return Resolution("unresolved", why=R.another(rel.relation)) if stored else new           # 8a
        if same: return known(same[0])                                                  # 8b
        if not stored or all(named.values()): return new                                # 8d, 8e
        return Resolution("unresolved", why=R.already(rel.relation))                    # 8c, 8f

    def _bare(self, name, key, speakers, sentences):
        """Section 3.1. Step 1 scoped, step 2 unscoped; never one search over every alias at once."""
        owners = []
        if len(speakers) == 1:
            label = next(iter(speakers))
            owner = self._owner(label)
            if owner == "ambiguous":   # D1-12.5, strict reading (BF-2, his word of 19:57): every bare name such a speaker says is held
                # The speaker's own name is held by step 2' below, with today's text (the speaker's label leads to two entities).
                if _bare_name(name) and key != normalize_name(label): return Resolution("ambiguous", name, why=f"'{label}' names more than one known entity")
            elif owner[0]:
                owners = [owner[0]]
        scoped = [e for e in self._relations(owners) if key in self._names(e)]
        unscoped = self._unscoped(key)
        if len(scoped) > 1: return Resolution("ambiguous", name, why=f"'{name}' names {len(scoped)} of the speaker's own people")   # 1'
        if len(unscoped) > 1: return Resolution("ambiguous", name, why=f"'{name}' names {len(unscoped)} known entities")          # 2'
        if scoped and unscoped: return Resolution("ambiguous", name, why=f"'{name}' may be the speaker's own relation or someone else")  # 3
        if scoped:                                                                      # 1: the speaker's own relation, by its name
            ent = self.kb.entity(scoped[0])
            return Resolution("known", ent.canonical_name, ent.entity_id, relation_of=ent.metadata.get("relation_of"), relation=ent.metadata.get("relation", ""))
        if unscoped: return Resolution("known", self.kb.entity(unscoped[0]).canonical_name, unscoped[0])                          # 2
        theirs = self.kb.db.execute("SELECT 1 FROM entity_aliases a JOIN entities e ON e.entity_id = a.entity_id WHERE a.normalized_alias=? "
                                    "AND json_extract(e.metadata, '$.relation_of') IS NOT NULL LIMIT 1", (key,)).fetchone()
        if theirs: return Resolution("unresolved", why=R.OTHER_SPEAKERS)                # 4
        if not _has_name(name, sentences): return Resolution("absent", why=f"'{name}' is not in its source")
        if self._similar(name): return Resolution("ambiguous", name, why=f"'{name}' may be someone already known")
        return Resolution("new", name)                                                  # 5, as today
