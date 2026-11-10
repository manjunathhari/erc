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
    w.obs("Manipal", "located_in", "Bengaluru")
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
from engram_erc import EvidenceRelation
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
    world.obs("Manipal", "located_in", "Bengaluru")
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
    world.obs("Manipal", "located_in", "Bengaluru")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert r.result.conclusion_refs, "the rule still fires"
    assert r.evaluation.overall_decision.value == "provisional"
    ev = r.evaluation.evaluations[0]
    assert "QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION" in ev.reasons and ev.escalation.value == "review"


def test_the_state_record_is_never_counted_as_corroboration(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021", validation="pending")
    world.obs("Manipal", "located_in", "Bengaluru")
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


def test_the_same_history_answers_a_question_asked_as_of_2020(world):
    world.who("Manipal")
    old, _ = world.obs("Asha", "works_at", "Manipal", valid_from="2019", valid_to="2021", status="superseded")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2019")
    r = Reasoner(world.kb).reason("Asha", ruleset=CITY, as_of=dt.datetime(2020, 6, 1, tzinfo=dt.timezone.utc))
    props = {p.id: p for p in r.result.propositions}
    assert f"fact:{old}" in props and props[f"fact:{old}"].qualifiers["status"] == "superseded"
    derived = [p for p in r.result.propositions if p.kind == PropositionKind.INFERENCE]
    assert [(p.predicate, p.object_value) for p in derived] == [("works_in_city", "Bengaluru")]


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
    assert lines[i + 1] == "    state: status active, validation pending, source explicit; sent as hypothesis with a qualifying state record; valid 2021-01-01 to 2024-03-06"
    assert lines[lines.index("  because: Manipal located_in Bengaluru") + 1] == "    state: status active, validation accepted, source explicit; sent as assertion; valid time unknown"
    assert "fact: Asha works_at Manipal; state: status active, validation pending, source explicit; sent as hypothesis with a qualifying state record; valid 2021-01-01 to 2024-03-06" in lines
