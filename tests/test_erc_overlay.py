"""ERC over the knowledge layers: the gaps found when ERC-1.9 was first fed real P1 facts, and the overlay's promises
(reads only, changes nothing in the engine, respects deletion). Made-up people only."""
import datetime as dt

import pytest

import engram_chat as E
from engram_erc import ConclusionTemplate, PropositionKind, PropositionPattern, ReasoningStatus, RuleDefinition, RuleSet, Variable
from engram_erc.primitives.contradiction import ContradictionCertainty
from engram_knowledge import StateEngine
from engram_records import Entity, EntityAlias, FactEvidence, FactWithEvidence, KnowledgeBase, KnowledgeFact
from erc_overlay import KnowledgeAdapter, Reasoner

DAY = "1:00 pm on 5 March, 2024"
AS_OF = dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc)
X, C, Y = Variable("x"), Variable("c"), Variable("y")
CITY = RuleSet((RuleDefinition("works_in_city", "1", (PropositionPattern(X, "works_at", C), PropositionPattern(C, "located_in", Y)),
                               ConclusionTemplate(X, "works_in_city", Y)),))


class World:
    def __init__(self, path):
        self.m = E.ChatMemory(path)
        self.kb = KnowledgeBase(self.m.db)
        self.engine = StateEngine(self.kb)

    def who(self, name):
        return self.kb.resolve(name) or self.kb.add_entity(Entity.create(name, "person")).entity_id

    def say(self, speaker, text):
        self.m.open_chat(DAY)
        sid = self.m.add(speaker, text, date=DAY)
        self.m.close_chat(write_note=False)
        return sid

    def obs(self, subject, predicate, value, valid_from=None, speaker=None, source_type="explicit", sid=None, plan=False,
            validation="accepted", status="active", valid_to=None):
        sid = sid or self.say(speaker or subject, f"{subject} {predicate} {value}.")
        f = KnowledgeFact.create(self.who(subject), predicate, "text", "plan" if plan else "attribute", source_type, object_value=value,
                                 valid_from=valid_from, valid_to=valid_to, validation_status=validation)
        self.engine.apply_observation(FactWithEvidence(f, (FactEvidence.create(f.fact_id, sid),)))
        if status in ("superseded", "disputed", "retracted"): self.kb.set_status(f.fact_id, status)
        elif status != "active":  # needs_review and invalidated come from deletion; set directly for the test
            self.m.db.execute("UPDATE knowledge_records SET status=? WHERE fact_id=?", (status, f.fact_id)); self.m.db.commit()
        return f.fact_id, sid


@pytest.fixture
def world(tmp_path):
    w = World(str(tmp_path / "m.db"))
    yield w
    w.m.close()


def chain(w):
    """Asha works at Manipal, and Manipal is in Bengaluru: a two-step rule needs the text 'Manipal' to mean the entity Manipal."""
    w.who("Manipal")
    works = w.obs("Asha", "works_at", "Manipal", valid_from="2021")
    w.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    return works


def test_a_text_object_joins_the_entity_it_names_so_a_two_step_rule_fires(world):
    chain(world)
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    derived = [p for p in r.result.propositions if p.kind == PropositionKind.INFERENCE]
    assert [(p.predicate, p.object_value) for p in derived] == [("works_in_city", "Bengaluru")]
    assert r.evaluation.overall_decision.value == "accepted"


def test_as_of_is_respected(world):
    chain(world)
    before = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=dt.datetime(2019, 6, 1, tzinfo=dt.timezone.utc))
    assert not before.result.conclusion_refs
    assert any(l.reason == "starts after as_of" for l in before.adapted.left_out)


def test_a_conflict_p1_sees_is_a_definite_contradiction_in_erc(world):
    world.obs("Asha", "lives_in", "Bengaluru", valid_from="2022")
    world.obs("Asha", "lives_in", "Mysore", valid_from="2022", speaker="Ravi")
    asha = world.kb.resolve("Asha")
    assert world.engine.get_current_state(asha)["lives_in"].conflict
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert [c.certainty for c in r.orchestration.contradictions] == [ContradictionCertainty.DEFINITE]
    assert r.result.status == ReasoningStatus.CONFLICT and r.orchestration.stopped_before_inference


def test_a_value_replaced_by_the_same_speaker_is_history_not_a_contradiction(world):
    world.obs("Asha", "lives_in", "Pune", valid_from="2019")
    world.obs("Asha", "lives_in", "Bengaluru", valid_from="2022")
    asha = world.kb.resolve("Asha")
    assert not world.engine.get_current_state(asha)["lives_in"].conflict
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF, ruleset=CITY)
    assert not [c for c in r.orchestration.contradictions if c.certainty == ContradictionCertainty.DEFINITE]


def test_inferred_facts_are_hypotheses_and_plans_are_left_out(world):
    inferred, _ = world.obs("Asha", "hobby", "chess", source_type="inferred")
    plan, _ = world.obs("Asha", "moved_to", "Delhi", plan=True)
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    kinds = {p.id: p.kind for p in a.request.propositions}
    assert kinds[f"fact:{inferred}"] == PropositionKind.HYPOTHESIS
    assert f"fact:{plan}" not in kinds and (plan, "plan") in [(l.fact_id, l.reason) for l in a.left_out]


def test_one_sentence_counts_once_however_many_facts_it_supports(world):
    sid = world.say("Asha", "I work at Manipal and I play chess.")
    world.obs("Asha", "works_at", "Manipal", sid=sid)
    world.obs("Asha", "hobby", "chess", sid=sid)
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert [e.id for e in a.request.evidence] == [f"sentence:{sid}"]
    assert len(a.request.evidence_links) == 2


def test_a_different_rule_set_or_new_facts_give_a_different_result_id(world):
    chain(world)
    reasoner = Reasoner(world.kb)
    first = reasoner.reason("Asha", ruleset=CITY, as_of=AS_OF).result.id
    other = RuleSet(CITY.rules, version="2")
    assert reasoner.reason("Asha", ruleset=other, as_of=AS_OF).result.id != first
    assert reasoner.reason("Asha", ruleset=CITY, as_of=AS_OF).result.id == first
    world.obs("Asha", "hobby", "chess")
    assert reasoner.reason("Asha", ruleset=CITY, as_of=AS_OF).result.id != first


def test_reasoning_reads_only_and_leaves_the_engine_as_it_was(world):
    chain(world)
    question = "Where does Asha work?"
    found = world.m.find(question)[0]
    changes = world.m.db.total_changes
    r = Reasoner(world.kb)
    r.explain(r.reason("Asha", ruleset=CITY, as_of=AS_OF))
    assert world.m.db.total_changes == changes
    assert world.m.db.row_factory is None
    assert world.m.find(question)[0] == found


def test_after_a_sentence_is_deleted_reasoning_no_longer_uses_it(world):
    (_, sid) = chain(world)
    world.obs("Asha", "hobby", "chess")  # so Asha is still known once that sentence and the fact on it are gone
    assert Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF).result.conclusion_refs
    world.m.forget_sentence(sid)
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert not r.result.conclusion_refs
    assert all(f"sentence:{sid}" not in p.source_refs for p in r.result.propositions)


def test_two_entities_with_one_name_are_refused_not_guessed(world):
    first = world.kb.add_entity(Entity.create("Sam", "person")).entity_id
    other = world.kb.add_entity(Entity.create("Samuel", "person")).entity_id
    world.kb.add_alias(EntityAlias.create(other, "Sam", "manual"))  # two entities now answer to "Sam"
    with pytest.raises(LookupError, match="2 entities"):
        Reasoner(world.kb).reason("Sam", as_of=AS_OF)
    assert Reasoner(world.kb).reason(first, as_of=AS_OF).adapted.request.context_refs == (f"entity:{first}",)


def test_explain_shows_the_conclusion_and_the_sentences_under_it(world):
    chain(world)
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", ruleset=CITY, as_of=AS_OF))
    text = "\n".join(lines)
    assert "conclusion: Asha works_in_city Bengaluru -> accepted" in text
    assert '"Asha works_at Manipal."' in text and '"Manipal located_in Bengaluru."' in text


# ---------- step 1: the fact-state gate (claude/erc-adapter-step1-eng-review.md) ----------
from engram_erc import EvidenceRelation, TimeInterval
from erc_overlay.knowledge import LeftOut, map_state

# The handover's table, as data: each row is checked against the adapter's mapping, so the document, the test and the code
# are one list. (status, validation, source) -> (action, kind or None)
HANDOVER_TABLE = [
    (("active", "accepted", "explicit"), ("send", PropositionKind.ASSERTION)),
    (("active", "accepted", "inferred"), ("send", PropositionKind.HYPOTHESIS)),
    (("active", "pending", "explicit"), ("send", PropositionKind.HYPOTHESIS)),
    (("active", "pending", "inferred"), ("send", PropositionKind.HYPOTHESIS)),
    (("needs_review", "accepted", "explicit"), ("send", PropositionKind.HYPOTHESIS)),
    (("needs_review", "pending", "explicit"), ("send", PropositionKind.HYPOTHESIS)),
    (("needs_review", "accepted", "inferred"), ("send", PropositionKind.HYPOTHESIS)),
    (("disputed", "accepted", "explicit"), ("leave_out", None)),
    (("disputed", "pending", "inferred"), ("leave_out", None)),
    (("superseded", "accepted", "explicit"), ("history", PropositionKind.ASSERTION)),
    (("superseded", "pending", "explicit"), ("history", PropositionKind.HYPOTHESIS)),
    (("superseded", "accepted", "inferred"), ("history", PropositionKind.HYPOTHESIS)),
    (("active", "rejected", "explicit"), ("leave_out", None)),
    (("superseded", "rejected", "inferred"), ("leave_out", None)),
    (("retracted", "accepted", "explicit"), ("leave_out", None)),
    (("invalidated", "accepted", "explicit"), ("leave_out", None)),
]


def _state_links(a, fid):
    return [l.relation for l in a.request.evidence_links if l.evidence_id == f"state:{fid}" and l.proposition_id == f"fact:{fid}"]


def _sentence_links(a, fid):
    return [l.relation for l in a.request.evidence_links if l.evidence_id.startswith("sentence:") and l.proposition_id == f"fact:{fid}"]


@pytest.mark.parametrize("state,expected", HANDOVER_TABLE)
def test_every_row_of_the_handover_table_maps_as_written(state, expected):
    rule = map_state(*state)
    assert (rule.action, rule.kind) == expected
    if rule.action == "leave_out": assert rule.reason and rule.needs
    if rule.kind == PropositionKind.HYPOTHESIS: assert rule.state_record
    if rule.kind == PropositionKind.ASSERTION: assert not rule.state_record


@pytest.mark.parametrize("state", [("active", "accepted", "guessed"), ("active", "unknown", "explicit"), ("archived", "accepted", "explicit")])
def test_a_combination_not_in_the_table_is_left_out_never_sent(state):
    rule = map_state(*state)
    assert rule.action == "leave_out" and rule.kind is None
    assert rule.reason == "unmapped state" and rule.needs == "mapping update"


def test_an_accepted_explicit_fact_is_an_assertion_with_no_state_record_and_can_be_accepted(world):
    works, _ = chain(world)
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert not any(e.id.startswith("state:") for e in a.request.evidence)
    assert _sentence_links(a, works) == [EvidenceRelation.SUPPORTS]
    assert Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF).evaluation.overall_decision.value == "accepted"


@pytest.mark.parametrize("how", [dict(validation="pending"), dict(status="needs_review"), dict(source_type="inferred")])
def test_an_unchecked_fact_keeps_its_sentence_as_support_and_adds_a_qualifying_state_record(world, how):
    world.who("Manipal")
    works, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2021", **how)
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert _sentence_links(a, works) == [EvidenceRelation.SUPPORTS]
    assert _state_links(a, works) == [EvidenceRelation.QUALIFIES]
    rec = next(e for e in a.request.evidence if e.id == f"state:{works}")
    assert rec.metadata["status"] in ("active", "needs_review") and rec.metadata["validation_status"] in ("accepted", "pending")
    assert rec.metadata["source_type"] in ("explicit", "inferred") and rec.metadata["adapter_control"] is True
    assert {p.id: p.kind for p in a.request.propositions}[f"fact:{works}"] == PropositionKind.HYPOTHESIS


@pytest.mark.parametrize("how", [dict(validation="pending"), dict(status="needs_review"), dict(source_type="inferred")])
def test_an_unchecked_fact_can_only_ever_be_provisional_never_accepted(world, how):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021", **how)
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert r.result.conclusion_refs, "the rule still fires"
    assert r.evaluation.overall_decision.value == "provisional"
    ev = r.evaluation.evaluations[0]
    assert "QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION" in ev.reasons and ev.escalation.value == "review"


def test_the_state_record_is_never_counted_as_corroboration(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021", validation="pending")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    ev = r.evaluation.evaluations[0]
    assert ev.supporting_source_count == 2 and ev.qualifying_source_count == 1  # one sentence per leaf; the record adds no support


def test_a_disputed_fact_is_left_out_with_a_diagnostic_and_never_becomes_a_proposition(world):
    fid, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2021", status="disputed")
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert f"fact:{fid}" not in {p.id for p in a.request.propositions}
    out = next(l for l in a.left_out if l.fact_id == fid)
    assert isinstance(out, LeftOut) and out.reason == "disputed: needs resolution" and out.needs == "resolution"
    assert out.state == {"status": "disputed", "validation_status": "accepted", "source_type": "explicit"}


def test_a_superseded_fact_with_an_end_date_is_history_not_current(world):
    old, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019", valid_to="2021", status="superseded")
    world.obs("Asha", "lives_in", "Bengaluru", valid_from="2022")
    # asked today: ended before as_of, so left out of the present question (step 1A), and not a definite contradiction
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert f"fact:{old}" not in {p.id for p in a.request.propositions}
    assert next(l for l in a.left_out if l.fact_id == old).reason == "ended before as_of"
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF)
    assert not [c for c in r.orchestration.contradictions if c.certainty == ContradictionCertainty.DEFINITE]
    # asked as of 2020: sent as history, with the dates Engram holds, marked superseded
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=dt.datetime(2020, 6, 1, tzinfo=dt.timezone.utc))
    props = {p.id: p for p in a.request.propositions}
    t = props[f"fact:{old}"].valid_time
    assert t.start == dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc) and t.end == dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc)
    assert props[f"fact:{old}"].qualifiers["status"] == "superseded"


def test_a_superseded_fact_with_no_end_date_is_left_out_not_given_one(world):
    old, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019", status="superseded")
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert f"fact:{old}" not in {p.id for p in a.request.propositions}
    out = next(l for l in a.left_out if l.fact_id == old)
    assert out.reason == "superseded: end date unknown" and out.needs == "date"


def test_a_rejected_fact_is_left_out_with_its_reason(world):
    fid, _ = world.obs("Asha", "works_at", "Manipal", validation="rejected")
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    assert f"fact:{fid}" not in {p.id for p in a.request.propositions}
    assert next(l for l in a.left_out if l.fact_id == fid).reason == "validation rejected"


def test_explain_names_every_left_out_fact_its_state_and_what_it_needs(world):
    chain(world)
    fid, _ = world.obs("Asha", "hobby", "chess", status="disputed")
    r = Reasoner(world.kb)
    text = "\n".join(r.explain(r.reason("Asha", ruleset=CITY, as_of=AS_OF)))
    assert f"left out: fact {fid} (disputed: needs resolution; status disputed, validation accepted, source explicit; needs resolution)" in text


def test_changing_a_facts_validation_status_changes_the_request_id(world):
    works, _ = chain(world)
    adapter = KnowledgeAdapter(world.kb)
    first = adapter.request_for("Asha", as_of=AS_OF).request.id
    world.kb.set_validation(works, "pending")
    assert adapter.request_for("Asha", as_of=AS_OF).request.id != first
    world.kb.set_validation(works, "accepted")
    assert adapter.request_for("Asha", as_of=AS_OF).request.id == first


# ---------- step 1A: eligibility decided inside the walk; one point in time (claude/erc-adapter-step1-eng-review.md, audit) ----------
from engram_knowledge.models import SOURCE_TYPES, STATUSES, VALIDATION


def expected_rule(status, validation, source):
    """The policy written out independently of STATE_RULES, so the test is not the table checking itself."""
    if validation == "rejected": return ("leave_out", None)
    if status in ("disputed", "retracted", "invalidated"): return ("leave_out", None)
    checked = validation == "accepted" and source == "explicit"
    if status == "superseded": return ("history", PropositionKind.ASSERTION if checked else PropositionKind.HYPOTHESIS)
    if status == "active": return ("send", PropositionKind.ASSERTION if checked else PropositionKind.HYPOTHESIS)
    if status == "needs_review": return ("send", PropositionKind.HYPOTHESIS)
    raise AssertionError(f"the policy has no row for {status!r}: add it here and in STATE_RULES")


ALL_STATES = [(s, v, t) for s in STATUSES for v in VALIDATION for t in SOURCE_TYPES]
assert len(ALL_STATES) == 36


@pytest.mark.parametrize("state", ALL_STATES)
def test_all_36_engram_states_map_to_the_independently_written_policy(state):
    rule = map_state(*state)
    assert (rule.action, rule.kind) == expected_rule(*state)
    assert rule.state_record == (rule.kind == PropositionKind.HYPOTHESIS)


def _reaches_manipal(w):
    a = KnowledgeAdapter(w.kb).request_for("Asha", as_of=AS_OF)
    return [p for p in a.request.propositions if p.subject == w.kb.resolve("Manipal")], a


@pytest.mark.parametrize("how", [dict(status="disputed"), dict(validation="rejected"), dict(plan=True),
                                 dict(status="superseded", valid_from="2019", valid_to="2021"), dict(valid_from="2030")])
def test_an_excluded_fact_cannot_bridge_the_walk_to_another_entity(world, how):
    world.who("Manipal")
    bridge, _ = world.obs("Asha", "works_at", "Manipal", **how)
    world.obs("Manipal", "located_in", "Bengaluru")  # reachable only through the excluded fact
    manipal, a = _reaches_manipal(world)
    assert manipal == []
    assert bridge in {l.fact_id for l in a.left_out}
    assert world.kb.resolve("Manipal") not in {p.subject for p in a.request.propositions}


def test_an_eligible_fact_still_bridges_the_walk(world):
    chain(world)
    manipal, _ = _reaches_manipal(world)
    assert [(p.predicate, p.object_value) for p in manipal] == [("located_in", "Bengaluru")]


def test_a_fact_that_ended_before_as_of_is_left_out_of_a_present_question(world):
    world.who("Manipal")
    old, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2019", valid_to="2021", status="superseded")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2019")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert not r.result.conclusion_refs, "history must not leak into a present conclusion"
    out = next(l for l in r.adapted.left_out if l.fact_id == old)
    assert out.reason == "ended before as_of" and out.needs == "a past as_of" and out.state["status"] == "superseded"


def test_the_same_history_answers_a_question_asked_as_of_2020_when_both_premises_are_dated(world):
    world.who("Manipal")
    old, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2019", valid_to="2021", status="superseded")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=dt.datetime(2020, 6, 1, tzinfo=dt.timezone.utc))
    props = {p.id: p for p in r.result.propositions}
    assert f"fact:{old}" in props and props[f"fact:{old}"].qualifiers["status"] == "superseded"
    derived = [p for p in r.result.propositions if p.kind == PropositionKind.INFERENCE]
    assert [(p.predicate, p.object_value) for p in derived] == [("works_in_city", "Bengaluru")]
    assert r.evaluation.overall_decision.value == "accepted"


def test_a_2020_conclusion_that_rests_on_an_undated_fact_is_provisional_not_established(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2019", valid_to="2021", status="superseded")
    located, _ = world.obs("Manipal", "located_in", "Bengaluru")  # no date: ERC cannot establish it held in 2020
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=dt.datetime(2020, 6, 1, tzinfo=dt.timezone.utc))
    assert r.result.conclusion_refs
    ev = r.evaluation.evaluations[0]
    assert ev.decision.value == "provisional" and "QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION" in ev.reasons
    assert any(e.id == f"state:{located}" and e.metadata["valid_time"] == "unknown" for e in r.adapted.request.evidence)


def test_a_current_fact_known_only_since_2024_does_not_answer_a_2020_question(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2019", valid_to="2021", status="superseded")
    located, _ = world.obs("Manipal", "located_in", "Bengaluru", valid_from="2024")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=dt.datetime(2020, 6, 1, tzinfo=dt.timezone.utc))
    assert not r.result.conclusion_refs
    assert next(l for l in r.adapted.left_out if l.fact_id == located).reason == "starts after as_of"


def test_an_undated_fact_is_included_but_marked_time_unknown_never_current(world):
    fid, _ = world.obs("Asha", "admires", "Ramanujan")  # no state slot: no period, no dates
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    p = {p.id: p for p in a.request.propositions}[f"fact:{fid}"]
    assert p.valid_time is None and p.qualifiers["valid_time"] == "unknown"


def test_explain_shows_each_included_facts_state_and_kind(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021", validation="pending")
    world.obs("Manipal", "located_in", "Bengaluru")
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", ruleset=CITY, as_of=AS_OF))
    i = lines.index("  because: Asha works_at Manipal")
    assert lines[i + 1] == "    state: status active, validation pending, source explicit; sent as hypothesis with a qualifying state record (validation pending); valid 2021-01-01 to 2024-03-06"
    assert lines[lines.index("  because: Manipal located_in Bengaluru") + 1] == "    state: status active, validation accepted, source explicit; sent as assertion with a qualifying state record (valid time unknown); valid time unknown"
    assert "fact: Asha works_at Manipal; state: status active, validation pending, source explicit; sent as hypothesis with a qualifying state record (validation pending); valid 2021-01-01 to 2024-03-06" in lines


# ---------- 1A follow-up: unknown time is qualifying evidence; excluded facts cannot alter eligible periods ----------
def _conclusion(r):
    return r.evaluation.evaluations[0]


def test_two_dated_compatible_premises_can_be_accepted(world):
    chain(world)
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert _conclusion(r).decision.value == "accepted"
    assert not any(e.id.startswith("state:") for e in r.adapted.request.evidence)


@pytest.mark.parametrize("works_dated", [True, False], ids=["works_at stated 2021", "works_at dated only by when it was said"])
def test_a_conclusion_resting_on_an_undated_premise_is_provisional_and_names_the_premise(world, works_dated):
    """located_in is no P1 slot, so with no stated date it has no valid time. works_at is a slot: P1 dates it from when it was said
    if nothing is stated, so it is never undated; the undated premise is always the location."""
    world.who("Manipal")
    works, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2021" if works_dated else None)
    located, _ = world.obs("Manipal", "located_in", "Bengaluru")
    r = Reasoner(world.kb)
    run = r.reason("Asha", ruleset=CITY, as_of=AS_OF)
    ev = _conclusion(run)
    assert ev.decision.value == "provisional" and "QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION" in ev.reasons
    assert run.evaluation.overall_decision.value == "provisional"
    recs = {e.id: e for e in run.adapted.request.evidence if e.id.startswith("state:")}
    assert set(recs) == {f"state:{located}"}, "only the undated premise carries a record"
    assert recs[f"state:{located}"].metadata["valid_time"] == "unknown" and recs[f"state:{located}"].metadata["qualified_for"] == ("valid time unknown",)
    props = {p.id: p for p in run.result.propositions}
    assert props[f"fact:{works}"].valid_time is not None
    lines = r.explain(run)
    i = lines.index(f"  because: {r._claim(props[f'fact:{located}'])}")
    assert lines[i + 1] == "    state: status active, validation accepted, source explicit; sent as assertion with a qualifying state record (valid time unknown); valid time unknown"


def test_a_slot_value_dated_only_by_when_it_was_said_conflicts_with_a_dated_one_and_is_not_resolved(world):
    world.obs("Asha", "lives_in", "Bengaluru", valid_from="2022")
    other, _ = world.obs("Asha", "lives_in", "Mysore", speaker="Ravi")  # no date; P1 dates it from when it was said
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert [c.certainty for c in r.orchestration.contradictions] == [ContradictionCertainty.DEFINITE]
    assert r.result.status == ReasoningStatus.CONFLICT


def test_a_disputed_closing_event_cannot_end_an_eligible_facts_period(world):
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    closing, _ = world.obs("Asha", "left_job", "Hospital Pune", valid_from="2021", speaker="Ravi", status="disputed")
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=dt.datetime(2023, 6, 1, tzinfo=dt.timezone.utc))
    props = {p.id: p for p in a.request.propositions}
    assert f"fact:{pune}" in props, "the active fact stays eligible"
    assert props[f"fact:{pune}"].valid_time.end > dt.datetime(2023, 6, 1, tzinfo=dt.timezone.utc)
    assert next(l for l in a.left_out if l.fact_id == closing).reason == "disputed: needs resolution"
    # P1 itself still sees the closing event by default: the adapter asked for periods without disputed facts, nothing else changed
    assert world.engine.get_history(world.kb.resolve("Asha"), "works_at")["periods"][0].end == "2021"


# ---------- 1A follow-up 2: only accepted observations set period boundaries ----------
AT_2023 = dt.datetime(2023, 6, 1, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("how", [dict(validation="pending"), dict(status="needs_review")], ids=["pending", "needs_review"])
def test_an_unaccepted_closing_event_cannot_end_an_accepted_facts_period_but_still_reaches_erc_as_a_hypothesis(world, how):
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    closing, _ = world.obs("Asha", "left_job", "Hospital Pune", valid_from="2021", speaker="Ravi", **how)
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AT_2023)
    props = {p.id: p for p in a.request.propositions}
    assert f"fact:{pune}" in props and props[f"fact:{pune}"].valid_time.end > AT_2023, "the accepted fact stays eligible and open"
    assert props[f"fact:{closing}"].kind == PropositionKind.HYPOTHESIS, "the closing event is still sent, as a hypothesis"
    assert _state_links(a, closing) == [EvidenceRelation.QUALIFIES]
    assert world.engine.get_history(world.kb.resolve("Asha"), "works_at")["periods"][0].end == "2021", "P1's own default view is unchanged"


def test_a_pending_slot_fact_with_no_stated_date_has_no_period_and_is_time_unknown(world):
    fid, _ = world.obs("Asha", "job_title", "Registrar", validation="pending")
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    p = {p.id: p for p in a.request.propositions}[f"fact:{fid}"]
    assert p.valid_time is None and p.qualifiers["valid_time"] == "unknown"
    rec = next(e for e in a.request.evidence if e.id == f"state:{fid}")
    assert rec.metadata["qualified_for"] == ("validation pending", "valid time unknown")


def _conflict_report(world, how, when):
    """Accepted works_at Pune (2019) beside a pending works_at Delhi; returns what ERC made of the competing values."""
    world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    world.obs("Asha", "works_at", "Hospital Delhi", valid_from=when, speaker="Ravi", **how)
    r = Reasoner(world.kb).reason("Asha", as_of=AT_2023)
    return r, [c.certainty for c in r.orchestration.contradictions]


def test_a_pending_value_with_a_stated_overlapping_date_is_a_definite_conflict(world):
    """ERC's policy (orchestration.py): a definite conflict stops inference; status CONFLICT; with no conclusion to evaluate, withheld."""
    r, kinds = _conflict_report(world, dict(validation="pending"), "2021")
    assert kinds == [ContradictionCertainty.DEFINITE]
    assert r.result.status == ReasoningStatus.CONFLICT
    assert r.evaluation.overall_decision.value == "withheld"


def test_a_pending_value_with_no_stated_date_is_a_potential_conflict_and_the_run_is_indeterminate(world):
    """The pending value has no period (not accepted) and no stated date, so ERC cannot establish the overlap: the competing values are
    still detected, as a potential conflict recorded as uncertainty; status INDETERMINATE, not CONFLICT; nothing is resolved."""
    r, kinds = _conflict_report(world, dict(validation="pending"), None)
    assert kinds == [ContradictionCertainty.POTENTIAL]
    assert r.result.status == ReasoningStatus.INDETERMINATE
    assert [u.id for u in r.result.uncertainty] == ["uncertainty_potential_conflict_1"]
    assert r.evaluation.overall_decision.value == "withheld"


# a rule over two non-slot predicates, so both premises can truly have no valid time
X_, Y_, Z_ = Variable("x"), Variable("y"), Variable("z")
ADMIRES = RuleSet((RuleDefinition("admires_city", "1", (PropositionPattern(X_, "admires", Y_), PropositionPattern(Y_, "located_in", Z_)),
                                  ConclusionTemplate(X_, "admires_someone_in", Z_)),))


def test_two_genuinely_undated_premises_give_a_provisional_conclusion_with_both_named(world):
    world.who("Ramanujan")
    admires, _ = world.obs("Asha", "admires", "Ramanujan")
    located, _ = world.obs("Ramanujan", "located_in", "Kumbakonam")
    r = Reasoner(world.kb)
    run = r.reason("Asha", ruleset=ADMIRES, as_of=AS_OF)
    assert [(p.predicate, p.object_value) for p in run.result.propositions if p.kind == PropositionKind.INFERENCE] == [("admires_someone_in", "Kumbakonam")]
    assert run.evaluation.overall_decision.value == "provisional"
    recs = {e.id for e in run.adapted.request.evidence if e.id.startswith("state:")}
    assert recs == {f"state:{admires}", f"state:{located}"}


# ---------- 1A follow-up 3: an event keeps its own date; only the state takes the period's span ----------
def _pune(world, when):
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    left, _ = world.obs("Asha", "left_job", "Hospital Pune", valid_from=when)
    return pune, left


def _at(world, year):
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=dt.datetime(year, 6, 1, tzinfo=dt.timezone.utc))
    return {p.id: p for p in a.request.propositions}, {l.fact_id: l.reason for l in a.left_out}


def test_as_of_2020_the_employment_is_in_and_the_2021_closing_event_is_not(world):
    pune, left = _pune(world, "2021")
    props, out = _at(world, 2020)
    assert f"fact:{pune}" in props and props[f"fact:{pune}"].valid_time.end == dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc)
    assert f"fact:{left}" not in props and out[left] == "starts after as_of"


def test_as_of_2022_the_employment_is_out_and_the_2021_closing_event_is_available(world):
    pune, left = _pune(world, "2021")
    props, out = _at(world, 2022)
    assert f"fact:{pune}" not in props and out[pune] == "ended before as_of"
    t = props[f"fact:{left}"].valid_time
    assert t.start == dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc), "the event has its own date, not the period's start"
    assert t.end is None, "an event does not stop having happened: no end, not even a synthetic one at as_of"
    assert props[f"fact:{left}"].qualifiers["time_kind"] == "event"
    props_2020, _ = _at(world, 2020)
    assert props_2020[f"fact:{pune}"].qualifiers["time_kind"] == "state"


def test_an_undated_closing_event_takes_its_date_from_its_sentence_not_from_the_period(world):
    pune, left = _pune(world, None)  # said on 5 March 2024
    props, out = _at(world, 2022)
    assert f"fact:{pune}" in props and props[f"fact:{pune}"].valid_time.end == dt.datetime(2024, 3, 6, tzinfo=dt.timezone.utc)
    assert f"fact:{left}" not in props and out[left] == "starts after as_of"
    props, _ = _at(world, 2025)
    assert f"fact:{pune}" not in props
    assert props[f"fact:{left}"].valid_time == TimeInterval(dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc), None)


def test_an_opening_event_keeps_its_own_date_and_outlives_the_state_it_opened(world):
    moved, _ = world.obs("Asha", "moved_to", "Delhi", valid_from="2022")
    world.obs("Asha", "lives_in", "Mysore", valid_from="2024")
    props, out = _at(world, 2023)
    assert props[f"fact:{moved}"].qualifiers["time_kind"] == "event"
    assert props[f"fact:{moved}"].valid_time == TimeInterval(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc), None)
    props, out = _at(world, 2025)
    assert f"fact:{moved}" in props, "the move still happened in 2025, even though living in Delhi ended in 2024"
    lives = [p for p in props.values() if p.predicate == "lives_in"]
    assert [(p.object_value, p.qualifiers["time_kind"]) for p in lives] == [("Mysore", "state")]


def test_explain_tells_an_event_from_a_state(world):
    pune, left = _pune(world, "2021")
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=dt.datetime(2022, 6, 1, tzinfo=dt.timezone.utc)))
    assert any(l.startswith("fact: Asha left_job Hospital Pune; state:") and l.endswith("; event on 2021-01-01") for l in lines), lines


@pytest.mark.parametrize("stated", [True, False], ids=["started_job stated 2021", "started_job dated only by its sentence"])
def test_an_opening_event_appended_to_an_existing_period_keeps_its_own_date_not_the_periods_start(world, stated):
    """P1 files a same-value observation into the existing period without moving the period's start; the event's date must still
    come from its own observation (its valid_from, else the day its sentence was said), never from the period's 2019 start."""
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    started, _ = world.obs("Asha", "started_job", "Hospital Pune", valid_from="2021" if stated else None)  # said on 5 March 2024
    props, out = _at(world, 2025)
    expected = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc) if stated else dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc)
    assert props[f"fact:{started}"].valid_time == TimeInterval(expected, None)
    assert props[f"fact:{pune}"].valid_time.start == dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc), "the state keeps the period's start"
    assert world.engine.get_history(world.kb.resolve("Asha"), "works_at")["periods"][0].start == "2019", "P1 unchanged"
    props, out = _at(world, 2020)
    assert f"fact:{started}" not in props and out[started] == "starts after as_of"


# ---------- 1A sign-off: an event whose date cannot be established ----------
def test_an_event_with_no_establishable_date_is_time_unknown_not_dated_from_the_period(world):
    """left_job with no stated date and a sentence whose date cannot be read: the adapter must not borrow the employment period's
    boundary. The event is sent, marked valid time unknown, with a qualifying state record, so nothing resting on it is established."""
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    world.m.open_chat(DAY); sid = world.m.add("Ravi", "Asha left_job Hospital Pune.", date="sometime"); world.m.close_chat(write_note=False)
    left, _ = world.obs("Asha", "left_job", "Hospital Pune", sid=sid)
    assert world.m.db.execute("SELECT date FROM sentences WHERE sid=?", (int(sid),)).fetchone()[0] == "sometime"
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF)
    props = {p.id: p for p in a.request.propositions}
    p = props[f"fact:{left}"]
    assert p.valid_time is None and p.qualifiers["valid_time"] == "unknown" and p.qualifiers["time_kind"] == "event"
    rec = next(e for e in a.request.evidence if e.id == f"state:{left}")
    assert rec.metadata["qualified_for"] == ("valid time unknown",)
    assert _state_links(a, left) == [EvidenceRelation.QUALIFIES]
    # the state engine, by its own rule, still closes the period from the sentence it can date (none here): the period stays open
    assert props[f"fact:{pune}"].valid_time.end > AS_OF
    assert left not in {l.fact_id for l in a.left_out}


# ---------- B2a: adapter enrichment (claude/erc-b2a-spec.md, frozen 10 Nov 2026) ----------
# Additive only. The adapter passes on what Engram already knows and ERC does not yet read: when a sentence was said (A), how
# precisely a stated date is known (B), where each boundary came from (C), and the same for events without changing them (D).
# Nothing ERC reads today may move: starts, ends, what is sent, what is left out, the guards (G), the request id (I). One place
# turns a day into an instant (Z). explain() gains separate "time:" lines and loses nothing (X).
import hashlib
import json

from engram_erc import BoundaryStatus
import erc_overlay.knowledge as overlay_knowledge
from erc_overlay.knowledge import PLAYED

UTC = dt.timezone.utc
END_OF_DAY = (23, 59, 59, 999999)
SAID = dt.datetime(2024, 3, 5, tzinfo=UTC)                     # every test sentence is said on 5 March 2024 (DAY)
SAID_LATEST = "2024-03-05T23:59:59.999999+00:00"
AT_2020 = dt.datetime(2020, 6, 1, tzinfo=UTC)
OLD_QUALIFIERS = ("status", "validation_status", "source_type", "fact_type", "time_kind", "valid_time")


def _t(*parts):
    return dt.datetime(*parts, tzinfo=UTC)


def _sent(world, as_of=AS_OF, who="Asha"):
    a = KnowledgeAdapter(world.kb).request_for(who, as_of=as_of)
    return a, {p.id: p for p in a.request.propositions}


def _evidence(a, evidence_id):
    return next(e for e in a.request.evidence if e.id == evidence_id)


# ----- A: the observation date on sentence evidence -----
def test_b2a_sentence_evidence_carries_the_day_it_was_said_as_an_anchor_with_the_days_last_instant_beside_it(world):
    """A1. observed_at is the first instant of the said day: a date anchor, not a claim the sentence was said at midnight.
    observed_latest keeps the rest of the day. The source is the sentence's date, never the fact's recorded_at."""
    fid, sid = world.obs("Asha", "works_at", "Apollo", valid_from="2021")
    a, _ = _sent(world)
    e = _evidence(a, f"sentence:{sid}")
    assert e.observed_at == SAID
    assert e.metadata["observed_latest"] == SAID_LATEST
    assert world.kb.get(fid).fact.recorded_at[:10] != "2024-03-05", "the fact was recorded today, not on the day the sentence was said"


def test_b2a_a_sentence_with_no_readable_date_gets_no_observation_date_none_is_invented(world):
    """A2."""
    world.m.open_chat(DAY); sid = world.m.add("Asha", "Asha works_at Apollo.", date="sometime"); world.m.close_chat(write_note=False)
    world.obs("Asha", "works_at", "Apollo", valid_from="2021", sid=sid)
    _, dated = world.obs("Asha", "hobby", "chess")
    a, _ = _sent(world)
    e = _evidence(a, f"sentence:{sid}")
    assert e.observed_at is None and "observed_latest" not in e.metadata
    assert _evidence(a, f"sentence:{dated}").observed_at == SAID, "the sentence beside it, which has a date, gets one"


def test_b2a_the_adapters_own_state_record_has_no_observation_date_while_the_sentence_beside_it_has(world):
    """A3. A state record is the adapter's control signal, not something observed."""
    fid, sid = world.obs("Asha", "hobby", "chess", source_type="inferred")
    a, _ = _sent(world)
    rec = _evidence(a, f"state:{fid}")
    assert rec.observed_at is None and "observed_latest" not in rec.metadata
    assert _evidence(a, f"sentence:{sid}").observed_at == SAID


def test_b2a_one_sentence_supporting_two_facts_is_one_evidence_record_with_one_observation_date(world):
    """A4."""
    sid = world.say("Asha", "I work at Manipal and I play chess.")
    world.obs("Asha", "works_at", "Manipal", sid=sid)
    world.obs("Asha", "hobby", "chess", sid=sid)
    a, _ = _sent(world)
    assert [(e.id, e.observed_at, e.metadata.get("observed_latest")) for e in a.request.evidence] == [(f"sentence:{sid}", SAID, SAID_LATEST)]


# ----- B: precision bounds on a state's interval; start and end themselves do not move -----
def test_b2a_a_start_stated_to_the_year_keeps_its_start_and_gains_the_years_last_instant(world):
    """B1. Open state: the stand-in end (as_of + 1 day) is untouched and carries no bound."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2021")
    _, props = _sent(world)
    v = props[f"fact:{fid}"].valid_time
    assert v.start == _t(2021, 1, 1) and v.start_latest == _t(2021, 12, 31, *END_OF_DAY)
    assert v.start_status == BoundaryStatus.WITHIN
    assert v.end == AS_OF + dt.timedelta(days=1) and v.end_earliest is None


def test_b2a_a_start_stated_to_the_month_gains_the_months_last_instant(world):
    """B2."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2021-04")
    _, props = _sent(world)
    v = props[f"fact:{fid}"].valid_time
    assert v.start == _t(2021, 4, 1) and v.start_latest == _t(2021, 4, 30, *END_OF_DAY)


def test_b2a_a_start_stated_to_the_day_stays_exact(world):
    """B3 (OP-2). A day's own window waits for the time-zone decision at B2b."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2021-04-10")
    _, props = _sent(world)
    v = props[f"fact:{fid}"].valid_time
    assert v.start == _t(2021, 4, 10) and v.start_latest is None and v.start_status == BoundaryStatus.EXACT
    assert props[f"fact:{fid}"].qualifiers["start_basis"] == "stated", "exact because it was stated to the day, and labelled so"


@pytest.mark.parametrize("predicate", ["works_at", "located_in"], ids=["a fact the state engine plays in a slot", "a fact outside every slot"])
def test_b2a_an_end_stated_to_the_month_keeps_its_end_and_gains_the_earliest_it_could_be(world, predicate):
    """B4 (OP-3). 'To March 2021': the last day it held lies in March, so it stopped holding between 2 March and 1 April."""
    fid, _ = world.obs("Asha", predicate, "Apollo", valid_from="2019", valid_to="2021-03")
    _, props = _sent(world, AT_2020)
    v = props[f"fact:{fid}"].valid_time
    assert v.start == _t(2019, 1, 1) and v.start_latest == _t(2019, 12, 31, *END_OF_DAY)
    assert v.end == _t(2021, 4, 1) and v.end_earliest == _t(2021, 3, 2)
    assert v.end_status == BoundaryStatus.WITHIN


def test_b2a_an_end_stated_to_the_year_runs_from_the_second_of_january_to_the_next_first_of_january(world):
    """B5 (OP-3)."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021")
    _, props = _sent(world, AT_2020)
    v = props[f"fact:{fid}"].valid_time
    assert v.end == _t(2022, 1, 1) and v.end_earliest == _t(2021, 1, 2)


def test_b2a_an_end_stated_to_the_day_stays_exact(world):
    """B6."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03-15")
    _, props = _sent(world, AT_2020)
    v = props[f"fact:{fid}"].valid_time
    assert v.end == _t(2021, 3, 16) and v.end_earliest is None and v.end_status == BoundaryStatus.EXACT
    assert v.start_latest == _t(2019, 12, 31, *END_OF_DAY), "the enrichment is present on the same interval"


# ----- C: where each boundary came from -----
def test_b2a_a_state_dated_only_by_when_it_was_said_keeps_that_start_gets_no_bound_and_is_labelled_first_said(world):
    """C1 (OP-4, TAD-15). The interval is exactly today's; only the label is new. B2b changes the interval, not B2a."""
    fid, _ = world.obs("Asha", "works_at", "Apollo")
    _, props = _sent(world)
    p = props[f"fact:{fid}"]
    assert p.valid_time == TimeInterval(SAID, AS_OF + dt.timedelta(days=1)), "start, end and no bound of any kind"
    assert p.qualifiers["start_basis"] == "first_said"


def test_b2a_a_state_first_said_in_a_sentence_dated_only_to_the_month_gets_no_bound_from_the_sentences_precision(world):
    """C1, strengthened at build (10 Nov): the deliberate breakage 'bound added to a first-said start' was missed, because every
    other test sentence is dated to the day. Here the sentence is dated 'March 2024'. The coarse date is the sentence's, not a
    stated start, so the state's interval gets no bound; the sentence's own month goes on its evidence, where it belongs."""
    world.m.open_chat(DAY); sid = world.m.add("Asha", "Asha works_at Apollo.", date="March 2024"); world.m.close_chat(write_note=False)
    fid, _ = world.obs("Asha", "works_at", "Apollo", sid=sid)
    period = world.engine.get_history(world.kb.resolve("Asha"), "works_at", **PLAYED)["periods"][0]
    assert (period.start, period.first_said) == (None, "2024-03")
    a, props = _sent(world)
    p = props[f"fact:{fid}"]
    assert p.valid_time == TimeInterval(_t(2024, 3, 1), AS_OF + dt.timedelta(days=1)), "today's interval, and no bound"
    assert p.qualifiers["start_basis"] == "first_said"
    e = _evidence(a, f"sentence:{sid}")
    assert e.observed_at == _t(2024, 3, 1) and e.metadata["observed_latest"] == "2024-03-31T23:59:59.999999+00:00"


@pytest.mark.parametrize("predicate", ["works_at", "located_in"], ids=["slot fact", "fact outside every slot"])
def test_b2a_a_stated_start_is_labelled_stated(world, predicate):
    """C2."""
    fid, _ = world.obs("Asha", predicate, "Apollo", valid_from="2021")
    _, props = _sent(world)
    assert props[f"fact:{fid}"].qualifiers["start_basis"] == "stated"


def _open(w):
    return w.obs("Asha", "works_at", "Apollo", valid_from="2019")[0], "works_at"


def _stated_end(w):
    return w.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03")[0], "works_at"


def _closed(w):
    fid, _ = w.obs("Asha", "works_at", "Apollo", valid_from="2019")
    w.obs("Asha", "left_job", "Apollo", valid_from="2021")
    return fid, "works_at"


def _replaced(w):
    fid, _ = w.obs("Asha", "lives_in", "Pune", valid_from="2019")
    w.obs("Asha", "lives_in", "Bengaluru", valid_from="2022")
    return fid, "lives_in"


@pytest.mark.parametrize("build,kind", [(_open, "open"), (_stated_end, "stated"), (_closed, "closed"), (_replaced, "replaced")],
                         ids=["open", "stated", "closed", "replaced"])
def test_b2a_end_basis_is_engrams_own_word_for_how_the_period_ended(world, build, kind):
    """C3 (OP-5, OP-10). No second vocabulary: the label is the state engine's end_kind for the period the fact is in."""
    fid, slot = build(world)
    period = next(p for p in world.engine.get_history(world.kb.resolve("Asha"), slot, **PLAYED)["periods"] if fid in p.fact_ids)
    assert period.end_kind == kind, "what Engram says"
    _, props = _sent(world, AT_2020)
    assert props[f"fact:{fid}"].qualifiers["end_basis"] == kind


def test_b2a_a_period_closed_by_a_dated_statement_keeps_its_end_and_gets_no_bound(world):
    """C4 (OP-5). 'Left in 2021' closes the job: Engram's period end is the closing statement's date, not the fact's own stated end."""
    fid, _ = _closed(world)
    _, props = _sent(world, AT_2020)
    v = props[f"fact:{fid}"].valid_time
    assert v.end == _t(2022, 1, 1) and v.end_earliest is None
    assert v.start_latest == _t(2019, 12, 31, *END_OF_DAY), "the start, which was stated, still gets its bound"


def test_b2a_a_period_closed_by_an_undated_statement_keeps_the_said_day_end_and_gets_no_bound(world):
    """C4, finding F5. 'I left Apollo', said 5 March 2024 with no date: Engram ends the job on the said day and the adapter still
    sends that end (corrected at B2b, TAD-17). B2a labels it and invents nothing."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    world.obs("Asha", "left_job", "Apollo")
    _, props = _sent(world, _t(2023, 1, 1))
    p = props[f"fact:{fid}"]
    assert p.valid_time.end == _t(2024, 3, 6) and p.valid_time.end_earliest is None
    assert p.qualifiers["end_basis"] == "closed"


def test_b2a_a_period_replaced_by_an_undated_new_value_keeps_its_end_and_gets_no_bound(world):
    """C4, finding F5. Pune from 2019, then 'lives in Delhi' with no date: Engram ends Pune the day before the sentence was said."""
    fid, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019")
    world.obs("Asha", "lives_in", "Delhi")
    _, props = _sent(world, _t(2023, 1, 1))
    p = props[f"fact:{fid}"]
    assert p.valid_time.end == _t(2024, 3, 5) and p.valid_time.end_earliest is None
    assert p.qualifiers["end_basis"] == "replaced"


def test_b2a_a_fact_with_no_valid_time_carries_neither_label_and_its_sentence_still_has_its_date(world):
    """C5. Unknown stays unknown: no interval, no basis to describe."""
    fid, sid = world.obs("Asha", "located_in", "Bengaluru")
    a, props = _sent(world)
    p = props[f"fact:{fid}"]
    assert p.valid_time is None and p.qualifiers["valid_time"] == "unknown"
    assert "start_basis" not in p.qualifiers and "end_basis" not in p.qualifiers
    assert _evidence(a, f"sentence:{sid}").observed_at == SAID


def test_b2a_the_one_day_minimum_is_labelled_adjusted_and_gets_no_bound(world):
    """C6. Reproduced 10 Nov: a job first said on 5 March 2024 with a stated end of 2021. Engram's end (2021) falls before the
    first-said start, so the adapter's one-day minimum makes the end 6 March 2024. That end is the adapter's, not Engram's."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_to="2021")
    period = world.engine.get_history(world.kb.resolve("Asha"), "works_at", **PLAYED)["periods"][0]
    assert (period.start, period.first_said, period.end, period.end_kind) == (None, "2024-03-05", "2021", "stated")
    _, props = _sent(world)
    p = props[f"fact:{fid}"]
    assert p.valid_time == TimeInterval(SAID, _t(2024, 3, 6)), "today's interval, with no bound added"
    assert p.qualifiers["start_basis"] == "first_said" and p.qualifiers["end_basis"] == "adjusted"


def _only_an_end(w):
    return w.obs("Asha", "located_in", "Pune", valid_to="2021")[0]


def _only_an_end_in_a_slot_with_an_unreadable_sentence(w):
    w.m.open_chat(DAY); sid = w.m.add("Asha", "Asha works_at Apollo.", date="sometime"); w.m.close_chat(write_note=False)
    return w.obs("Asha", "works_at", "Apollo", valid_to="2021", sid=sid)[0]


def _only_an_end_superseded(w):
    return w.obs("Asha", "located_in", "Pune", valid_to="2021", status="superseded")[0]


@pytest.mark.parametrize("build", [_only_an_end, _only_an_end_in_a_slot_with_an_unreadable_sentence, _only_an_end_superseded],
                         ids=["fact outside every slot", "slot fact whose sentence has no readable date", "superseded fact sent as history"])
def test_b2a_a_fact_with_a_known_end_and_no_start_gets_no_start_label_and_explain_still_works(world, build):
    """Review of bd6d977 (10 Nov): Engram can hold a stated end with neither a stated start nor a readable first-said day. The
    adapter sends that as an interval with no start, as it did before B2a. There is then nothing for a start label to describe,
    so none is attached (the first build attached 'stated' or 'first_said', and explain() failed on the missing date). The end
    keeps its label and its bound; explain() says the start is not known and keeps its existing line."""
    fid = build(world)
    r = Reasoner(world.kb)
    run = r.reason("Asha", as_of=AT_2020)
    p = next(x for x in run.adapted.request.propositions if x.id == f"fact:{fid}")
    assert p.valid_time == TimeInterval(None, _t(2022, 1, 1), end_earliest=_t(2021, 1, 2))
    assert "start_basis" not in p.qualifiers and p.qualifiers["end_basis"] == "stated" and p.qualifiers["valid_time"] == "known"
    lines = r.explain(run)
    at = next(i for i, l in enumerate(lines) if l.startswith("fact:"))
    assert lines[at].endswith("; valid ? to 2022-01-01"), "the line explain() gave before B2a"
    assert lines[at + 1] == "  time: start not known; end stated, between 2021-01-02 and 2022-01-01"


# ----- D: events are labelled and otherwise untouched (they move to `occurred` at B2b) -----
def test_b2a_an_event_with_a_stated_year_keeps_exactly_its_interval_and_is_labelled_stated(world):
    """D1 (OP-6). No precision bound on an event's interval in B2a."""
    moved, _ = world.obs("Asha", "moved_to", "Delhi", valid_from="2022")
    _, props = _sent(world, _t(2023, 6, 1))
    p = props[f"fact:{moved}"]
    assert p.valid_time == TimeInterval(_t(2022, 1, 1), None) and p.occurred is None
    assert p.qualifiers["time_kind"] == "event" and p.qualifiers["start_basis"] == "stated" and "end_basis" not in p.qualifiers


def test_b2a_an_event_dated_only_by_its_sentence_keeps_exactly_its_interval_and_is_labelled_first_said(world):
    """D2."""
    world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    left, _ = world.obs("Asha", "left_job", "Apollo")
    _, props = _sent(world, _t(2025, 6, 1))
    p = props[f"fact:{left}"]
    assert p.valid_time == TimeInterval(SAID, None) and p.occurred is None
    assert p.qualifiers["start_basis"] == "first_said" and "end_basis" not in p.qualifiers


# ----- G: the guards decide exactly as before, with the bounds present -----
def test_b2a_guard_a_fact_from_this_year_is_still_sent_and_a_fact_from_next_year_is_still_left_out(world):
    """G1. Known limitation until B2b / B6: 'from 2026' asked on 1 March 2026 is sent as if it had begun on 1 January. The honest
    bound now travels with it, later than the stand-in end (finding F11, OP-9); the guard still reads the start alone."""
    this_year, _ = world.obs("Asha", "lives_in", "Mysore", valid_from="2026")
    next_year, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2027")
    as_of = _t(2026, 3, 1)
    a, props = _sent(world, as_of)
    v = props[f"fact:{this_year}"].valid_time
    assert (v.start, v.end) == (_t(2026, 1, 1), _t(2026, 3, 2))
    assert v.start_latest == _t(2026, 12, 31, *END_OF_DAY) and v.start_latest > v.end
    assert f"fact:{next_year}" not in props
    assert {l.fact_id: l.reason for l in a.left_out} == {next_year: "starts after as_of"}


def test_b2a_guard_a_fact_whose_stated_end_has_passed_is_still_left_out_and_is_still_sent_before_it(world):
    """G2. The guard reads the end (1 January 2022), never the earliest it could be (2 January 2021)."""
    fid, _ = world.obs("Asha", "located_in", "Pune", valid_from="2019", valid_to="2021")
    a, props = _sent(world, _t(2022, 6, 1))
    assert f"fact:{fid}" not in props and {l.fact_id: l.reason for l in a.left_out} == {fid: "ended before as_of"}
    a, props = _sent(world, _t(2021, 6, 1))
    v = props[f"fact:{fid}"].valid_time
    assert (v.start, v.end, v.end_earliest) == (_t(2019, 1, 1), _t(2022, 1, 1), _t(2021, 1, 2)) and not a.left_out


def test_b2a_guard_two_values_held_at_once_are_still_one_definite_contradiction_with_the_bounds_present(world):
    """G3. ERC's comparison reads start and end only; the bounds change nothing it decides."""
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    delhi, _ = world.obs("Asha", "works_at", "Hospital Delhi", valid_from="2020", speaker="Ravi")
    r = Reasoner(world.kb).reason("Asha", as_of=AT_2023)
    assert [c.certainty for c in r.orchestration.contradictions] == [ContradictionCertainty.DEFINITE]
    assert r.result.status == ReasoningStatus.CONFLICT
    props = {p.id: p for p in r.adapted.request.propositions}
    assert props[f"fact:{pune}"].valid_time.start_latest == _t(2019, 12, 31, *END_OF_DAY)
    assert props[f"fact:{delhi}"].valid_time.start_latest == _t(2020, 12, 31, *END_OF_DAY)


# ----- I: identity of what was already sent -----
def test_b2a_the_request_id_is_the_same_recipe_while_the_request_carries_the_enrichment(world):
    """I1 (OP-11). The id is recomputed here from the documented recipe: entity, as_of, task, each fact's id, status, validation,
    source type and recorded_at, and the rule set. The new fields are in the request and not in the id."""
    chain(world)
    a = KnowledgeAdapter(world.kb).request_for("Asha", as_of=AS_OF, ruleset=CITY)
    facts = sorted((f.fact_id, f.status, f.validation_status, f.source_type, f.recorded_at) for f in (world.kb.get(i).fact for i in a.fact_ids))
    digest = hashlib.sha256(json.dumps(dict(
        entity=world.kb.resolve("Asha"), as_of=AS_OF.isoformat(), task="state_question", facts=facts,
        rules=[CITY.version] + sorted((r.rule_id, r.version) for r in CITY.rules)), sort_keys=True).encode()).hexdigest()[:24]
    assert a.request.id == f"erc_req_{digest}"
    assert all(e.observed_at == SAID for e in a.request.evidence) and len(a.request.evidence) == 2
    assert all(p.valid_time.start_latest is not None for p in a.request.propositions)


def test_b2a_every_qualifier_sent_before_is_still_sent_with_the_same_value_and_only_the_two_labels_are_new(world):
    """I2."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2021")
    _, props = _sent(world)
    q = dict(props[f"fact:{fid}"].qualifiers)
    assert {k: q[k] for k in OLD_QUALIFIERS} == dict(status="active", validation_status="accepted", source_type="explicit",
                                                     fact_type="attribute", time_kind="state", valid_time="known")
    assert set(q) == set(OLD_QUALIFIERS) | {"start_basis", "end_basis"}
    assert (q["start_basis"], q["end_basis"]) == ("stated", "open")


# ----- Z: one place turns a day into an instant -----
def test_b2a_every_instant_made_from_a_day_follows_the_adapters_one_zone(world, monkeypatch):
    """Z1 (E4). With the adapter's zone set to +05:30 for this test, every day-derived instant moves with it: start, stated end,
    both bounds and the observation date. Nothing is left at UTC midnight, so B2b's zone decision is one line."""
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    monkeypatch.setattr(overlay_knowledge, "DAY_ZONE", ist)
    fid, sid = world.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03")
    a, props = _sent(world, AT_2020)
    v = props[f"fact:{fid}"].valid_time
    at = lambda *parts: dt.datetime(*parts, tzinfo=ist)
    assert (v.start, v.start_latest) == (at(2019, 1, 1), at(2019, 12, 31, *END_OF_DAY))
    assert (v.end_earliest, v.end) == (at(2021, 3, 2), at(2021, 4, 1))
    assert all(x.utcoffset() == dt.timedelta(hours=5, minutes=30) for x in (v.start, v.start_latest, v.end_earliest, v.end))
    e = _evidence(a, f"sentence:{sid}")
    assert e.observed_at == at(2024, 3, 5) and e.observed_at.utcoffset() == dt.timedelta(hours=5, minutes=30)
    assert e.metadata["observed_latest"] == "2024-03-05T23:59:59.999999+05:30"


# ----- X: explain() says what is stated and what is only first said, and loses no line -----
STATE = "state: status active, validation accepted, source explicit; sent as assertion"


def _explained(lines):
    """explain()'s output as (the heading lines, the 'because' blocks, the 'fact' blocks). ERC orders a conclusion's premises by
    proposition id, and fact ids are random, so the blocks are compared as sets of blocks; inside a block the order is exact."""
    heading, because, facts = [], [], []
    for l in lines:
        if l.startswith("  because:"):
            assert not facts, "premises are explained before the list of facts"
            because.append([l])
        elif l.startswith("fact:"): facts.append([l])
        elif facts or because: (facts or because)[-1].append(l)
        else: heading.append(l)
    return heading, sorted(map(tuple, because)), sorted(map(tuple, facts))


def test_b2a_explain_adds_a_time_line_under_each_fact_and_every_other_line_is_exactly_as_before(world):
    """X1 (OP-8). `before` is explain()'s output for this world at e6e6a9d, block for block. With the time lines taken out, the
    output must equal it; with them in, each sits directly under the state it describes."""
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021")          # sentence 1: stated to the year
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")   # sentence 2
    world.obs("Asha", "lives_in", "Mysore")                              # sentence 3: dated only by when it was said
    world.obs("Asha", "left_job", "Apollo", valid_from="2022")           # sentence 4: an event
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", ruleset=CITY, as_of=AS_OF))
    said = "1:00 pm on 5 March, 2024"
    heading = ["strategy rule_reasoning@1.0, status complete, as of 2024-03-05, overall accepted",
               "conclusion: Asha works_in_city Bengaluru -> accepted (PREMISE_LINEAGE_COMPLETE_AND_SUPPORT_THRESHOLD_MET)"]
    located = ("  because: Manipal located_in Bengaluru", f"    {STATE}; valid 2010-01-01 to 2024-03-06",
               f'    sentence 2 (Manipal, {said}): "Manipal located_in Bengaluru."')
    works = ("  because: Asha works_at Manipal", f"    {STATE}; valid 2021-01-01 to 2024-03-06",
             f'    sentence 1 (Asha, {said}): "Asha works_at Manipal."')
    facts = [f"fact: Asha works_at Manipal; {STATE}; valid 2021-01-01 to 2024-03-06",
             f"fact: Asha lives_in Mysore; {STATE}; valid 2024-03-05 to 2024-03-06",
             f"fact: Asha left_job Apollo; {STATE}; event on 2022-01-01",
             f"fact: Manipal located_in Bengaluru; {STATE}; valid 2010-01-01 to 2024-03-06"]
    before = (heading, sorted([located, works]), sorted((f,) for f in facts))
    assert _explained([l for l in lines if not l.lstrip().startswith("time:")]) == before
    in_2010 = "time: start stated, between 2010-01-01 and 2010-12-31; end open"
    in_2021 = "time: start stated, between 2021-01-01 and 2021-12-31; end open"
    times = [f"  {in_2021}", "  time: start not stated (first said 2024-03-05); end open", "  time: event stated 2022-01-01", f"  {in_2010}"]
    after = (heading,
             sorted([(located[0], located[1], f"    {in_2010}", located[2]), (works[0], works[1], f"    {in_2021}", works[2])]),
             sorted(zip(facts, times)))
    assert _explained(lines) == after


@pytest.mark.parametrize("how,as_of,expected", [
    (dict(valid_from="2021-04-10"), AS_OF, "  time: start stated 2021-04-10; end open"),
    (dict(valid_from="2019", valid_to="2021-03"), AT_2020, "  time: start stated, between 2019-01-01 and 2019-12-31; end stated, between 2021-03-02 and 2021-04-01"),
    (dict(valid_from="2019", valid_to="2021-03-15"), AT_2020, "  time: start stated, between 2019-01-01 and 2019-12-31; end stated 2021-03-16"),
    (dict(valid_to="2021"), AS_OF, "  time: start not stated (first said 2024-03-05); end adjusted 2024-03-06"),
], ids=["exact start", "end known to the month", "exact end", "adjusted end"])
def test_b2a_explain_time_line_for_each_kind_of_state_boundary(world, how, as_of, expected):
    """X1, the remaining wordings. An end is shown as the first day the state no longer holds, as the existing 'valid … to …' line does."""
    world.obs("Asha", "works_at", "Apollo", **how)
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=as_of))
    assert [l for l in lines if l.lstrip().startswith("time:")] == [expected]


def test_b2a_explain_time_lines_for_a_closed_period_its_closing_event_and_a_fact_with_no_time(world):
    """X1. A closed end is shown with Engram's word; an event dated only by its sentence says so; unknown time says so."""
    world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    world.obs("Asha", "left_job", "Apollo")                               # said 5 March 2024, no stated date
    world.obs("Asha", "located_in", "Bengaluru")                          # no valid time at all
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=AS_OF))
    assert _explained(lines)[2] == sorted([
        (f"fact: Asha works_at Apollo; {STATE}; valid 2019-01-01 to 2024-03-06",
         "  time: start stated, between 2019-01-01 and 2019-12-31; end closed 2024-03-06"),
        (f"fact: Asha left_job Apollo; {STATE}; event on 2024-03-05",
         "  time: event not stated (first said 2024-03-05)"),
        ("fact: Asha located_in Bengaluru; state: status active, validation accepted, source explicit; sent as assertion with a qualifying "
         "state record (valid time unknown); valid time unknown",
         "  time: not known"),
    ])
