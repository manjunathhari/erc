"""P6's step in ChatMemory.forget_sentence: feedback and learned scores that point at a deleted sentence, or at a fact erased with it, go too.

It runs after the knowledge layer's step (order 10), so a fact that lost its last supporting sentence is already marked invalidated.
Moved here from engram_knowledge/feedback.py, so P6 cleans up its own tables; feedback.forget_refs still names the same function.
"""
import json

import engram_chat

LAYER = "learning"
LAYER_SQL = f"CREATE TABLE IF NOT EXISTS engram_layers(layer TEXT PRIMARY KEY); INSERT OR IGNORE INTO engram_layers VALUES('{LAYER}');"


def forget_refs(db, refs):
    """Removes feedback and learned scores for these references. Called when a sentence is deleted."""
    refs = set(refs)
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not refs or "p6_experience_events" not in have: return 0
    gone = 0
    for event_id, target, cand, sel in db.execute("SELECT event_id, target_ref, candidate_refs, selected_refs FROM p6_experience_events").fetchall():
        if target in refs:
            db.execute("DELETE FROM p6_experience_events WHERE event_id=?", (event_id,)); gone += 1
            continue
        c, s = json.loads(cand or "[]"), json.loads(sel or "[]")
        if refs & set(c + s):  # a retrieval that showed it: keep the event, drop the reference
            db.execute("UPDATE p6_experience_events SET candidate_refs=?, selected_refs=? WHERE event_id=?", (json.dumps([x for x in c if x not in refs]), json.dumps([x for x in s if x not in refs]), event_id))
    if "p6_scoring_policies" in have:
        for r in refs: gone += db.execute("DELETE FROM p6_scoring_policies WHERE target_ref=?", (r,)).rowcount
    return gone


def forget_sentence(db, sid: int) -> int:
    """The sentence itself, and every fact the knowledge layer has erased: an erased fact has no content, so nothing may point at it."""
    refs = {f"sentence:{sid}"}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_records'").fetchone():
        refs |= {f"fact:{r[0]}" for r in db.execute("SELECT fact_id FROM knowledge_records WHERE status='invalidated'")}
    return forget_refs(db, refs)


engram_chat.add_forget_step(LAYER, forget_sentence, order=60)
