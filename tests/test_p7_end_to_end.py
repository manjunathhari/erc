"""P7 end to end on real data: P6 scores learned from feedback in one memory, packaged, checked, restored into a second memory and
used there. The other P7 tests use hand-built tables; this one uses what the engine, P1, P2.5 feedback and P6 actually write."""
import json

import pytest

import engram_chat as E
from engram_knowledge.feedback import store_feedback
from engram_p6 import AdaptiveScorer, ExperienceRecorder, ModelPersistence
from engram_p7 import (ContextPolicyTransfer, CrossInstallationHarness, DestinationIntelligenceAdapter, IntelligenceExporter,
                       IntelligenceRestorer, ModelCompatibilityValidator)
from engram_records import Entity, FactEvidence, FactWithEvidence, KnowledgeBase, KnowledgeFact

DAY = "1:00 pm on 5 March, 2023"
QUESTION = "What pet does Asha have?"


@pytest.fixture
def source(tmp_path):
    m = E.ChatMemory(str(tmp_path / "source.db"))
    m.open_chat(DAY)
    s1 = m.add("Asha", "I adopted a beagle called Pixel.", date=DAY)
    s2 = m.add("Asha", "I live in Pune.", date=DAY)
    m.close_chat(write_note=False)
    kb = KnowledgeBase(m.db)
    who = kb.add_entity(Entity.create("Asha", "person")).entity_id
    f = KnowledgeFact.create(who, "owns", "text", "relationship", "explicit", object_value="beagle")
    fid = kb.add(FactWithEvidence(f, (FactEvidence.create(f.fact_id, s1),))).fact.fact_id
    ctx = ExperienceRecorder.context_key("pets")
    for n in range(4): store_feedback(m.db, f"fact:{fid}", "helpful", QUESTION, idempotency_key=f"h{n}", context_key=ctx)
    for n in range(3): store_feedback(m.db, f"sentence:{s2}", "irrelevant", QUESTION, idempotency_key=f"i{n}", context_key=ctx)
    snap = AdaptiveScorer(m.db).build_policy(ctx, note="end to end")
    bundle = ModelPersistence(m.db).create_bundle(p63_policy_version=snap.version, p63_context_key=ctx,
                                                  p64_config={"half_life_days": 90, "trend_window_days": 30},
                                                  retrieval_config={"mode": "shadow"}, note="end to end")
    m.ctx, m.fid, m.sids, m.bundle_id = ctx, fid, (s1, s2), bundle.bundle_id
    yield m
    m.close()


@pytest.fixture
def destination(tmp_path):
    m = E.ChatMemory(str(tmp_path / "destination.db"))
    m.open_chat(DAY)
    m.add("Ravi", "My cat is called Mochi.", date=DAY)
    m.close_chat(write_note=False)
    ExperienceRecorder(m.db)  # a destination's own P6, which starts empty
    yield m
    m.close()


def carry(source, destination):
    p71 = IntelligenceExporter(source.db).extract(source.bundle_id)
    p72 = ContextPolicyTransfer().build(p71)
    p73 = ModelCompatibilityValidator().validate(p72, CrossInstallationHarness._make_profile("destination-B"))
    restorer = IntelligenceRestorer(destination.db, "destination-B")
    staged = restorer.restore(p72, p73, imported_by="test", acknowledge_warnings=bool(p73["report"]["warnings"]))
    restorer.activate(staged["transfer_sha256"], activated_by="test", reason="end-to-end test on real P6 data; warnings reviewed", validation_report=p73)
    return p71, p72, p73, restorer


def test_the_package_carries_no_personal_content(source, destination):
    p71, p72, _, _ = carry(source, destination)
    for document in (p71, p72):
        text = json.dumps(document)
        for private in ("Asha", "beagle", "Pixel", "Pune", source.fid) + tuple(f"sentence:{s}" for s in source.sids):
            assert private not in text


def test_the_destination_gets_the_prior_for_that_context_only_and_keeps_its_own_memory(source, destination):
    before = destination.db.execute("SELECT sid, text FROM sentences").fetchall()
    _, _, p73, restorer = carry(source, destination)
    assert p73["report"]["status"].startswith("compatible")
    prior = restorer.get_active_prior(source.ctx)
    assert prior is not None and prior["prior_multiplier"] > 0 and prior["prior_strength"] > 0
    assert restorer.get_active_prior(ExperienceRecorder.context_key("cooking")) is None
    assert destination.db.execute("SELECT sid, text FROM sentences").fetchall() == before


def test_restored_tables_hold_no_sentence_or_fact_references(source, destination):
    carry(source, destination)
    tables = [r[0] for r in destination.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'p7%'")]
    assert tables
    blob = "".join(str(tuple(row)) for t in tables for row in destination.db.execute(f"SELECT * FROM {t}"))
    assert "sentence:" not in blob and "fact:" not in blob


def test_an_inherited_prior_alone_lifts_every_candidate_alike_so_the_order_holds(source, destination):
    _, _, _, restorer = carry(source, destination)
    adapter = DestinationIntelligenceAdapter(restorer, AdaptiveScorer(destination.db), mode="apply")
    ranking = adapter.rank([0, 1], [{"id": "sentence:1"}, {"id": "sentence:2"}], source.ctx)
    assert ranking.indices == ranking.original_indices
    assert {t["source"] for t in ranking.trace} == {"inherited_context_prior"}
    assert len({t["effective_multiplier"] for t in ranking.trace}) == 1


def test_deleting_in_the_destination_still_works_with_p7_present(source, destination):
    carry(source, destination)
    assert destination.forget_sentence(1)["sentences"] == 1


def test_p7_leaves_the_engine_connections_as_they_were(source, destination):
    _, _, _, restorer = carry(source, destination)
    restorer.get_active_prior(source.ctx)
    assert source.db.row_factory is None and destination.db.row_factory is None
    assert type(destination.db.execute("SELECT sid FROM sentences").fetchone()) is tuple
