"""Illustrative ERC-3.2 call pattern; host supplies validated source refs."""
from engram_erc import (
    DecisionOption, OptionEvidence, DecisionSupportRequest,
    build_decision_support,
)

# `surgical_reasoning_report` must be produced by ERC-3.1 using a validated
# case snapshot and lifecycle-governed knowledge.

def create_report(surgical_reasoning_report):
    request = DecisionSupportRequest(
        request_id="case-decision-001",
        reasoning_report=surgical_reasoning_report,
        options=(DecisionOption(
            option_id="option-a",
            label="Option A",
            description="A host-authored description of an option.",
            knowledge_refs=("governed-knowledge-ref",),
            evidence=(OptionEvidence(
                evidence_ref="study-ref-1",
                relation="supports",
                source_ref="literature-store:study-1",
                knowledge_ref="governed-knowledge-ref",
            ),),
        ),),
    )
    return build_decision_support(request)
