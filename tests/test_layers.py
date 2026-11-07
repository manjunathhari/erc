"""The engine stands alone, and a layer is reached only through the engine's open and forget steps. Each check runs in a fresh
Python process, so nothing is loaded that the check does not load itself."""
import json
import subprocess
import sys

from conftest import ROOT


def run(code):
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_engine_alone_loads_no_layer_and_creates_no_layer_tables(tmp_path):
    db = str(tmp_path / "m.db")
    got = run(f"""
import json, sys, engram_chat as E
m = E.ChatMemory({db!r}); m.open_chat("1:00 pm on 5 March, 2024")
sid = m.add("A", "My dog is called Rex.", date="1:00 pm on 5 March, 2024"); m.close_chat(write_note=False)
gone = m.forget_sentence(sid)
tables = sorted(r[0] for r in m.db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
print(json.dumps(dict(layers=sorted(k for k in sys.modules if k.startswith(("engram_knowledge", "engram_records", "engram_p6", "engram_erc"))),
                      tables=tables, gone=gone["sentences"])))
""")
    assert got["layers"] == []
    assert not [t for t in got["tables"] if t.startswith(("knowledge", "record_", "entit", "review", "state_", "p6_"))]
    assert got["gone"] == 1


def test_a_deletion_is_refused_when_a_layer_holding_data_is_not_loaded(tmp_path):
    db = str(tmp_path / "m.db")
    run(f"""
import json, engram_chat as E
from engram_records import Entity, FactEvidence, FactWithEvidence, KnowledgeBase, KnowledgeFact
m = E.ChatMemory({db!r}); m.open_chat("1:00 pm on 5 March, 2024")
sid = m.add("A", "My dog is called Rex.", date="1:00 pm on 5 March, 2024"); m.close_chat(write_note=False)
kb = KnowledgeBase(m.db); a = kb.add_entity(Entity.create("A", "person"))
f = KnowledgeFact.create(a.entity_id, "owns", "text", "relationship", "explicit", object_value="Rex")
kb.add(FactWithEvidence(f, (FactEvidence.create(f.fact_id, sid),))); m.close(); print(json.dumps(sid))
""")
    got = run(f"""
import json, engram_chat as E
m = E.ChatMemory({db!r})
try:
    m.forget_sentence(1); refused = ""
except RuntimeError as e:
    refused = str(e)
left = m.db.execute("SELECT count(*) FROM sentences").fetchone()[0]
facts = m.db.execute("SELECT count(*) FROM knowledge_records WHERE status='active'").fetchone()[0]
print(json.dumps(dict(refused=refused, sentences=left, facts=facts)))
""")
    assert "knowledge" in got["refused"]
    assert got["sentences"] == 1 and got["facts"] == 1


def test_with_the_layer_loaded_a_deletion_reaches_it(tmp_path):
    db = str(tmp_path / "m.db")
    got = run(f"""
import json, engram_chat as E
from engram_records import Entity, FactEvidence, FactWithEvidence, KnowledgeBase, KnowledgeFact
m = E.ChatMemory({db!r}); m.open_chat("1:00 pm on 5 March, 2024")
sid = m.add("A", "My dog is called Rex.", date="1:00 pm on 5 March, 2024"); m.close_chat(write_note=False)
kb = KnowledgeBase(m.db); a = kb.add_entity(Entity.create("A", "person"))
f = KnowledgeFact.create(a.entity_id, "owns", "text", "relationship", "explicit", object_value="Rex")
kb.add(FactWithEvidence(f, (FactEvidence.create(f.fact_id, sid),)))
m.forget_sentence(sid)
row = m.db.execute("SELECT status, object_value FROM knowledge_records WHERE fact_id=?", (f.fact_id,)).fetchone()
print(json.dumps(dict(status=row[0], value=row[1], problems=kb.integrity_check())))
""")
    assert got == dict(status="invalidated", value=None, problems=[])
