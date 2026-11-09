"""ERC decides which statements supersede which; base 2 writes the verdict into P1.

One record in P1 is one statement (base 3: a restated fact is a new record, linked by metadata.same_claim_as). For one
(entity, relation) group this module builds one ERC Proposition per record with the record's own dates, asks ERC for the
contradicting pairs, and writes back: the earlier statement of each pair becomes `superseded`, its valid_to the later
one's start, its note "superseded by <fact>: ERC <reason>"; a statement ERC leaves standing is `active` with no valid_to.
A relation that is multi-valued gets polarity checks only (a retraction retires the claim; a second value does not).

Called by the structure layer after each filing and by the knowledge layer's forget step after a cascade, so that a
record superseded by something that is later forgotten comes back on its own. Standard library + engram_erc only.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from engram_erc.contracts import Proposition, TimeInterval
from engram_erc.primitives.contradiction import find_contradictions

from .relations import is_multi_valued

U = timezone.utc
VERDICT_VERSION = "verdict-1"


def _day(s):
    try: return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=U) if s else None
    except ValueError: return None


def group_rows(db, subject_id: str, predicate: str) -> list[dict]:
    """The statements of one (entity, relation) group that still have content, oldest first."""
    rows = db.execute("SELECT fact_id, object_value, status, valid_from, valid_to, recorded_at, metadata, note FROM knowledge_records "
                      "WHERE subject_id=? AND predicate=? AND status IN ('active','superseded') AND validation_status='accepted' "
                      "ORDER BY valid_from, recorded_at, fact_id", (subject_id, predicate)).fetchall()
    out = []
    for fid, obj, status, vf, vt, rec, meta, note in rows:
        try: m = json.loads(meta or "{}")
        except ValueError: m = {}
        out.append(dict(fact_id=fid, value=(obj or "").strip().casefold(), status=status, valid_from=vf, valid_to=vt, recorded_at=rec,
                        polarity=bool(m.get("polarity", True)), note=note or ""))
    return out


def decide(rows: list[dict], relation: str, as_of: datetime | None = None) -> dict:
    """ERC's verdict for one group: {fact_id: (superseded_by or None, reason, valid_to or None)}. Pure; writes nothing."""
    as_of = as_of or datetime.now(U)
    functional = not is_multi_valued(relation)
    props, start_of = [], {}
    for r in rows:
        start = _day(r["valid_from"]); start_of[r["fact_id"]] = start
        end = as_of + timedelta(days=1) if start and start <= as_of else None
        vt = TimeInterval(start=start, end=end if end and end > start else None) if start else None
        props.append(Proposition(id=r["fact_id"], subject="s", predicate=relation, object_value=r["value"] or "_", polarity=r["polarity"],
                                 source_refs=(r["fact_id"],), valid_time=vt))
    order = [r["fact_id"] for r in rows]; pos = {f: i for i, f in enumerate(order)}
    verdict = {f: (None, "", None) for f in order}
    if len(props) > 1:
        for c in find_contradictions(props, functional_predicates=frozenset([relation]) if functional else frozenset()):
            old, new = (c.left_id, c.right_id) if pos[c.left_id] < pos[c.right_id] else (c.right_id, c.left_id)
            prev = verdict[old][0]
            if prev and pos[prev] <= pos[new]: continue
            end = start_of[new].date().isoformat() if start_of[new] else None
            verdict[old] = (new, f"ERC {c.reason_code} ({c.certainty.value})", end)
    return verdict


def apply(db, subject_id: str, predicate: str, as_of: datetime | None = None) -> dict:
    """Runs decide() on a group and writes the verdict into P1. Returns {fact_id: new status} for what changed.
    Only rows whose status or valid_to would change are written, so a repeated call is a no-op."""
    rows = group_rows(db, subject_id, predicate)
    if not rows: return {}
    verdict = decide(rows, predicate, as_of)
    changed = {}
    for r in rows:
        new, reason, end = verdict[r["fact_id"]]
        if new:
            status, valid_to, note = "superseded", end or r["valid_to"], f"superseded by {new}: {reason}"
            if valid_to and r["valid_from"] and valid_to < r["valid_from"]: valid_to = r["valid_from"]
        else:
            status, valid_to, note = "active", None, (re.sub(r"^(superseded|replaced) by \S+:?.*$", "", r["note"]).strip() if r["status"] == "superseded" else r["note"])
            if r["status"] == "superseded": note = (note + " reinstated: no live rival (" + VERDICT_VERSION + ")").strip()
        if status != r["status"] or (valid_to or None) != (r["valid_to"] or None):
            db.execute("UPDATE knowledge_records SET status=?, valid_to=?, note=? WHERE fact_id=?", (status, valid_to, note[:300], r["fact_id"]))
            changed[r["fact_id"]] = status
    return changed


def reinstate_after_delete(db, deleted_fact_ids) -> dict:
    """After a cascade: every group that held a record superseded by a now-invalidated fact is re-decided by ERC."""
    changed = {}
    groups = set()
    for fid in deleted_fact_ids:
        for subj, pred in db.execute("SELECT subject_id, predicate FROM knowledge_records WHERE note LIKE ? AND status='superseded'", (f"superseded by {fid}%",)).fetchall():
            if subj and pred: groups.add((subj, pred))
    for subj, pred in groups: changed.update(apply(db, subj, pred))
    return changed


__all__ = ["decide", "apply", "group_rows", "reinstate_after_delete", "VERDICT_VERSION"]
