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
from engram_erc import EvidenceRelation, Occurrence, TimeInterval
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
    assert lines[i + 1] == "    state: status active, validation pending, source explicit; sent as hypothesis with a qualifying state record (validation pending); valid 2021-01-01, still going"
    assert lines[lines.index("  because: Manipal located_in Bengaluru") + 1] == "    state: status active, validation accepted, source explicit; sent as assertion with a qualifying state record (valid time unknown); valid time unknown"
    assert "fact: Asha works_at Manipal; state: status active, validation pending, source explicit; sent as hypothesis with a qualifying state record (validation pending); valid 2021-01-01, still going" in lines


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
    assert props[f"fact:{pune}"].valid_time == TimeInterval(_t(2019, 1, 1), start_latest=_t(2019, 12, 31, *END_OF_DAY), end_unbounded=True)  # revised at B2b: still going, no stand-in end
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
    assert f"fact:{pune}" in props and props[f"fact:{pune}"].valid_time.end_unbounded, "the accepted fact stays eligible and open"  # revised at B2b: open is sent as still going
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
    o = props[f"fact:{left}"].occurred  # revised at B2b: an event is an occurrence, with no validity interval
    assert o == Occurrence(_t(2021, 1, 1), _t(2021, 12, 31, *END_OF_DAY)), "the event has its own date, not the period's start"
    assert props[f"fact:{left}"].valid_time is None, "an event is not a period: nothing to end, and nothing synthetic at as_of"
    assert props[f"fact:{left}"].qualifiers["time_kind"] == "event"
    props_2020, _ = _at(world, 2020)
    assert props_2020[f"fact:{pune}"].qualifiers["time_kind"] == "state"


def test_an_undated_closing_event_takes_its_date_from_its_sentence_not_from_the_period(world):
    pune, left = _pune(world, None)  # said on 5 March 2024
    props, out = _at(world, 2022)
    assert f"fact:{pune}" in props and props[f"fact:{pune}"].valid_time.end == dt.datetime(2024, 3, 6, tzinfo=dt.timezone.utc)
    assert props[f"fact:{pune}"].valid_time.end_is_upper_bound  # revised at B2b: a closing date that was only said is the latest the job can have ended
    assert f"fact:{left}" not in props and out[left] == "starts after as_of"
    props, _ = _at(world, 2025)
    assert f"fact:{pune}" not in props
    assert props[f"fact:{left}"].occurred == Occurrence(None, _t(2024, 3, 5, *END_OF_DAY)) and props[f"fact:{left}"].valid_time is None  # revised at B2b: told by 5 March: no later, and no date


def test_an_opening_event_keeps_its_own_date_and_outlives_the_state_it_opened(world):
    moved, _ = world.obs("Asha", "moved_to", "Delhi", valid_from="2022")
    world.obs("Asha", "lives_in", "Mysore", valid_from="2024")
    props, out = _at(world, 2023)
    assert props[f"fact:{moved}"].qualifiers["time_kind"] == "event"
    assert props[f"fact:{moved}"].occurred == Occurrence(_t(2022, 1, 1), _t(2022, 12, 31, *END_OF_DAY)) and props[f"fact:{moved}"].valid_time is None  # revised at B2b: an occurrence some time in 2022
    props, out = _at(world, 2025)
    assert f"fact:{moved}" in props, "the move still happened in 2025, even though living in Delhi ended in 2024"
    lives = [p for p in props.values() if p.predicate == "lives_in"]
    assert [(p.object_value, p.qualifiers["time_kind"]) for p in lives] == [("Mysore", "state")]


def test_explain_tells_an_event_from_a_state(world):
    pune, left = _pune(world, "2021")
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=dt.datetime(2022, 6, 1, tzinfo=dt.timezone.utc)))
    assert any(l.startswith("fact: Asha left_job Hospital Pune; state:") and l.endswith("; event between 2021-01-01 and 2021-12-31") for l in lines), lines  # revised at B2b: stated to the year


@pytest.mark.parametrize("stated", [True, False], ids=["started_job stated 2021", "started_job dated only by its sentence"])
def test_an_opening_event_appended_to_an_existing_period_keeps_its_own_date_not_the_periods_start(world, stated):
    """P1 files a same-value observation into the existing period without moving the period's start; the event's date must still
    come from its own observation (its valid_from, else the day its sentence was said), never from the period's 2019 start."""
    pune, _ = world.obs("Asha", "works_at", "Hospital Pune", valid_from="2019")
    started, _ = world.obs("Asha", "started_job", "Hospital Pune", valid_from="2021" if stated else None)  # said on 5 March 2024
    props, out = _at(world, 2025)
    expected = Occurrence(_t(2021, 1, 1), _t(2021, 12, 31, *END_OF_DAY)) if stated else Occurrence(None, _t(2024, 3, 5, *END_OF_DAY))
    assert props[f"fact:{started}"].occurred == expected and props[f"fact:{started}"].valid_time is None  # revised at B2b: an event is an occurrence
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
    assert props[f"fact:{pune}"].valid_time.end_unbounded and props[f"fact:{pune}"].valid_time.end is None  # revised at B2b: the open period is sent as still going
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
    assert v.end is None and v.end_unbounded and v.end_earliest is None  # revised at B2b: no stand-in end


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
    assert p.valid_time == TimeInterval(start_latest=_t(2024, 3, 5, *END_OF_DAY), end_unbounded=True)  # revised at B2b: begun no later than the said day; still going
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
    assert p.valid_time == TimeInterval(start_latest=_t(2024, 3, 31, *END_OF_DAY), end_unbounded=True)  # revised at B2b: begun no later than the said month
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
    assert v.end == _t(2022, 1, 1) and v.end_earliest == _t(2021, 1, 2) and not v.end_is_upper_bound  # revised at B2b: a closing date stated to the year bounds the end as a stated end does
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
    a, props = _sent(world)  # revised at B2b: no date is moved to make an interval valid: the job ended by 2021 and is left out as ended
    assert f"fact:{fid}" not in props and {l.fact_id: l.reason for l in a.left_out} == {fid: "ended before as_of"}
    assert not any(p.qualifiers.get("end_basis") == "adjusted" for p in props.values())


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
    assert p.occurred == Occurrence(_t(2022, 1, 1), _t(2022, 12, 31, *END_OF_DAY)) and p.valid_time is None  # revised at B2b: the stated year is the window
    assert p.qualifiers["time_kind"] == "event" and p.qualifiers["start_basis"] == "stated" and "end_basis" not in p.qualifiers


def test_b2a_an_event_dated_only_by_its_sentence_keeps_exactly_its_interval_and_is_labelled_first_said(world):
    """D2."""
    world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    left, _ = world.obs("Asha", "left_job", "Apollo")
    _, props = _sent(world, _t(2025, 6, 1))
    p = props[f"fact:{left}"]
    assert p.occurred == Occurrence(None, _t(2024, 3, 5, *END_OF_DAY)) and p.valid_time is None  # revised at B2b: no later than the said day, and no date
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
    assert (v.start, v.end, v.end_unbounded) == (_t(2026, 1, 1), None, True)  # revised at B2b: no stand-in end for the bound to run past
    assert v.start_latest == _t(2026, 12, 31, *END_OF_DAY)
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
    heading = ["strategy rule_reasoning@1.0, status complete, as of 2024-03-05, overall accepted, zone UTC",  # revised at B2b: this whole expectation: no invented end, said is not stated, the zone
               "conclusion: Asha works_in_city Bengaluru -> accepted (PREMISE_LINEAGE_COMPLETE_AND_SUPPORT_THRESHOLD_MET)"]
    located = ("  because: Manipal located_in Bengaluru", f"    {STATE}; valid 2010-01-01, still going",
               f'    sentence 2 (Manipal, {said}): "Manipal located_in Bengaluru."')
    works = ("  because: Asha works_at Manipal", f"    {STATE}; valid 2021-01-01, still going",
             f'    sentence 1 (Asha, {said}): "Asha works_at Manipal."')
    facts = [f"fact: Asha works_at Manipal; {STATE}; valid 2021-01-01, still going",
             f"fact: Asha lives_in Mysore; {STATE}; valid from no later than 2024-03-05, still going",
             f"fact: Asha left_job Apollo; {STATE}; event between 2022-01-01 and 2022-12-31",
             f"fact: Manipal located_in Bengaluru; {STATE}; valid 2010-01-01, still going"]
    before = (heading, sorted([located, works]), sorted((f,) for f in facts))
    assert _explained([l for l in lines if not l.lstrip().startswith("time:")]) == before
    in_2010 = "time: start stated, between 2010-01-01 and 2010-12-31; end open"
    in_2021 = "time: start stated, between 2021-01-01 and 2021-12-31; end open"
    times = [f"  {in_2021}", "  time: start not stated (first said 2024-03-05); end open", "  time: event stated, between 2022-01-01 and 2022-12-31", f"  {in_2010}"]
    after = (heading,
             sorted([(located[0], located[1], f"    {in_2010}", located[2]), (works[0], works[1], f"    {in_2021}", works[2])]),
             sorted(zip(facts, times)))
    assert _explained(lines) == after


@pytest.mark.parametrize("how,as_of,expected", [
    (dict(valid_from="2021-04-10"), AS_OF, "  time: start stated 2021-04-10; end open"),
    (dict(valid_from="2019", valid_to="2021-03"), AT_2020, "  time: start stated, between 2019-01-01 and 2019-12-31; end stated, between 2021-03-02 and 2021-04-01"),
    (dict(valid_from="2019", valid_to="2021-03-15"), AT_2020, "  time: start stated, between 2019-01-01 and 2019-12-31; end stated 2021-03-16"),
    (dict(valid_to="2021"), AS_OF, None),  # revised at B2b: first said after its own end: never sent, so no time line; no end is ever adjusted
], ids=["exact start", "end known to the month", "exact end", "adjusted end"])
def test_b2a_explain_time_line_for_each_kind_of_state_boundary(world, how, as_of, expected):
    """X1, the remaining wordings. An end is shown as the first day the state no longer holds, as the existing 'valid … to …' line does."""
    world.obs("Asha", "works_at", "Apollo", **how)
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=as_of))
    assert [l for l in lines if l.lstrip().startswith("time:")] == ([expected] if expected else [])
    if expected is None: assert any(l.startswith("left out: fact ") and "(ended before as_of;" in l for l in lines) and not any("adjusted" in l for l in lines)


def test_b2a_explain_time_lines_for_a_closed_period_its_closing_event_and_a_fact_with_no_time(world):
    """X1. A closed end is shown with Engram's word; an event dated only by its sentence says so; unknown time says so."""
    world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    world.obs("Asha", "left_job", "Apollo")                               # said 5 March 2024, no stated date
    world.obs("Asha", "located_in", "Bengaluru")                          # no valid time at all
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=AS_OF))
    assert _explained(lines)[2] == sorted([
        (f"fact: Asha works_at Apollo; {STATE}; valid 2019-01-01 to 2024-03-06 at the latest",  # revised at B2b: the closing date was only said
         "  time: start stated, between 2019-01-01 and 2019-12-31; end closed, no later than 2024-03-06"),
        (f"fact: Asha left_job Apollo; {STATE}; event by 2024-03-05",
         "  time: event not stated (first said 2024-03-05)"),
        ("fact: Asha located_in Bengaluru; state: status active, validation accepted, source explicit; sent as assertion with a qualifying "
         "state record (valid time unknown); valid time unknown",
         "  time: not known"),
    ])


# ======================================================================================================================
# B3 - ERC's comparison reads the temporal contract. End to end: the adapter is unchanged; what ERC decides is asserted.
# Specification: claude/erc-b3-spec.md (frozen 10 Nov 2026, SHA-256 a94eb532e5d8bcfb4fb220bdac72a6875bd1515897656ddb56470aa2339e4c86),
# section 7, tests X1 to X5; the scenario numbers S01 to S21 are its sections 2.4 and 2.5.
# A test that only says "this stays as it is" passes before B3 exists, so each such test first calls _b3_is_in().
# ======================================================================================================================
from engram_erc.primitives.comparison import TemporalRelation, _temporal_relation


def _b3_is_in():
    """A state still going from 2019 certainly overlaps one that held from 2020 to 2022. Before B3: unknown."""
    assert _temporal_relation(TimeInterval(_t(2019, 1, 1), end_unbounded=True), TimeInterval(_t(2020, 1, 1), _t(2022, 1, 1))) is TemporalRelation.OVERLAP


def _undated(world, speaker, text):
    """A sentence with no readable date: its fact has no first-said day."""
    world.m.open_chat(DAY); sid = world.m.add(speaker, text, date="sometime"); world.m.close_chat(write_note=False)
    return sid


def _s01(w): w.obs("Asha", "works_at", "Hospital Pune", valid_from="2019"); w.obs("Asha", "works_at", "Hospital Delhi", valid_from="2020", speaker="Ravi")
def _s02(w): w.obs("Asha", "lives_in", "Bengaluru", valid_from="2024"); w.obs("Asha", "lives_in", "Mysore", valid_from="2024", speaker="Ravi")
def _s03(w): w.obs("Asha", "lives_in", "Bengaluru", valid_from="2022"); w.obs("Asha", "lives_in", "Mysore", valid_from="2024", speaker="Ravi")
def _s04(w): w.obs("Asha", "lives_in", "Bengaluru", valid_from="2024-03"); w.obs("Asha", "lives_in", "Mysore", speaker="Ravi")
def _s05(w): w.obs("Asha", "lives_in", "Bengaluru"); w.obs("Asha", "lives_in", "Mysore", speaker="Ravi")
def _s06(w): w.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021", status="superseded"); w.obs("Asha", "works_at", "Manipal", valid_from="2021", speaker="Ravi")
def _s07(w): w.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021"); w.obs("Asha", "works_at", "Manipal", valid_from="2021", speaker="Ravi")
def _s08(w): w.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021"); w.obs("Asha", "works_at", "Manipal", valid_from="2021")
def _s09(w):
    w.obs("Asha", "works_at", "Apollo", valid_to="2021", status="superseded", sid=_undated(w, "Asha", "Asha works_at Apollo."))
    w.obs("Asha", "works_at", "Manipal", valid_from="2019", speaker="Ravi")
def _s10(w):
    w.obs("Asha", "works_at", "Apollo", valid_to="2021", status="superseded", sid=_undated(w, "Asha", "Asha works_at Apollo."))
    w.obs("Asha", "works_at", "Manipal", valid_to="2021", status="superseded", sid=_undated(w, "Ravi", "Asha works_at Manipal."))
def _s11(w): w.obs("Asha", "works_at", "Apollo", valid_to="2021"); w.obs("Asha", "works_at", "Manipal", speaker="Ravi")
def _s12(w): w.obs("Asha", "moved_to", "Pune", valid_from="2022"); w.obs("Asha", "moved_to", "Delhi", valid_from="2023")
def _s13(w): w.obs("Asha", "lives_in", "Bengaluru", valid_from="2023-02"); w.obs("Asha", "lives_in", "Mysore", valid_from="2023-09", speaker="Ravi")
def _s14(w): w.obs("Asha", "lives_in", "Pune", valid_from="2019", valid_to="2021-06"); w.obs("Asha", "lives_in", "Delhi", valid_from="2020", speaker="Ravi")
def _s15(w): w.obs("Asha", "lives_in", "Pune", valid_from="2019", valid_to="2021", status="superseded"); w.obs("Asha", "lives_in", "Delhi", valid_from="2021-02-10", speaker="Ravi")
def _s16(w): w.obs("Asha", "works_at", "Apollo", valid_from="2024"); w.obs("Asha", "left_job", "Apollo"); w.obs("Asha", "works_at", "Manipal", speaker="Ravi")
def _s21(w): w.obs("Asha", "lives_in", "Pune", valid_from="2019", valid_to="2021-06-30"); w.obs("Asha", "lives_in", "Delhi", valid_from="2021", speaker="Ravi")


AT_JUNE_2021 = dt.datetime(2021, 6, 1, tzinfo=UTC)
DEFINITE, POTENTIAL = ContradictionCertainty.DEFINITE, ContradictionCertainty.POTENTIAL


def _decided(world, build, as_of, ruleset=None):
    build(world)
    r = Reasoner(world.kb).reason("Asha", as_of=as_of, ruleset=ruleset)
    return r, ([c.certainty for c in r.orchestration.contradictions], r.result.status)


def test_b3_a_coarse_stated_end_no_longer_makes_a_definite_conflict_with_a_start_inside_its_window(world):
    """X1 (S15, OP-2). Lived in Pune 2019 to "2021" (history); lives in Delhi from 10 February 2021; asked 1 March 2021.
    Pune may have ended before 10 February, so the overlap is possible and not certain. At 103d2fd: definite, conflict."""
    r, decided = _decided(world, _s15, dt.datetime(2021, 3, 1, tzinfo=UTC))
    assert decided == ([POTENTIAL], ReasoningStatus.INDETERMINATE)
    assert not r.orchestration.stopped_before_inference


@pytest.mark.parametrize("build,as_of", [(_s02, AS_OF), (_s03, AS_OF), (_s04, AS_OF), (_s02, dt.datetime(2024, 2, 1, tzinfo=UTC))],
                         ids=["S02 both from the asked-in year", "S03 one from the asked-in year", "S04 asked-in month and first said",
                              "S17 asked before either was said"])
def test_b3_named_limitation_two_open_values_with_a_coarse_start_reaching_the_asked_at_date_are_potential_until_b2b(world, build, as_of):
    """X2. THE NAMED LIMITATION OF B3 - TO BE REVISED AT B2b, where the expected value becomes DEFINITE and CONFLICT.
    Engram holds both values as open and flags the conflict. The adapter still closes an open state the day after as_of, so
    the coarse start window passes that end and the period has no certain part. ERC's rule is right for what it is given;
    the adapter corrects the representation at B2b (end_unbounded). The honest spelling is proved definite today, at ERC
    level, in engram_erc/tests/test_temporal_comparison.py::test_r13_..."""
    r, decided = _decided(world, build, as_of)
    assert world.engine.get_current_state(world.kb.resolve("Asha"))["lives_in"].conflict     # Engram is certain
    # revised at B2b (frozen specification 621314c5, section 10, Group A): the limitation is corrected and ERC is certain too
    assert decided == ([DEFINITE], ReasoningStatus.CONFLICT)
    still_going = [p.valid_time for p in r.adapted.request.propositions if p.qualifiers.get("end_basis") == "open"]
    assert len(still_going) == 2 and all(i.end_unbounded and i.end is None for i in still_going)  # the correction, visible


@pytest.mark.parametrize("build,as_of", [(_s06, AT_JUNE_2021), (_s07, AT_JUNE_2021), (_s08, AT_JUNE_2021), (_s16, AS_OF), (_s21, AT_JUNE_2021)],
                         ids=["S06 job change in one year, as history", "S07 two speakers", "S08 one speaker, an ordinary change",
                              "S16 a genuinely closed end", "S21 a closed day-exact end"])
def test_b3_a_change_inside_one_coarse_period_is_a_potential_conflict_not_a_definite_one(world, build, as_of):
    """X3. A CORRECTION, NOT REVISED AT B2b: these stay potential. Leaving Apollo some time in 2021 and joining Manipal some
    time in 2021 is an ordinary change of job. At 103d2fd each was a definite conflict; Engram's own current state has none."""
    r, decided = _decided(world, build, as_of)
    assert not any(s.conflict for s in world.engine.get_current_state(world.kb.resolve("Asha")).values())
    assert decided == ([POTENTIAL], ReasoningStatus.INDETERMINATE)


@pytest.mark.parametrize("build,as_of,expected", [
    (_s01, AT_2023, ([DEFINITE], ReasoningStatus.CONFLICT)),
    (_s05, AS_OF, ([DEFINITE], ReasoningStatus.CONFLICT)),
    (_s11, AS_OF, ([], ReasoningStatus.COMPLETE)),              # revised at B2b (B3 amendment 1): no one-day minimum; the job that ended by 2021 is left out
    (_s13, AS_OF, ([DEFINITE], ReasoningStatus.CONFLICT)),
    (_s14, AT_JUNE_2021, ([DEFINITE], ReasoningStatus.CONFLICT)),
    (_s09, dt.datetime(2020, 6, 1, tzinfo=UTC), ([POTENTIAL], ReasoningStatus.INDETERMINATE)),
    (_s10, dt.datetime(2020, 6, 1, tzinfo=UTC), ([POTENTIAL], ReasoningStatus.INDETERMINATE)),
    (_s12, AS_OF, ([], ReasoningStatus.COMPLETE)),              # revised at B2b (B3 amendment 1): two moves at different known times cannot meet
], ids=["S01 starts already past", "S05 both first said", "S11 one-day minimum", "S13 different months of a past year",
        "S14 a real overlap of six months", "S09 end with no start", "S10 two ends with no start", "S12 two moves"])
def test_b3_results_that_do_not_change(world, build, as_of, expected):
    """X4. Beside the changes of X1 to X3: what ERC decides here is what it decided at 103d2fd."""
    _b3_is_in()
    assert _decided(world, build, as_of)[1] == expected


def test_b3_named_limitation_a_conclusion_resting_on_such_a_conflict_is_provisional_and_never_accepted_until_b2b(world):
    """X5 (S19, S20). THE NAMED LIMITATION OF B3 - TO BE REVISED AT B2b, where the run halts on a definite conflict again.
    Asha works at Apollo from "2024" and at Manipal from "2024" (two speakers); Manipal is in Bengaluru. Until B2b the
    conflict is potential, so the rule fires; the conclusion is provisional, says why, and is never accepted."""
    world.who("Manipal")
    world.obs("Asha", "works_at", "Apollo", valid_from="2024")
    world.obs("Asha", "works_at", "Manipal", valid_from="2024", speaker="Ravi")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF, ruleset=CITY)
    assert world.engine.get_current_state(world.kb.resolve("Asha"))["works_at"].conflict
    # revised at B2b (frozen specification 621314c5, section 10, S19): the limitation is corrected. Both jobs are sent as still going,
    # so the conflict Engram holds is definite again, the run halts before any rule fires and nothing is derived.
    assert [c.certainty for c in r.orchestration.contradictions] == [DEFINITE] and r.orchestration.stopped_before_inference
    assert r.result.status == ReasoningStatus.CONFLICT
    assert not [p for p in r.result.propositions if p.kind == PropositionKind.INFERENCE]
    assert r.evaluation.evaluations == () and not r.evaluation.accepted_refs


def test_b3_the_same_conclusion_with_no_second_value_is_accepted(world):
    """X5, the control (S20): with one employer and no conflict the conclusion is accepted, as at 103d2fd."""
    _b3_is_in()
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2024", speaker="Ravi")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF, ruleset=CITY)
    assert not r.orchestration.contradictions and r.evaluation.overall_decision.value == "accepted"


# ======================================================================================================================
# B2b - the adapter stops stating what Engram does not hold: open states are still going, a first-said day is the latest a
# state can have begun, a date that was only said is never an exact end, an event is an occurrence, no date is moved to
# make an interval valid, and the zone is declared. ERC and Engram are not touched.
# Specification: claude/erc-b2b-spec.md, frozen 10 Nov 2026 (Draft 5), SHA-256
# 621314c573ecbffcd82cf5295e3a0b98597fe750164c220c1d4d17356f5589c7. Section numbers below are its sections.
# The 29 existing tests it names (section 12.2) are revised in place above, each marked "revised at B2b".
# A test that says "this stays as it is" would pass before B2b exists, so each also asserts something new beside it.
# The explain() wording asserted here is that of the wording amendment (section 11.2, OP-11).
# ======================================================================================================================
import zoneinfo

from engram_knowledge.normalizer import PREDICATE_TYPES
from engram_knowledge.transition import CLOSES, OPENS

AT_2022 = dt.datetime(2022, 6, 1, tzinfo=UTC)
MICRO = dt.timedelta(microseconds=1)
Y2019 = dict(start_latest=dt.datetime(2019, 12, 31, *END_OF_DAY, tzinfo=UTC))
SAID_END = dt.datetime(2024, 3, 5, *END_OF_DAY, tzinfo=UTC)


def _dated(world, speaker, text, date):
    """A sentence said on a given date (text as Engram stores it)."""
    world.m.open_chat(DAY); sid = world.m.add(speaker, text, date=date); world.m.close_chat(write_note=False)
    return sid


def _in(world, zone, as_of, who="Asha"):
    a = KnowledgeAdapter(world.kb, day_zone=zone).request_for(who, as_of=as_of)
    return a, {p.id: p for p in a.request.propositions}


def _reasons(a):
    return {l.fact_id: l.reason for l in a.left_out}


# ----- Appendix A: what is sent, combination by combination -----
def _a_day_open(w): return w.obs("Asha", "works_at", "Apollo", valid_from="2021-04-10")[0]
def _a_year_open(w): return w.obs("Asha", "works_at", "Apollo", valid_from="2021")[0]
def _a_said_open(w): return w.obs("Asha", "works_at", "Apollo")[0]
def _a_day_stated(w): return w.obs("Asha", "works_at", "Apollo", valid_from="2019-05-01", valid_to="2021-03-15")[0]
def _a_year_stated(w): return w.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03")[0]
def _a_said_stated(w): return w.obs("Asha", "works_at", "Apollo", valid_to="2025")[0]
def _a_closed_day(w): fid = w.obs("Asha", "works_at", "Apollo", valid_from="2019")[0]; w.obs("Asha", "left_job", "Apollo", valid_from="2021-06-30"); return fid
def _a_closed_year(w): return _closed(w)[0]
def _a_closed_said(w): fid = w.obs("Asha", "works_at", "Apollo", valid_from="2019")[0]; w.obs("Asha", "left_job", "Apollo"); return fid
def _a_said_closed_said(w): fid = w.obs("Asha", "works_at", "Apollo")[0]; w.obs("Asha", "left_job", "Apollo"); return fid
def _a_replaced_stated(w): return _replaced(w)[0]
def _a_replaced_said(w): fid = w.obs("Asha", "lives_in", "Pune", valid_from="2019")[0]; w.obs("Asha", "lives_in", "Delhi"); return fid
def _a_none_stated(w): return w.obs("Asha", "works_at", "Apollo", valid_to="2021", sid=_undated(w, "Asha", "Asha works_at Apollo."))[0]
def _a_outside_open(w): return w.obs("Asha", "located_in", "Pune", valid_from="2010")[0]
def _a_none_open(w): return w.obs("Asha", "works_at", "Apollo", sid=_undated(w, "Asha", "Asha works_at Apollo."))[0]
def _a_outside_none(w): return w.obs("Asha", "located_in", "Pune")[0]


def _a_day_closed_day(w): fid = w.obs("Asha", "works_at", "Apollo", valid_from="2019-05-01")[0]; w.obs("Asha", "left_job", "Apollo", valid_from="2021-06-30"); return fid
def _a_day_closed_said(w): fid = w.obs("Asha", "works_at", "Apollo", valid_from="2019-05-01")[0]; w.obs("Asha", "left_job", "Apollo"); return fid
def _a_day_replaced_stated(w): fid = w.obs("Asha", "lives_in", "Pune", valid_from="2019-05-01")[0]; w.obs("Asha", "lives_in", "Delhi", valid_from="2022"); return fid
def _a_day_replaced_said(w): fid = w.obs("Asha", "lives_in", "Pune", valid_from="2019-05-01")[0]; w.obs("Asha", "lives_in", "Delhi"); return fid
def _a_said_closed_day(w): fid = w.obs("Asha", "works_at", "Apollo")[0]; w.obs("Asha", "left_job", "Apollo", valid_from="2024-06-30"); return fid
def _a_said_closed_year(w): fid = w.obs("Asha", "works_at", "Apollo")[0]; w.obs("Asha", "left_job", "Apollo", valid_from="2025"); return fid
def _a_said_replaced_stated(w): fid = w.obs("Asha", "lives_in", "Pune")[0]; w.obs("Asha", "lives_in", "Delhi", valid_from="2024-06-01"); return fid


def _a_said_replaced_said(w):
    fid = w.obs("Asha", "lives_in", "Pune")[0]
    w.obs("Asha", "lives_in", "Delhi", sid=_dated(w, "Asha", "Asha lives_in Delhi.", "1:00 pm on 10 April, 2024"))
    return fid


AT_APRIL_2024 = dt.datetime(2024, 4, 1, tzinfo=UTC)
SAID_START = dict(start_latest=SAID_END)
# (build, asked at, what is sent, (start_basis, end_basis), the Appendix A cell as Engram's own period shows it: (start, end_kind);
#  None for a fact outside every slot, which has no period)
APPENDIX_A = [
    (_a_day_open, AS_OF, TimeInterval(_t(2021, 4, 10), end_unbounded=True), ("stated", "open"), ("day", "open")),
    (_a_day_stated, AT_2020, TimeInterval(_t(2019, 5, 1), _t(2021, 3, 16)), ("stated", "stated"), ("day", "stated")),
    (_a_day_closed_day, AT_2020, TimeInterval(_t(2019, 5, 1), _t(2021, 7, 1)), ("stated", "closed"), ("day", "closed")),
    (_a_day_closed_said, AT_2020, TimeInterval(_t(2019, 5, 1), _t(2024, 3, 6), end_is_upper_bound=True), ("stated", "closed"), ("day", "closed")),
    (_a_day_replaced_stated, AT_2020, TimeInterval(_t(2019, 5, 1), _t(2022, 1, 1)), ("stated", "replaced"), ("day", "replaced")),
    (_a_day_replaced_said, AT_2020, TimeInterval(_t(2019, 5, 1), _t(2024, 3, 5), end_is_upper_bound=True), ("stated", "replaced"), ("day", "replaced")),
    (_a_year_open, AS_OF, TimeInterval(_t(2021, 1, 1), start_latest=_t(2021, 12, 31, *END_OF_DAY), end_unbounded=True), ("stated", "open"), ("coarse", "open")),
    (_a_year_stated, AT_2020, TimeInterval(_t(2019, 1, 1), _t(2021, 4, 1), end_earliest=_t(2021, 3, 2), **Y2019), ("stated", "stated"), ("coarse", "stated")),
    (_a_closed_day, AT_2020, TimeInterval(_t(2019, 1, 1), _t(2021, 7, 1), **Y2019), ("stated", "closed"), ("coarse", "closed")),
    (_a_closed_year, AT_2020, TimeInterval(_t(2019, 1, 1), _t(2022, 1, 1), end_earliest=_t(2021, 1, 2), **Y2019), ("stated", "closed"), ("coarse", "closed")),
    (_a_closed_said, AT_2022, TimeInterval(_t(2019, 1, 1), _t(2024, 3, 6), end_is_upper_bound=True, **Y2019), ("stated", "closed"), ("coarse", "closed")),
    (_a_replaced_stated, AT_2020, TimeInterval(_t(2019, 1, 1), _t(2022, 1, 1), **Y2019), ("stated", "replaced"), ("coarse", "replaced")),
    (_a_replaced_said, AT_2022, TimeInterval(_t(2019, 1, 1), _t(2024, 3, 5), end_is_upper_bound=True, **Y2019), ("stated", "replaced"), ("coarse", "replaced")),
    (_a_said_open, AS_OF, TimeInterval(end_unbounded=True, **SAID_START), ("first_said", "open"), ("said", "open")),
    (_a_said_stated, AS_OF, TimeInterval(None, _t(2026, 1, 1), end_earliest=_t(2025, 1, 2), **SAID_START), ("first_said", "stated"), ("said", "stated")),
    (_a_said_closed_day, AT_APRIL_2024, TimeInterval(None, _t(2024, 7, 1), **SAID_START), ("first_said", "closed"), ("said", "closed")),
    (_a_said_closed_year, AT_APRIL_2024, TimeInterval(None, _t(2026, 1, 1), end_earliest=_t(2025, 1, 2), **SAID_START), ("first_said", "closed"), ("said", "closed")),
    (_a_said_closed_said, AS_OF, TimeInterval(None, _t(2024, 3, 6), end_is_upper_bound=True, **SAID_START), ("first_said", "closed"), ("said", "closed")),
    (_a_said_replaced_stated, AT_APRIL_2024, TimeInterval(None, _t(2024, 6, 1), **SAID_START), ("first_said", "replaced"), ("said", "replaced")),
    (_a_said_replaced_said, AT_APRIL_2024, TimeInterval(None, _t(2024, 4, 10), end_is_upper_bound=True, **SAID_START), ("first_said", "replaced"), ("said", "replaced")),
    (_a_none_open, AS_OF, None, (None, None), ("none", "open")),
    (_a_none_stated, AT_2020, TimeInterval(None, _t(2022, 1, 1), end_earliest=_t(2021, 1, 2)), (None, "stated"), ("none", "stated")),
    (_a_outside_open, AS_OF, TimeInterval(_t(2010, 1, 1), start_latest=_t(2010, 12, 31, *END_OF_DAY), end_unbounded=True), ("stated", "open"), None),
    (_a_outside_none, AS_OF, None, (None, None), None),
]


def _cell(world, fid):
    """The Appendix A cell a fact sits in, read from the period Engram itself assembled: (start, end_kind)."""
    for slot in ("works_at", "lives_in"):
        for p in world.engine.get_history(world.kb.resolve("Asha"), slot, **PLAYED)["periods"]:
            if fid in p.fact_ids:
                start = ("day" if len(p.start.split("-")) == 3 else "coarse") if p.start else ("said" if p.first_said else "none")
                return start, p.end_kind
    return None


@pytest.mark.parametrize("build,as_of,expected,labels,cell", APPENDIX_A, ids=[
    "stated day | open", "stated day | stated", "stated day | closed, date stated", "stated day | closed, only said",
    "stated day | replaced, date stated", "stated day | replaced, only said",
    "stated year | open", "stated year | stated to the month", "stated year | closed, date stated to the day", "stated year | closed, date stated to the year",
    "stated year | closed, only said", "stated year | replaced, date stated", "stated year | replaced, only said",
    "first said | open", "first said | stated", "first said | closed, date stated to the day", "first said | closed, date stated to the year",
    "first said | closed, only said", "first said | replaced, date stated", "first said | replaced, only said",
    "none | open: time unknown", "none | stated", "outside every slot, start and no end", "outside every slot, no date: time unknown"])
def test_b2b_what_is_sent_for_each_reachable_combination_of_start_and_end(world, build, as_of, expected, labels, cell):
    """Appendix A, every one of its 20 cells marked R or U (some twice, for the precision of the closing date), and the two shapes
    of a fact outside every slot; sections 3, 4, 5. The cell is read back from Engram's own period, so each case is shown to be
    the combination it is named for. Field by field: TimeInterval equality compares all eight fields. A stated end, a stated-day
    closing date and a stated replacing date are sent exactly as before B2b; beside them the zone is reported."""
    fid = build(world)
    assert _cell(world, fid) == cell
    a, props = _sent(world, as_of)
    p = props[f"fact:{fid}"]
    assert p.valid_time == expected and p.occurred is None
    assert (p.qualifiers.get("start_basis"), p.qualifiers.get("end_basis")) == labels
    assert a.day_zone == "UTC"   # beside the cells that are sent exactly as before B2b
    if expected is None:  # OP-12: under the unknown-time guard, as an undated fact is
        assert p.qualifiers["valid_time"] == "unknown"
        assert next(e for e in a.request.evidence if e.id == f"state:{fid}").metadata["qualified_for"] == ("valid time unknown",)
    else:
        assert not any(e.id == f"state:{fid}" for e in a.request.evidence)


@pytest.mark.parametrize("slot,closer,then_sent", [
    ("works_at", dict(predicate="left_job", value="Apollo", valid_from="2021"), Occurrence(_t(2021, 1, 1), _t(2021, 12, 31, *END_OF_DAY))),
    ("works_at", dict(predicate="left_job", value="Apollo", valid_from=None), Occurrence(None, SAID_END)),
    ("lives_in", dict(predicate="lives_in", value="Delhi", valid_from="2022"), TimeInterval(_t(2022, 1, 1), start_latest=_t(2022, 12, 31, *END_OF_DAY), end_unbounded=True)),
    ("lives_in", dict(predicate="lives_in", value="Delhi", valid_from=None), TimeInterval(end_unbounded=True, **SAID_START)),
], ids=["none | closed, date stated", "none | closed, only said", "none | replaced, date stated", "none | replaced, only said"])
def test_b2b_engram_never_closes_or_replaces_a_value_that_has_no_start_of_any_kind(world, slot, closer, then_sent):
    """Appendix A, the four cells marked X. A value with no stated start and no readable said day, followed by a statement that
    would close or replace it. Engram plays an undated statement last, so nothing closes or replaces it: its period stays open
    with no start, and no period anywhere in the slot is closed or replaced with no start. The adapter sends it as time unknown
    (the 'none | open' cell), and the statement that came with it in its own new form."""
    value = "Apollo" if slot == "works_at" else "Pune"
    fid, _ = world.obs("Asha", slot, value, sid=_undated(world, "Asha", f"Asha {slot} {value}."))
    other, _ = world.obs("Asha", closer["predicate"], closer["value"], valid_from=closer["valid_from"])
    periods = world.engine.get_history(world.kb.resolve("Asha"), slot, **PLAYED)["periods"]
    mine = next(p for p in periods if fid in p.fact_ids)
    assert (mine.start, mine.first_said, mine.end, mine.end_kind) == (None, None, None, "open")
    assert not [p for p in periods if not p.start and not p.first_said and p.end_kind in ("closed", "replaced")]
    a, props = _sent(world, _t(2025, 1, 1))
    p = props[f"fact:{fid}"]
    assert p.valid_time is None and p.qualifiers["valid_time"] == "unknown" and "end_basis" not in p.qualifiers
    q = props[f"fact:{other}"]
    assert (q.occurred or q.valid_time) == then_sent


def _n_day(w): return [w.obs("Asha", "works_at", "Apollo", valid_from="2023-06-10", valid_to="2024-03")[0], w.obs("Asha", "works_at", "Apollo", valid_to="2021")[0]]
def _n_coarse(w): return [w.obs("Asha", "works_at", "Apollo", valid_from="2023-06", valid_to="2024-03")[0], w.obs("Asha", "works_at", "Apollo", valid_to="2021")[0]]
def _n_said(w): return [w.obs("Asha", "works_at", "Apollo", valid_to="2021")[0]]
def _n_stated_then_handed(w): return [w.obs("Asha", "works_at", "Apollo", valid_from="2023")[0]]
def _n_day_then_handed(w): return [w.obs("Asha", "works_at", "Apollo", valid_from="2023-06-10")[0]]
def _n_said_then_handed(w): return [w.obs("Asha", "works_at", "Apollo")[0]]


@pytest.mark.parametrize("build,handed,inconsistent", [
    (_n_day, None, True), (_n_coarse, None, True), (_n_said, None, False),
    (_n_stated_then_handed, ("2021", "closed"), True), (_n_stated_then_handed, ("2021", "replaced"), True),
    (_n_day_then_handed, ("2023-06-09", "closed"), True), (_n_day_then_handed, ("2023-06-09", "replaced"), True),   # ends the instant it starts
    (_n_said_then_handed, ("2021", "closed"), False), (_n_said_then_handed, ("2021", "replaced"), False),
], ids=["stated day | stated end before it", "stated month | stated end before it", "first said | stated end before it",
        "stated year | closed before it (handed)", "stated year | replaced before it (handed)",
        "stated day | closed the day before it (handed)", "stated day | replaced the day before it (handed)",
        "first said | closed before it (handed)", "first said | replaced before it (handed)"])
def test_b2b_a_period_whose_end_is_not_after_its_start_is_never_sent_whatever_ended_it(world, build, handed, inconsistent):
    """Appendix A, the cells marked N, at dates before, on and after each boundary. A stated start at or after the end: the period's
    dates are inconsistent, and that is the reason given, at every date. A first-said day at or after the end: not yet said
    before that day, ended from it on. Engram produced no closed or replaced end before a start in any probe (it plays statements
    in date order), so those six are handed to the adapter as periods, to hold the rule should Engram ever produce one. The stated-day pair ends on
    the day before it starts: its end, the first instant it no longer holds, is exactly its start, the boundary of the rule."""
    fids = build(world)
    periods = world.engine.get_history(world.kb.resolve("Asha"), "works_at", **PLAYED)["periods"]
    assert len(periods) == 1 and sorted(periods[0].fact_ids) == sorted(fids)   # one period holds every fact built here
    adapter = KnowledgeAdapter(world.kb)
    if handed:
        real = adapter.engine.get_history

        def ended_early(entity_id, predicate, **kwargs):
            history = real(entity_id, predicate, **kwargs)
            for p in history["periods"]: p.end, p.end_kind = handed
            return history
        adapter.engine.get_history = ended_early
    for as_of in (_t(2018, 6, 1), _t(2021, 12, 31), _t(2022, 1, 1), _t(2023, 1, 1), _t(2023, 6, 10), SAID - MICRO, SAID, SAID_END, _t(2025, 1, 1)):
        a = adapter.request_for("Asha", as_of=as_of)
        reason = "period dates inconsistent" if inconsistent else ("starts after as_of" if as_of < SAID else "ended before as_of")
        assert a.request.propositions == () and _reasons(a) == {f: reason for f in fids}, as_of


def test_b2b_nothing_that_is_sent_depends_on_the_asked_at_date_and_no_end_is_ever_invented(world):
    """Section 12.1, items 3 and 4. The same world asked at three dates: every fact sent at more than one of them has the same time."""
    world.obs("Asha", "works_at", "Apollo", valid_from="2021")
    world.obs("Asha", "lives_in", "Mysore")
    world.obs("Asha", "located_in", "Pune", valid_from="2010")
    world.obs("Asha", "moved_to", "Mysore", valid_from="2023")
    seen = {}
    for as_of in (AS_OF, _t(2024, 3, 5, 12), _t(2031, 1, 1)):
        _, props = _sent(world, as_of)
        assert len(props) == 4
        for pid, p in props.items():
            assert seen.setdefault(pid, (p.valid_time, p.occurred)) == (p.valid_time, p.occurred)
            assert p.qualifiers.get("end_basis") != "adjusted"
            if p.valid_time is not None: assert p.valid_time.end is None and p.valid_time.end_unbounded


# ----- section 10: the corrections stay potential -----
@pytest.mark.parametrize("build,as_of", [(_s06, AT_JUNE_2021), (_s07, AT_JUNE_2021), (_s08, AT_JUNE_2021), (_s15, dt.datetime(2021, 3, 1, tzinfo=UTC)),
                                         (_s16, AS_OF), (_s21, AT_JUNE_2021)], ids=["S06", "S07", "S08", "S15", "S16", "S21"])
def test_b2b_group_b_the_six_corrections_stay_potential_when_open_ends_are_sent_honestly(world, build, as_of):
    """Section 10, Group B (normative). B3's X1 and X3 hold these and are not edited; this holds them beside the new representation:
    the value still going is sent as still going, and the result is still a potential conflict, never a definite one."""
    r, decided = _decided(world, build, as_of)
    assert decided == ([POTENTIAL], ReasoningStatus.INDETERMINATE)
    going = [p.valid_time for p in r.adapted.request.propositions if p.qualifiers.get("end_basis") == "open"]
    assert len(going) == 1 and going[0].end_unbounded and going[0].end is None


# ----- section 8: no date is manufactured -----
def test_b2b_a_job_first_said_after_its_own_stated_end_is_never_sent_and_no_end_is_adjusted(world):
    """Shape (b), F18/S11. 'Worked at Apollo, to 2021', said on 5 March 2024. Asked before it was said: not yet known. Asked on or
    after: it ended by 2021. Before B2b it was sent, as a one-day job on 5 March 2024, when asked on that day."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_to="2021")
    for as_of, reason in [(AT_2020, "starts after as_of"), (SAID - MICRO, "starts after as_of"), (SAID, "ended before as_of"),
                          (SAID_END, "ended before as_of"), (_t(2025, 1, 1), "ended before as_of")]:
        a, props = _sent(world, as_of)
        assert props == {} and _reasons(a) == {fid: reason}, as_of


def test_b2b_a_period_whose_stated_start_is_after_its_stated_end_is_left_out_with_its_own_reason_and_is_no_bridge(world):
    """Shape (c), F22, OP-7. Two facts for one value merge into a period Engram holds as June 2023 to 2021. Every state fact dated by
    that period is left out, at any asked-at date, with the true reason; nothing is reached through it; no record is invented."""
    world.who("Manipal")
    one, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2023-06", valid_to="2024-03")
    two, _ = world.obs("Asha", "works_at", "Manipal", valid_to="2021")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    period = world.engine.get_history(world.kb.resolve("Asha"), "works_at", **PLAYED)["periods"][0]
    assert (period.start, period.end, sorted(period.fact_ids)) == ("2023-06", "2021", sorted([one, two]))
    for as_of in (_t(2018, 12, 31), _t(2023, 6, 1), _t(2023, 7, 1), _t(2024, 3, 4, 12), _t(2025, 1, 1)):
        a, props = _sent(world, as_of)
        assert props == {} and not a.request.evidence, as_of
        assert sorted((l.fact_id, l.reason, l.needs) for l in a.left_out) == sorted((f, "period dates inconsistent", "resolution") for f in (one, two))


def test_b2b_inconsistency_is_the_periods_not_one_facts_and_an_event_in_the_period_keeps_its_own_date(world):
    """Section 8, period-level. A valid period (2019 to 2021) containing a fact that on its own was first said after its end is dated
    normally. In an inconsistent period, an event filed there is still sent, by its own date."""
    a_fact, _ = world.obs("Asha", "lives_in", "Delhi", valid_from="2019")
    b_fact, _ = world.obs("Asha", "lives_in", "Delhi", valid_to="2021")          # no start of its own; said in 2024
    one, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2023-06", valid_to="2024-03")
    started, _ = world.obs("Asha", "started_job", "Apollo", valid_from="2023-07")
    two, _ = world.obs("Asha", "works_at", "Apollo", valid_to="2021")
    a, props = _sent(world, AT_2020)
    held = TimeInterval(_t(2019, 1, 1), _t(2022, 1, 1), end_earliest=_t(2021, 1, 2), **Y2019)
    assert props[f"fact:{a_fact}"].valid_time == held and props[f"fact:{b_fact}"].valid_time == held
    assert {k: v for k, v in _reasons(a).items() if k in (one, two)} == {one: "period dates inconsistent", two: "period dates inconsistent"}
    a, props = _sent(world, _t(2023, 8, 1))
    assert props[f"fact:{started}"].occurred == Occurrence(_t(2023, 7, 1), _t(2023, 7, 31, *END_OF_DAY))
    assert _reasons(a)[one] == _reasons(a)[two] == "period dates inconsistent"


# ----- section 9: the guards read Engram's dates, with today's inequalities -----
def test_b2b_guards_at_equality_a_fact_known_from_the_asked_at_instant_is_kept_and_one_ending_at_it_is_left_out(world):
    """Section 9. Starts on 5 March 2024; another ended on 4 March (so its end, the first instant it no longer held, is 5 March 00:00)."""
    starts, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2024-03-05")
    ended, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019", valid_to="2024-03-04")
    a, props = _sent(world, SAID)
    assert set(props) == {f"fact:{starts}"} and _reasons(a) == {ended: "ended before as_of"}
    assert props[f"fact:{starts}"].valid_time == TimeInterval(SAID, end_unbounded=True)
    a, props = _sent(world, SAID - MICRO)
    assert set(props) == {f"fact:{ended}"} and _reasons(a) == {starts: "starts after as_of"}
    a, props = _sent(world, (SAID - MICRO).astimezone(dt.timezone(dt.timedelta(hours=-5))))   # the same instant, written in another offset
    assert set(props) == {f"fact:{ended}"} and _reasons(a) == {starts: "starts after as_of"}


def test_b2b_guards_a_coarse_start_is_eligible_from_its_first_day_and_a_first_said_fact_does_not_answer_an_earlier_question(world):
    """Section 9. 'From 2026' is known from 1 January 2026, never only from its latest possible start. A value only first said on
    5 March 2024 is not known before that day. A state still going is never 'ended', however late it is asked."""
    coarse, _ = world.obs("Asha", "lives_in", "Mysore", valid_from="2026")
    said, _ = world.obs("Asha", "works_at", "Apollo")
    a, props = _sent(world, _t(2026, 1, 1))
    assert set(props) == {f"fact:{coarse}", f"fact:{said}"}
    a, props = _sent(world, _t(2026, 1, 1) - MICRO)
    assert set(props) == {f"fact:{said}"} and _reasons(a) == {coarse: "starts after as_of"}
    a, props = _sent(world, SAID - MICRO)
    assert props == {} and _reasons(a) == {coarse: "starts after as_of", said: "starts after as_of"}
    a, props = _sent(world, SAID)
    assert props[f"fact:{said}"].valid_time == TimeInterval(start_latest=SAID_END, end_unbounded=True)
    a, props = _sent(world, _t(2100, 1, 1))
    assert set(props) == {f"fact:{coarse}", f"fact:{said}"} and a.left_out == ()


# ----- section 5: the provenance of a replacing date -----
def _pune_then(world, *after):
    fid, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019")
    for predicate, value, when in after: world.obs("Asha", predicate, value, valid_from=when)
    return fid


@pytest.mark.parametrize("after,end,only_said", [
    ([("lives_in", "Delhi", "2024-03-05")], (2024, 3, 5), False),
    ([("lives_in", "Delhi", None)], (2024, 3, 5), True),
    ([("lives_in", "Delhi", None), ("moved_to", "Delhi", None)], (2024, 3, 5), True),
    ([("moved_to", "Mysore", None), ("lives_in", "Mysore", "2024-03-05")], (2024, 3, 5), False),
    ([("lives_in", "Mysore", "2024-03-05"), ("moved_to", "Mysore", None)], (2024, 3, 5), False),
], ids=["one candidate, stated", "one candidate, only said", "several, all only said", "mixed: only said entered first", "mixed: stated entered first"])
def test_b2b_a_replaced_end_is_an_upper_bound_only_when_no_replacing_fact_states_the_date(world, after, end, only_said):
    """Section 5, OP-4: an aggregation, not a search. All facts that could have replaced the value are taken together; if any
    states the date the end is stated and exact, in either order of entry; if none does it was only said and is an upper bound."""
    fid = _pune_then(world, *after)
    period = next(p for p in world.engine.get_history(world.kb.resolve("Asha"), "lives_in", **PLAYED)["periods"] if p.value == "Pune")
    assert (period.end, period.end_kind) == ("2024-03-04", "replaced")
    a, props = _sent(world, AT_2022)
    p = props[f"fact:{fid}"]
    assert p.valid_time == TimeInterval(_t(2019, 1, 1), _t(*end), end_is_upper_bound=only_said, **Y2019)
    assert p.qualifiers["end_basis"] == "replaced"
    assert a.day_zone == "UTC"   # beside the stated cases, which are sent exactly as before B2b


def test_b2b_a_replaced_end_with_no_replacing_fact_to_be_found_is_treated_as_only_said(world):
    """Section 5, the fallback: the weaker claim. Engram does not produce this (0 of 586 in the probe), so the period is handed to
    the adapter as replaced with nothing in the slot that could have replaced it."""
    fid, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019")
    adapter = KnowledgeAdapter(world.kb)
    real = adapter.engine.get_history

    def replaced_by_nothing(entity_id, predicate, **kwargs):
        history = real(entity_id, predicate, **kwargs)
        for p in history["periods"]: p.end, p.end_kind = "2021", "replaced"
        return history
    adapter.engine.get_history = replaced_by_nothing
    p = {p.id: p for p in adapter.request_for("Asha", as_of=AT_2020).request.propositions}[f"fact:{fid}"]
    assert p.valid_time == TimeInterval(_t(2019, 1, 1), _t(2022, 1, 1), end_is_upper_bound=True, **Y2019)


# ----- section 6: an event is an occurrence -----
@pytest.mark.parametrize("when,expected,basis", [
    ("2022", Occurrence(_t(2022, 1, 1), _t(2022, 12, 31, *END_OF_DAY)), "stated"),
    ("2022-03", Occurrence(_t(2022, 3, 1), _t(2022, 3, 31, *END_OF_DAY)), "stated"),
    ("2022-03-05", Occurrence(_t(2022, 3, 5), _t(2022, 3, 5, *END_OF_DAY)), "stated"),
    (None, Occurrence(None, SAID_END), "first_said"),
], ids=["stated to the year", "stated to the month", "stated to the day", "only said"])
def test_b2b_an_event_is_sent_as_an_occurrence_with_no_validity_interval(world, when, expected, basis):
    """Section 6. A stated date is the window in which it happened. Only said: no later than the day it was told, and no date."""
    moved, _ = world.obs("Asha", "moved_to", "Delhi", valid_from=when)
    a, props = _sent(world, _t(2025, 6, 1))
    p = props[f"fact:{moved}"]
    assert p.occurred == expected and p.valid_time is None
    assert (p.qualifiers["time_kind"], p.qualifiers["valid_time"], p.qualifiers["start_basis"]) == ("event", "known", basis)
    assert "end_basis" not in p.qualifiers and not any(e.id == f"state:{moved}" for e in a.request.evidence)


def test_b2b_the_said_day_bounds_an_event_only_under_the_three_conditions_and_the_event_vocabulary_is_pinned(world):
    """Section 6, OP-5. (1) The predicate is one of Engram's event predicates, all completed happenings: this set is pinned, and
    the test fails when a predicate is added or removed, so a new one cannot get the bound without a decision. (2) A plan is left
    out. (3) Only a sentence linked as supporting evidence gives the bound: a dated sentence that merely qualifies does not.
    Step 3a (the decision this test asks for; B2b Amendment 2): attended, visited and completed join the 14. The set is every
    vocabulary word typed as an event, and the 14 that open or close another word's slot are all still in it."""
    assert overlay_knowledge.EVENTS == frozenset({"started_job", "moved_to", "got_married", "bought", "adopted", "started_hobby", "joined",
                                                  "left_job", "divorced", "sold", "lost", "gave_away", "stopped_hobby", "left_group",
                                                  "attended", "visited", "completed"})
    assert overlay_knowledge.EVENTS == frozenset(w for w, t in PREDICATE_TYPES.items() if t == "event")
    assert frozenset(p for p, s in {**OPENS, **CLOSES}.items() if p != s) < overlay_knowledge.EVENTS
    told, _ = world.obs("Asha", "moved_to", "Delhi")
    planned, _ = world.obs("Asha", "moved_to", "Goa", plan=True)
    f = KnowledgeFact.create(world.who("Asha"), "sold", "text", "attribute", "explicit", object_value="car", validation_status="accepted")
    undated, dated = _undated(world, "Asha", "Asha sold car."), world.say("Ravi", "Asha sold car, I think.")
    world.engine.apply_observation(FactWithEvidence(f, (FactEvidence.create(f.fact_id, undated), FactEvidence.create(f.fact_id, dated, "qualifies"))))
    a, props = _sent(world, _t(2025, 6, 1))
    assert props[f"fact:{told}"].occurred == Occurrence(None, SAID_END)
    assert _reasons(a) == {planned: "plan"}
    sold = props[f"fact:{f.fact_id}"]
    assert sold.occurred is None and sold.valid_time is None and sold.qualifiers["valid_time"] == "unknown"
    assert next(e for e in a.request.evidence if e.id == f"state:{f.fact_id}").metadata["qualified_for"] == ("valid time unknown",)


def test_b2b_two_moves_at_different_known_times_no_longer_look_like_a_conflict_and_a_move_only_said_stays_uncertain(world):
    """Section 6 and section 10 (S12), through ERC: windows that cannot meet give no contradiction; a move only said, whose window
    has no earliest bound, may meet a dated one, so it is a potential contradiction and never a definite one."""
    world.obs("Asha", "moved_to", "Pune", valid_from="2022"); world.obs("Asha", "moved_to", "Delhi", valid_from="2023")
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF)
    assert r.orchestration.contradictions == () or list(r.orchestration.contradictions) == []
    world.obs("Asha", "moved_to", "Goa")
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF)
    assert {c.certainty for c in r.orchestration.contradictions} == {POTENTIAL}


# ----- section 11.2: explain() says where each date came from -----
def test_b2b_explain_shows_a_date_that_was_only_said_as_only_said_and_never_an_invented_end(world):
    """Section 11.2, OP-11 (wording amendment). A value replaced by a statement with no date; a job closed by a statement stated
    to the year; a value only first said and still going."""
    world.obs("Asha", "lives_in", "Pune", valid_from="2019"); world.obs("Asha", "lives_in", "Delhi")
    world.obs("Asha", "works_at", "Apollo", valid_from="2019"); world.obs("Asha", "left_job", "Apollo", valid_from="2021")
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=AT_2020))
    assert lines[0].endswith(", as of 2020-06-01, overall withheld, zone UTC")
    assert [block[:2] for block in _explained(lines)[2]] == sorted([   # the first two lines of each fact: its state line and its time line
        (f"fact: Asha lives_in Pune; {STATE}; valid 2019-01-01 to 2024-03-05 at the latest",
         "  time: start stated, between 2019-01-01 and 2019-12-31; end replaced, no later than 2024-03-05"),
        (f"fact: Asha works_at Apollo; {STATE}; valid 2019-01-01 to 2022-01-01",
         "  time: start stated, between 2019-01-01 and 2019-12-31; end closed, between 2021-01-02 and 2022-01-01"),
    ])
    lines = r.explain(r.reason("Asha", as_of=_t(2025, 1, 1)))
    assert (f"fact: Asha lives_in Delhi; {STATE}; valid from no later than 2024-03-05, still going", "  time: start not stated (first said 2024-03-05); end open") in [block[:2] for block in _explained(lines)[2]]
    assert (f"fact: Asha left_job Apollo; {STATE}; event between 2021-01-01 and 2021-12-31", "  time: event stated, between 2021-01-01 and 2021-12-31") in [block[:2] for block in _explained(lines)[2]]
    world.obs("Asha", "works_at", "Fortis", valid_to="2025")   # only first said, with a stated end: the same words, then the end
    lines = r.explain(r.reason("Asha", as_of=AS_OF))
    assert (f"fact: Asha works_at Fortis; {STATE}; valid from no later than 2024-03-05 to 2026-01-01",
            "  time: start not stated (first said 2024-03-05); end stated, between 2025-01-02 and 2026-01-01") in [block[:2] for block in _explained(lines)[2]]
    assert not any("valid by " in l for l in lines)


def test_b2b_explain_names_an_inconsistent_period_as_the_reason_a_fact_is_left_out(world):
    """Section 11.2."""
    one, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2023-06", valid_to="2024-03")
    two, _ = world.obs("Asha", "works_at", "Apollo", valid_to="2021")
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=_t(2023, 7, 1)))
    assert sorted(l for l in lines if l.startswith("left out:")) == sorted(
        f"left out: fact {f} (period dates inconsistent; status active, validation accepted, source explicit; needs resolution)" for f in (one, two))


# ----- section 7: the zone is a setting of each adapter -----
def test_b2b_the_default_zone_is_utc_and_an_explicit_utc_sends_exactly_the_same_instants(world):
    """Section 7. No zone given: UTC, reported as UTC. The zone is on the adapted request and in explain()'s heading."""
    fid, sid = world.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03")
    a0, p0 = _sent(world, AT_2020)
    a1, p1 = _in(world, "UTC", AT_2020)
    a2, p2 = _in(world, zoneinfo.ZoneInfo("UTC"), AT_2020)
    assert a0.day_zone == a1.day_zone == a2.day_zone == "UTC"
    expected = TimeInterval(_t(2019, 1, 1), _t(2021, 4, 1), end_earliest=_t(2021, 3, 2), **Y2019)
    assert [p[f"fact:{fid}"].valid_time for p in (p0, p1, p2)] == [expected] * 3
    assert _evidence(a1, f"sentence:{sid}").observed_at == SAID and _evidence(a1, f"sentence:{sid}").metadata["observed_latest"] == SAID_LATEST
    r = Reasoner(world.kb, day_zone="Asia/Kolkata")
    assert r.explain(r.reason("Asha", as_of=AT_2020))[0].endswith(", zone Asia/Kolkata")


def test_b2b_a_named_zone_puts_every_boundary_at_that_zones_calendar_day_including_month_and_year_ends(world):
    """Section 7. Asia/Kolkata: 'from 2019' begins at local midnight on 1 January 2019, which is 18:30 UTC the day before; the
    year's last instant is local; 'to March 2021' ends at local midnight on 1 April; the sentence's day is local too."""
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    at = lambda *parts: dt.datetime(*parts, tzinfo=ist)
    fid, sid = world.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03")
    moved, _ = world.obs("Asha", "moved_to", "Delhi", valid_from="2019-12")
    a, props = _in(world, "Asia/Kolkata", AT_2020)
    v = props[f"fact:{fid}"].valid_time
    assert a.day_zone == "Asia/Kolkata"
    assert (v.start, v.start_latest, v.end_earliest, v.end) == (at(2019, 1, 1), at(2019, 12, 31, *END_OF_DAY), at(2021, 3, 2), at(2021, 4, 1))
    assert v.start == _t(2018, 12, 31, 18, 30) and all(x.utcoffset() == dt.timedelta(hours=5, minutes=30) for x in (v.start, v.start_latest, v.end_earliest, v.end))
    assert props[f"fact:{moved}"].occurred == Occurrence(at(2019, 12, 1), at(2019, 12, 31, *END_OF_DAY))
    assert _evidence(a, f"sentence:{sid}").observed_at == at(2024, 3, 5)
    assert _evidence(a, f"sentence:{sid}").metadata["observed_latest"] == "2024-03-05T23:59:59.999999+05:30"


@pytest.mark.parametrize("day,hours", [("2024-03-10", 23), ("2024-11-03", 25), ("2024-06-01", 24)], ids=["a 23-hour day", "a 25-hour day", "an ordinary day"])
def test_b2b_a_day_shortened_or_lengthened_by_a_clock_change_runs_from_its_own_first_instant_to_its_own_last(world, day, hours):
    """Section 7, F35. America/New_York. The day's last instant is one microsecond before the next day's first instant, as an
    instant: never the first instant plus 24 hours."""
    ny = zoneinfo.ZoneInfo("America/New_York")
    y, m, d = (int(x) for x in day.split("-"))
    event, _ = world.obs("Asha", "moved_to", "Delhi", valid_from=day)
    state, _ = world.obs("Asha", "works_at", "Apollo", valid_from=day, valid_to=day)
    _, props = _in(world, "America/New_York", dt.datetime(y, m, d, 12, tzinfo=ny))
    o, v = props[f"fact:{event}"].occurred, props[f"fact:{state}"].valid_time
    assert o.earliest == v.start == dt.datetime(y, m, d, tzinfo=ny) and o.earliest.isoformat().startswith(f"{day}T00:00:00")
    assert o.latest.isoformat().startswith(f"{day}T23:59:59.999999")
    assert v.end.astimezone(UTC) - v.start.astimezone(UTC) == dt.timedelta(hours=hours)
    assert v.end.astimezone(UTC) - o.latest.astimezone(UTC) == MICRO


def test_b2b_the_asked_at_date_is_compared_as_an_instant_whatever_offset_or_zone_it_is_written_in(world):
    """Section 7, F34. Zone Asia/Kolkata; a job from 5 March 2024 and a home to 4 March. The boundary is IST midnight on 5 March,
    18:30 UTC on the 4th. The answer follows the instant, written in UTC, in IST or in New York time. Then the repeated hour in
    New York (3 November 2024, 01:30 twice): Python calls the two times equal; the guards answer for each as the instant it is."""
    starts, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2024-03-05")
    ended, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2019", valid_to="2024-03-04")
    boundary = _t(2024, 3, 4, 18, 30)
    ny = zoneinfo.ZoneInfo("America/New_York")
    for as_of in (boundary, boundary.astimezone(zoneinfo.ZoneInfo("Asia/Kolkata")), boundary.astimezone(ny)):
        a, props = _in(world, "Asia/Kolkata", as_of)
        assert set(props) == {f"fact:{starts}"} and _reasons(a) == {ended: "ended before as_of"}
    for as_of in (boundary - MICRO, (boundary - MICRO).astimezone(zoneinfo.ZoneInfo("Asia/Kolkata")), (boundary - MICRO).astimezone(ny)):
        a, props = _in(world, "Asia/Kolkata", as_of)
        assert set(props) == {f"fact:{ended}"} and _reasons(a) == {starts: "starts after as_of"}
    first, second = dt.datetime(2024, 11, 3, 1, 30, tzinfo=ny, fold=0), dt.datetime(2024, 11, 3, 1, 30, tzinfo=ny, fold=1)
    assert first == second and second.astimezone(UTC) - first.astimezone(UTC) == dt.timedelta(hours=1)
    nov, _ = world.obs("Asha", "job_title", "surgeon", valid_from="2024-11-03")
    for as_of in (first, second):
        a, props = _in(world, "America/New_York", as_of)
        assert f"fact:{nov}" in props and props[f"fact:{nov}"].valid_time.start.isoformat() == "2024-11-03T00:00:00-04:00"


def test_b2b_where_the_clock_goes_back_at_midnight_the_days_last_instant_is_its_second_2359_and_the_guards_follow_instants(world):
    """Section 7, F35, an acceptance requirement. America/Santiago, 14 March 2009: at midnight the clock went back to 23:00, so
    23:00 to midnight happened twice. The day's true last instant is the second 23:59:59.999999 (-04:00); clock arithmetic lands
    on the first (-03:00), an hour early. Through the adapter's own guards, at both occurrences of 23:30."""
    scl = zoneinfo.ZoneInfo("America/Santiago")
    event, _ = world.obs("Asha", "moved_to", "Delhi", valid_from="2009-03-14")
    ends, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2009-03-01", valid_to="2009-03-14")
    begins, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2009-03-15")
    first, second = dt.datetime(2009, 3, 14, 23, 30, tzinfo=scl, fold=0), dt.datetime(2009, 3, 14, 23, 30, tzinfo=scl, fold=1)
    assert second.astimezone(UTC) - first.astimezone(UTC) == dt.timedelta(hours=1)
    for as_of in (first, second):
        a, props = _in(world, "America/Santiago", as_of)
        assert set(props) == {f"fact:{event}", f"fact:{ends}"} and _reasons(a) == {begins: "starts after as_of"}
        o, v = props[f"fact:{event}"].occurred, props[f"fact:{ends}"].valid_time
        assert o.earliest.isoformat() == "2009-03-14T00:00:00-03:00" and o.latest.isoformat() == "2009-03-14T23:59:59.999999-04:00"
        assert v.end.isoformat() == "2009-03-15T00:00:00-04:00" and v.end.astimezone(UTC) - o.latest.astimezone(UTC) == MICRO
        assert v.end.astimezone(UTC) - o.earliest.astimezone(UTC) == dt.timedelta(hours=25)
    next_day = dt.datetime(2009, 3, 15, tzinfo=scl)
    a, props = _in(world, "America/Santiago", next_day)
    assert set(props) == {f"fact:{event}", f"fact:{begins}"} and _reasons(a) == {ends: "ended before as_of"}
    a, props = _in(world, "America/Santiago", (next_day.astimezone(UTC) - MICRO))
    assert set(props) == {f"fact:{event}", f"fact:{ends}"}


def test_b2b_a_day_whose_midnight_is_skipped_begins_at_the_first_time_that_did_occur_and_is_not_a_missing_day(world):
    """Section 7, F38, an acceptance requirement. America/Santiago, 11 October 2009: the clock went from midnight straight to 01:00.
    The day begins at 01:00 -03:00; the adapter sends that valid local time, never the label 00:00 -04:00 for a time that did not
    occur. The day before ends one microsecond earlier, at 23:59:59.999999 -04:00. Through the adapter's own guards at that first
    instant and one microsecond either side."""
    begins, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2009-10-11")
    before, _ = world.obs("Asha", "moved_to", "Delhi", valid_from="2009-10-10")
    ended, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2009-10-01", valid_to="2009-10-10")
    first = dt.datetime(2009, 10, 11, 4, 0, tzinfo=UTC)                         # 01:00 -03:00 in Santiago
    a, props = _in(world, "America/Santiago", first)
    v = props[f"fact:{begins}"].valid_time
    assert v == TimeInterval(first, end_unbounded=True) and v.start.isoformat() == "2009-10-11T01:00:00-03:00"
    assert props[f"fact:{begins}"].qualifiers["valid_time"] == "known" and not any(e.id == f"state:{begins}" for e in a.request.evidence)
    o = props[f"fact:{before}"].occurred
    assert o.latest.isoformat() == "2009-10-10T23:59:59.999999-04:00" and first - o.latest.astimezone(UTC) == MICRO
    assert _reasons(a) == {ended: "ended before as_of"}
    a, props = _in(world, "America/Santiago", first - MICRO)
    assert set(props) == {f"fact:{before}", f"fact:{ended}"} and _reasons(a) == {begins: "starts after as_of"}
    assert props[f"fact:{ended}"].valid_time.end.isoformat() == "2009-10-11T01:00:00-03:00"
    a, props = _in(world, "America/Santiago", first + MICRO)
    assert set(props) == {f"fact:{before}", f"fact:{begins}"} and _reasons(a) == {ended: "ended before as_of"}
    # An asked-at time written on Santiago's own clock as 00:30, a time that did not occur that night: as an instant it is 04:30 UTC,
    # half an hour after the day began. On the clock 00:30 is "before" 01:00; compared as instants, as it must be, the job has begun.
    written = dt.datetime(2009, 10, 11, 0, 30, tzinfo=zoneinfo.ZoneInfo("America/Santiago"))
    assert written.astimezone(UTC) == first + dt.timedelta(minutes=30) and written < v.start
    a, props = _in(world, "America/Santiago", written)
    assert set(props) == {f"fact:{before}", f"fact:{begins}"} and _reasons(a) == {ended: "ended before as_of"}


def test_b2b_two_adapters_with_different_zones_do_not_affect_one_another_and_the_module_default_is_untouched(world):
    """Section 7. The zone is fixed for the life of an adapter; nothing process-wide is written."""
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    kolkata, new_york = KnowledgeAdapter(world.kb, day_zone="Asia/Kolkata"), KnowledgeAdapter(world.kb, day_zone="America/New_York")
    starts = [(ad.day_zone, ad.request_for("Asha", as_of=AT_2020).request.propositions[0].valid_time.start.isoformat()) for ad in (kolkata, new_york, kolkata, new_york)]
    assert starts == [("Asia/Kolkata", "2019-01-01T00:00:00+05:30"), ("America/New_York", "2019-01-01T00:00:00-05:00")] * 2
    assert overlay_knowledge.DAY_ZONE is dt.timezone.utc
    assert _sent(world, AT_2020)[1][f"fact:{fid}"].valid_time.start == _t(2019, 1, 1)


def _nameless_zone():
    """A ZoneInfo read from data, not from a name: it is a real zone (UTC) and has no key to be reported by."""
    import io, struct
    return zoneinfo.ZoneInfo.from_file(io.BytesIO(b"TZif" + b"\x00" * 16 + struct.pack(">6l", 0, 0, 0, 0, 1, 4) + struct.pack(">lBB", 0, 0, 0) + b"UTC\x00"))


@pytest.mark.parametrize("setting", ["Mars/Olympus", "", "IST+5", 5.5, dt.timezone(dt.timedelta(hours=5, minutes=30)), dt.timezone.utc, _nameless_zone()],
                         ids=["an unknown name", "an empty name", "an offset written as a name", "a number", "a fixed offset", "the fixed UTC object",
                              "a ZoneInfo with no name"])
def test_b2b_a_zone_that_is_not_an_iana_name_or_a_zoneinfo_is_refused_and_never_replaced_by_utc(world, setting):
    """Section 7, the public contract."""
    with pytest.raises(ValueError):
        KnowledgeAdapter(world.kb, day_zone=setting)
    with pytest.raises(ValueError):
        Reasoner(world.kb, day_zone=setting)


def test_b2b_the_legacy_test_seam_still_works_and_is_reported_by_its_fixed_name(world, monkeypatch):
    """Section 7, the legacy test seam: replacing the module default with a fixed offset, as one B2a test does, still works and is
    reported by the offset's fixed name. It is a compatibility exception: the same offset cannot be given to day_zone (above)."""
    monkeypatch.setattr(overlay_knowledge, "DAY_ZONE", dt.timezone(dt.timedelta(hours=5, minutes=30)))
    fid, _ = world.obs("Asha", "works_at", "Apollo", valid_from="2019")
    a, props = _sent(world, AT_2020)
    assert a.day_zone == "UTC+05:30"
    assert props[f"fact:{fid}"].valid_time.start == dt.datetime(2019, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))


# ----- section 7.1: a calendar day that does not exist in the zone -----
APIA_AFTER = dt.datetime(2012, 6, 1, tzinfo=UTC)


def _nothing_is_dated_the_next_day(a):
    """No instant anywhere in the request falls on 31 December 2011 in Apia: the missing 30th was not moved to it."""
    apia = zoneinfo.ZoneInfo("Pacific/Apia")
    instants = []
    for p in a.request.propositions:
        t, o = p.valid_time, p.occurred
        if t is not None: instants += [t.start, t.end, t.start_latest, t.end_earliest]
        if o is not None: instants += [o.earliest, o.latest]
    instants += [e.observed_at for e in a.request.evidence]
    return not any(i is not None and i.astimezone(apia).date() in (dt.date(2011, 12, 31), dt.date(2011, 12, 30)) for i in instants)


@pytest.mark.parametrize("build", [
    lambda w: w.obs("Asha", "works_at", "Apollo", valid_from="2011-12-30")[0],
    lambda w: w.obs("Asha", "works_at", "Apollo", valid_from="2010", valid_to="2011-12-30")[0],
    lambda w: (w.obs("Asha", "works_at", "Apollo", valid_from="2010")[0], w.obs("Asha", "left_job", "Apollo", valid_from="2011-12-30"))[0],
    lambda w: w.obs("Asha", "moved_to", "Delhi", valid_from="2011-12-30")[0],
], ids=["a stated start", "a stated end", "a closing date", "an event's date"])
def test_b2b_a_date_that_does_not_exist_in_the_zone_is_never_moved_and_the_facts_time_is_not_established(world, build):
    """Section 7.1, F36, F37. Pacific/Apia skipped 30 December 2011. No instant is made from it and none from a neighbouring day;
    no partial interval is sent from the boundary that does exist; the fact goes under the existing unknown-time guard, and says
    why. In UTC, where the day exists, the same fact is dated normally."""
    fid = build(world)
    a, props = _in(world, "Pacific/Apia", APIA_AFTER)
    p = props[f"fact:{fid}"]
    assert p.valid_time is None and p.occurred is None and p.qualifiers["valid_time"] == "unknown"
    assert next(e for e in a.request.evidence if e.id == f"state:{fid}").metadata["qualified_for"] == ("valid time unknown", "date not in zone")
    assert _nothing_is_dated_the_next_day(a)
    r = Reasoner(world.kb, day_zone="Pacific/Apia")
    lines = r.explain(r.reason("Asha", as_of=APIA_AFTER))
    assert "  time: not known (date not in zone Pacific/Apia)" in lines
    a, props = _in(world, "UTC", dt.datetime(2011, 12, 30, 12, tzinfo=UTC))
    p = props[f"fact:{fid}"]
    assert (p.valid_time or p.occurred) is not None and p.qualifiers["valid_time"] == "known"


def test_b2b_a_sentence_said_on_a_day_that_does_not_exist_in_the_zone_gives_no_date_and_a_stated_month_is_unaffected(world):
    """Section 7.1. The said day is treated as a said date that cannot be read: no observation date, no first-said bound, so a
    value known only from it has no time. A day inside a stated month is not required: December 2011 in Apia is dated normally."""
    apia = zoneinfo.ZoneInfo("Pacific/Apia")
    sid = _dated(world, "Asha", "Asha works_at Apollo.", "1:00 pm on 30 December, 2011")
    said_only, _ = world.obs("Asha", "works_at", "Apollo", sid=sid)
    month, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2011-12")
    a, props = _in(world, "Pacific/Apia", APIA_AFTER)
    e = _evidence(a, f"sentence:{sid}")
    assert e.observed_at is None and "observed_latest" not in e.metadata
    p = props[f"fact:{said_only}"]
    assert p.valid_time is None and p.qualifiers["valid_time"] == "unknown"
    v = props[f"fact:{month}"].valid_time
    assert v == TimeInterval(dt.datetime(2011, 12, 1, tzinfo=apia), start_latest=dt.datetime(2011, 12, 31, *END_OF_DAY, tzinfo=apia), end_unbounded=True)
    assert v.start_latest.isoformat() == "2011-12-31T23:59:59.999999+14:00"
    # Added with the implementation: the same said day, and an end that was stated. The said day gives no bound; the stated end
    # stands. That is the "no start of any kind, stated end" shape, and it carries no start label.
    with_end, _ = world.obs("Asha", "job_title", "registrar", valid_to="2012", sid=_dated(world, "Asha", "Asha job_title registrar.", "1:00 pm on 30 December, 2011"))
    period = world.engine.get_history(world.kb.resolve("Asha"), "job_title", **PLAYED)["periods"][0]
    assert (period.start, period.first_said, period.end, period.end_kind) == (None, "2011-12-30", "2012", "stated")
    _, props = _in(world, "Pacific/Apia", APIA_AFTER)
    p = props[f"fact:{with_end}"]
    assert p.valid_time == TimeInterval(None, dt.datetime(2013, 1, 1, tzinfo=apia), end_earliest=dt.datetime(2012, 1, 2, tzinfo=apia))
    assert "start_basis" not in p.qualifiers and p.qualifiers["end_basis"] == "stated"


def test_b2b_a_superseded_fact_whose_end_is_a_day_missing_from_the_zone_is_left_out_as_end_not_known(world):
    """Section 7.1: as today for a superseded fact whose end is not known. In UTC the same fact is history, with its dates."""
    fid, _ = world.obs("Asha", "lives_in", "Pune", valid_from="2010", valid_to="2011-12-30", status="superseded")
    a, props = _in(world, "Pacific/Apia", dt.datetime(2011, 6, 1, tzinfo=UTC))
    assert props == {} and _reasons(a) == {fid: "superseded: end date unknown"}
    a, props = _in(world, "UTC", dt.datetime(2011, 6, 1, tzinfo=UTC))
    assert props[f"fact:{fid}"].valid_time.end == _t(2011, 12, 31)
