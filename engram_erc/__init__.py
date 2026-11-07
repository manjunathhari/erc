"""Engram Reasoning Core public contracts and graph implementation."""
from .contracts import (
    EdgeKind, Evidence, EvidenceKind, EvidenceLink, EvidenceRelation, GraphEdge,
    GraphNode, InferenceStep, Proposition, PropositionKind, ReasoningGraph,
    ReasoningRequest, ReasoningResult, ReasoningStatus, SourceKind, TimeInterval,
    TraceEntry, UncertaintyItem, UncertaintyKind, new_id,
)
from .graph import ReasoningGraphBuilder, ReasoningGraphView
from .validation import (
    find_inference_cycle, inference_dependencies, topological_inferences,
    validate_graph_bindings,
)

__version__ = "0.1.7"

__all__ = [
    "EdgeKind", "Evidence", "EvidenceKind", "EvidenceLink", "EvidenceRelation",
    "GraphEdge", "GraphNode", "InferenceStep", "Proposition", "PropositionKind",
    "ReasoningGraph", "ReasoningRequest", "ReasoningResult", "ReasoningStatus",
    "SourceKind", "TimeInterval", "TraceEntry", "UncertaintyItem",
    "UncertaintyKind", "new_id", "validate_graph_bindings",
    "ReasoningGraphBuilder", "ReasoningGraphView", "find_inference_cycle",
    "inference_dependencies", "topological_inferences",
    "ComparisonKind", "ComparisonResult", "TemporalRelation",
    "compare_propositions", "Contradiction", "ContradictionCertainty",
    "find_contradictions", "EvidenceAssessment",
    "EvidenceAssessmentStatus", "assess_evidence",
    "Variable", "PropositionPattern", "ConclusionTemplate",
    "RuleDefinition", "RuleSet", "RuleMatch", "ExecutionLimits",
    "RuleExecution", "match_rule", "execute_rules", "to_reasoning_result",
]

from .primitives import (
    ComparisonKind, ComparisonResult, TemporalRelation, compare_propositions,
    Contradiction, ContradictionCertainty, find_contradictions,
    EvidenceAssessment, EvidenceAssessmentStatus, assess_evidence,
)

from .rules import (
    Variable, PropositionPattern, ConclusionTemplate, RuleDefinition, RuleSet,
)
from .inference import (
    RuleMatch, ExecutionLimits, RuleExecution, match_rule, execute_rules,
    to_reasoning_result,
)

from .orchestration import (
    StrategyOperation, StrategyDefinition, StrategyCatalog,
    default_strategy_catalog, OrchestrationLimits, OrchestrationResult,
    orchestrate,
)
__all__ += [
    "StrategyOperation", "StrategyDefinition", "StrategyCatalog",
    "default_strategy_catalog", "OrchestrationLimits", "OrchestrationResult",
    "orchestrate",
]

from .evaluation import (
    ConclusionDecision, EscalationLevel, DecisionPolicy, PremiseCoverage,
    ConclusionEvaluation, EvaluationReport, evaluate_conclusions,
)
__all__ += [
    "ConclusionDecision", "EscalationLevel", "DecisionPolicy",
    "PremiseCoverage", "ConclusionEvaluation", "EvaluationReport",
    "evaluate_conclusions",
]

from .feedback import (
    OutcomeLabel, FeedbackTargetKind, OutcomeEvent, FeedbackLedger,
    FeedbackCounts, FeedbackMetric, FeedbackReport, summarize_feedback,
    make_feedback_event_id,
)
__all__ += [
    "OutcomeLabel", "FeedbackTargetKind", "OutcomeEvent", "FeedbackLedger",
    "FeedbackCounts", "FeedbackMetric", "FeedbackReport",
    "summarize_feedback", "make_feedback_event_id",
]

from .adaptation import (
    AdaptationStatus, ScoreOrigin, StrategyExperienceScore, AdaptationPolicy,
    StrategyRanking, AdaptationReport, strategy_ref, rank_eligible_strategies,
    rank_catalog_strategies,
)
__all__ += [
    "AdaptationStatus", "ScoreOrigin", "StrategyExperienceScore",
    "AdaptationPolicy", "StrategyRanking", "AdaptationReport",
    "strategy_ref", "rank_eligible_strategies", "rank_catalog_strategies",
]
__version__ = "0.1.8"

from .trace_learning import (
    TraceLearningStatus, TraceLearningPolicy, TraceOutcomeCounts,
    TracePatternMetric, TraceStepMetric, UnmatchedTraceOutcome,
    TraceLearningReport, learn_reasoning_traces,
)
__all__ += [
    "TraceLearningStatus", "TraceLearningPolicy", "TraceOutcomeCounts",
    "TracePatternMetric", "TraceStepMetric", "UnmatchedTraceOutcome",
    "TraceLearningReport", "learn_reasoning_traces",
]
__version__ = "0.1.9"

from .improvement import (
    ProposalKind, ReviewDisposition, ImprovementPolicy, ImprovementProposal,
    ProposalReport, ProposalReview, ProposalReviewLedger,
    generate_improvement_proposals,
)
__all__ += [
    "ProposalKind", "ReviewDisposition", "ImprovementPolicy",
    "ImprovementProposal", "ProposalReport", "ProposalReview",
    "ProposalReviewLedger", "generate_improvement_proposals",
]
__version__ = "0.2.0"

from .counterfactual import (
    ConclusionSignature, RegressionCase, CaseComparisonStatus, CaseReplay,
    RegressionSummary, CounterfactualReport, run_counterfactual_suite,
)
__all__ += [
    "ConclusionSignature", "RegressionCase", "CaseComparisonStatus",
    "CaseReplay", "RegressionSummary", "CounterfactualReport",
    "run_counterfactual_suite",
]
__version__ = "0.2.1"

from .generalization import (
    DatasetSplit, ValidationVerdict, ValidationCase, GeneralisationPolicy,
    SplitMetrics, ContextMetrics, GeneralisationReport, evaluate_generalisation,
)
__all__ += [
    "DatasetSplit", "ValidationVerdict", "ValidationCase",
    "GeneralisationPolicy", "SplitMetrics", "ContextMetrics",
    "GeneralisationReport", "evaluate_generalisation",
]
__version__ = "0.2.2"

from .temporal_external import (
    ValidationCohort, ValidationObservation, TemporalExternalPolicy, SiteMetrics,
    TemporalExternalReport, evaluate_temporal_external,
)
__all__ += [
    "ValidationCohort", "ValidationObservation", "TemporalExternalPolicy",
    "SiteMetrics", "TemporalExternalReport", "evaluate_temporal_external",
]
__version__ = "0.2.3"


from .statistics import (
    StatisticalPolicy, Interval, ContextUncertainty, CohortUncertainty,
    StatisticalRobustnessReport, quantify_temporal_external,
)
__all__ += [
    "StatisticalPolicy", "Interval", "ContextUncertainty", "CohortUncertainty",
    "StatisticalRobustnessReport", "quantify_temporal_external",
]
__version__ = "0.2.4"


from .calibration import (
    CalibrationOutcome, CalibrationObservation, CalibrationLedger,
    ReliabilityStatus, CalibrationPolicy, ReliabilityBin, CalibrationMetrics,
    ContextReliability, ReliabilityAlert, ReliabilityMonitoringReport,
    monitor_reliability,
)
__all__ += [
    "CalibrationOutcome", "CalibrationObservation", "CalibrationLedger",
    "ReliabilityStatus", "CalibrationPolicy", "ReliabilityBin",
    "CalibrationMetrics", "ContextReliability", "ReliabilityAlert",
    "ReliabilityMonitoringReport", "monitor_reliability",
]
__version__ = "0.2.5"
