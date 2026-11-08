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

from .failure_analysis import (
    FailureCategory, FailureSymptom, AttributionStatus, SignalKind,
    FailureSignal, FailureCase, FailureAnalysisPolicy, RootCauseAttribution,
    FailureCaseAnalysis, FailureAnalysisReport, analyze_reasoning_failures,
)
__all__ += [
    "FailureCategory", "FailureSymptom", "AttributionStatus", "SignalKind",
    "FailureSignal", "FailureCase", "FailureAnalysisPolicy", "RootCauseAttribution",
    "FailureCaseAnalysis", "FailureAnalysisReport", "analyze_reasoning_failures",
]
__version__ = "0.2.6"


from .recovery import (
    GuardStatus, RecoveryStatus, GuardKind, RecoveryPolicy, RecoveryRequest,
    GuardCheck, RecoveryReport, run_guarded_recovery,
)
__all__ += [
    "GuardStatus", "RecoveryStatus", "GuardKind", "RecoveryPolicy",
    "RecoveryRequest", "GuardCheck", "RecoveryReport", "run_guarded_recovery",
]
__version__ = "0.2.7"


from .consolidation import (
    ExperienceOutcome, ConsolidationStatus, ConsolidationDisposition,
    ExperienceRecord, ConsolidationPolicy, ExperienceCounts,
    ExperienceCandidate, ConsolidationReport, ConsolidationReview,
    ConsolidationReviewLedger, consolidate_experience,
    apply_consolidation_reviews,
)
__all__ += [
    "ExperienceOutcome", "ConsolidationStatus", "ConsolidationDisposition",
    "ExperienceRecord", "ConsolidationPolicy", "ExperienceCounts",
    "ExperienceCandidate", "ConsolidationReport", "ConsolidationReview",
    "ConsolidationReviewLedger", "consolidate_experience",
    "apply_consolidation_reviews",
]
__version__ = "0.2.8"

from .lifecycle import (
    KnowledgeStage, EvidenceRelation as KnowledgeEvidenceRelation, EvidenceClass,
    LifecycleAction, EvidenceLinkRecord, ExternalValidationRecord,
    PromotionPolicy, PromotionAssessment, assess_promotion, LifecycleEvent,
    KnowledgeLifecycleLedger, KnowledgeStoreAdapter, build_lifecycle_event,
)
__all__ += [
    "KnowledgeStage", "KnowledgeEvidenceRelation", "EvidenceClass",
    "LifecycleAction", "EvidenceLinkRecord", "ExternalValidationRecord",
    "PromotionPolicy", "PromotionAssessment", "assess_promotion",
    "LifecycleEvent", "KnowledgeLifecycleLedger", "KnowledgeStoreAdapter",
    "build_lifecycle_event",
]
__version__ = "0.2.9"

from .application import (
    ConditionOperator, ConditionPolarity, ApplicabilityStatus, ContextFact,
    CaseContext, ApplicabilityCondition, GovernedKnowledge, ConditionResult,
    KnowledgeApplication, ApplicationReport, assess_knowledge_application,
    apply_contextual_knowledge,
)
__all__ += [
    "ConditionOperator", "ConditionPolarity", "ApplicabilityStatus",
    "ContextFact", "CaseContext", "ApplicabilityCondition",
    "GovernedKnowledge", "ConditionResult", "KnowledgeApplication",
    "ApplicationReport", "assess_knowledge_application",
    "apply_contextual_knowledge",
]
__version__ = "0.3.0"

from .task_orchestration import (
    CaseTaskStatus, CaseReasoningPolicy, CaseReasoningReport,
    orchestrate_case_reasoning,
)
__all__ += [
    "CaseTaskStatus", "CaseReasoningPolicy", "CaseReasoningReport",
    "orchestrate_case_reasoning",
]
__version__ = "0.3.1"

from .decision_support import (
    OptionAssessmentStatus, RiskSeverity, DecisionSupportStatus,
    ReviewerDisposition, OptionEvidence, RiskSignal, EscalationTrigger,
    DecisionOption, OptionAssessment, DecisionSupportRequest,
    DecisionSupportReport, ReviewerDecision, ReviewerDecisionLedger,
    assess_option, build_decision_support, record_reviewer_decision,
)
__all__ += [
    "OptionAssessmentStatus", "RiskSeverity", "DecisionSupportStatus",
    "ReviewerDisposition", "OptionEvidence", "RiskSignal",
    "EscalationTrigger", "DecisionOption", "OptionAssessment",
    "DecisionSupportRequest", "DecisionSupportReport", "ReviewerDecision",
    "ReviewerDecisionLedger", "assess_option", "build_decision_support",
    "record_reviewer_decision",
]
__version__ = "0.3.2"

from .situation_awareness import (
    TriggerOperator, SignalStatus, SignalTransitionKind, ObservationEvent,
    TriggerRule, SignalEvaluation, SignalTransition, SituationLedger,
    SituationPolicy, SituationReport, evaluate_situation,
)
__all__ += [
    "TriggerOperator", "SignalStatus", "SignalTransitionKind",
    "ObservationEvent", "TriggerRule", "SignalEvaluation",
    "SignalTransition", "SituationLedger", "SituationPolicy",
    "SituationReport", "evaluate_situation",
]
__version__ = "0.3.3"

from .temporal_patterns import (
    EpisodeOutcome, MatchDisposition, TrajectoryEvent, CaseTrajectory,
    HistoricalEpisode, TemporalMatchPolicy, EventAlignment,
    TrajectoryDifference, EpisodeMatch, TemporalPatternReport,
    match_temporal_experience,
)
__all__ += [
    "EpisodeOutcome", "MatchDisposition", "TrajectoryEvent", "CaseTrajectory",
    "HistoricalEpisode", "TemporalMatchPolicy", "EventAlignment",
    "TrajectoryDifference", "EpisodeMatch", "TemporalPatternReport",
    "match_temporal_experience",
]
__version__ = "0.3.4"

from .experience_reasoning import (
    ComparisonStatus, HistoricalAction, HistoricalExperienceDetail,
    ExperienceComparisonPolicy, OutcomeCounts, ActionOutcomeComparison,
    ExperienceCaseExplanation, ExperienceReasoningReport,
    compare_case_experience,
)
__all__ += [
    "ComparisonStatus", "HistoricalAction", "HistoricalExperienceDetail",
    "ExperienceComparisonPolicy", "OutcomeCounts", "ActionOutcomeComparison",
    "ExperienceCaseExplanation", "ExperienceReasoningReport",
    "compare_case_experience",
]
__version__ = "0.3.5"

from .prospective_learning import (
    ProspectiveEventKind, ProspectiveCaseStatus, ProspectiveCase,
    ProspectiveEvent, ProspectiveLearningLedger, CaseLearningStatus,
    inspect_prospective_case, to_feedback_event, append_feedback,
    to_experience_record,
)
__all__ += [
    "ProspectiveEventKind", "ProspectiveCaseStatus", "ProspectiveCase",
    "ProspectiveEvent", "ProspectiveLearningLedger", "CaseLearningStatus",
    "inspect_prospective_case", "to_feedback_event", "append_feedback",
    "to_experience_record",
]
__version__ = "0.3.6"

from .longitudinal_learning import (
    PatternMaturity, LongitudinalObservation, LongitudinalPolicy,
    OutcomeDistribution, CasePatternSummary, ActionPatternSummary,
    LongitudinalLearningReport, analyze_longitudinal_learning,
)
__all__ += [
    "PatternMaturity", "LongitudinalObservation", "LongitudinalPolicy",
    "OutcomeDistribution", "CasePatternSummary", "ActionPatternSummary",
    "LongitudinalLearningReport", "analyze_longitudinal_learning",
]
__version__ = "0.3.7"

from .knowledge_synthesis import (
    LocalSignal, PopulationApplicability, SynthesisStatus, PracticeDisposition,
    ReviewDecision, LocalPracticeClaim, ExternalEvidence, SynthesisPolicy,
    EvidenceSynthesisItem, PracticeIntelligenceItem, KnowledgeSynthesisReport,
    synthesize_practice_intelligence, PracticeReview, PracticeReviewLedger,
    build_practice_review,
)
__all__ += [
    "LocalSignal", "PopulationApplicability", "SynthesisStatus",
    "PracticeDisposition", "ReviewDecision", "LocalPracticeClaim",
    "ExternalEvidence", "SynthesisPolicy", "EvidenceSynthesisItem",
    "PracticeIntelligenceItem", "KnowledgeSynthesisReport",
    "synthesize_practice_intelligence", "PracticeReview",
    "PracticeReviewLedger", "build_practice_review",
]
__version__ = "0.3.8"

from .knowledge_graph import (
    KnowledgeNodeKind, KnowledgeRelation, TransferStatus, KnowledgeNode,
    KnowledgeEdge, DomainKnowledgeGraph, CrossDomainPolicy, CrossDomainQuery,
    KnowledgePath, CrossDomainFinding, CrossDomainReasoningReport,
    build_knowledge_graph, reason_across_domains,
)
__all__ += [
    "KnowledgeNodeKind", "KnowledgeRelation", "TransferStatus", "KnowledgeNode",
    "KnowledgeEdge", "DomainKnowledgeGraph", "CrossDomainPolicy", "CrossDomainQuery",
    "KnowledgePath", "CrossDomainFinding", "CrossDomainReasoningReport",
    "build_knowledge_graph", "reason_across_domains",
]
__version__ = "0.3.9"

from .case_intelligence import (
    ExecutionStatus, ExecutionStage, ExecutionPolicy, CaseIntelligenceRequest,
    StageResult, CaseIntelligenceReport, execute_case_intelligence,
)
__all__ += [
    "ExecutionStatus", "ExecutionStage", "ExecutionPolicy",
    "CaseIntelligenceRequest", "StageResult", "CaseIntelligenceReport",
    "execute_case_intelligence",
]

from .profiles import DomainProfile, get_profile, register_profile, registered_profiles
from .profiles.general import GENERAL_PROFILE
__all__ += [
    "DomainProfile", "get_profile", "register_profile", "registered_profiles",
    "GENERAL_PROFILE",
]

# Deprecated names from the 0.4.0 surgical release (removed in the next release). Importing compat also registers the
# field profile shipped with this release; it never changes core behaviour.
from . import compat as _compat
_compat.install()


def _read_version() -> str:
    from pathlib import Path
    return (Path(__file__).with_name("VERSION")).read_text(encoding="utf-8").strip()


__version__ = _read_version()
