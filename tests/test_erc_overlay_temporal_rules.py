"""B4 through the adapter (specification claude/erc-b4-spec.md, frozen 11 Nov 2026, criterion A9): a rule that declares a
temporal requirement and is not applied shows in explain() as an `uncertain:` line, with no change in the adapter.

tests/test_erc_overlay.py is not edited by B4; this file borrows its world. Made-up people only.
"""
from engram_erc import ConclusionTemplate, PropositionPattern, RuleDefinition, RuleSet, Variable
from erc_overlay import Reasoner

from test_erc_overlay import AS_OF, CITY, world  # noqa: F401  (world is a fixture)

X, C, Y = Variable("x"), Variable("c"), Variable("y")


def declared():
    from engram_erc import TemporalConstraint
    return RuleSet((RuleDefinition("works_in_city", "1",
                                   (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
                                   ConclusionTemplate(X, "works_in_city", Y),
                                   temporal=(TemporalConstraint("overlaps", "job", "place"),)),))


def test_b4_a9_explain_prints_the_rule_that_was_not_applied(world):
    """Asha's job is dated; where Manipal is has no date, so Engram's time for it is unknown. The undeclared rule gives today's
    provisional conclusion (the adapter's guard). The declared rule gives none, and says why."""
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021")
    world.obs("Manipal", "located_in", "Bengaluru")
    r = Reasoner(world.kb)
    plain = r.reason("Asha", ruleset=CITY, as_of=AS_OF)
    assert plain.evaluation.overall_decision.value == "provisional" and len(plain.result.conclusion_refs) == 1
    run = r.reason("Asha", ruleset=declared(), as_of=AS_OF)
    assert run.result.conclusion_refs == () and run.evaluation.overall_decision.value == "withheld"
    assert run.result.status.value == "indeterminate"
    lines = r.explain(run)
    wanted = ("uncertain: Rule works_in_city@1 not applied: whether job and place hold at the same time cannot be established "
              "(place carries no time).")
    assert lines.count(wanted) == 1
    assert lines[0].startswith("strategy rule_reasoning@1.0, status indeterminate, as of 2024-03-05, overall withheld")
    assert not any(line.startswith("conclusion:") for line in lines)
    # every fact is still shown exactly as the undeclared run shows it
    assert [l for l in lines if l.startswith(("fact:", "  time:", "left out:"))] == [l for l in r.explain(plain) if l.startswith(("fact:", "  time:", "left out:"))]


def test_b4_a_declared_rule_over_two_dated_overlapping_facts_gives_the_same_accepted_conclusion(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb)
    plain, run = r.reason("Asha", ruleset=CITY, as_of=AS_OF), r.reason("Asha", ruleset=declared(), as_of=AS_OF)
    assert run.evaluation.overall_decision.value == plain.evaluation.overall_decision.value == "accepted"
    assert run.result.conclusion_refs == plain.result.conclusion_refs and run.result.uncertainty == plain.result.uncertainty
    (step,) = run.result.inference_steps
    assert step.parameters["temporal"] == [{"relation": "overlaps", "left": "job", "right": "place", "outcome": "established"}]
    assert r.explain(run) == r.explain(plain)
