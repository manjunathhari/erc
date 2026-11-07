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

    def obs(self, subject, predicate, value, valid_from=None, speaker=None, source_type="explicit", sid=None, plan=False):
        sid = sid or self.say(speaker or subject, f"{subject} {predicate} {value}.")
        f = KnowledgeFact.create(self.who(subject), predicate, "text", "plan" if plan else "attribute", source_type, object_value=value,
                                 valid_from=valid_from, validation_status="accepted")
        self.engine.apply_observation(FactWithEvidence(f, (FactEvidence.create(f.fact_id, sid),)))
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
    assert any(why == "starts after as_of" for _, why in before.adapted.left_out)


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
    assert f"fact:{plan}" not in kinds and (plan, "plan") in a.left_out


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
