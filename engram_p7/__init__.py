"""P7, carrying learned intelligence between installations: never memories, facts or conversations, only P6's context-level scores.

P7.1 intelligence (extract and package), P7.2 context_transfer (portable context priors), P7.3 compatibility (validate; never activates),
P7.4 restoration (stage, activate, roll back), P7.5 portability (cross-installation test harness), P7.6 adaptation (inherited prior plus
local policy, reordering candidates only), P7.7 benchmark (baseline against inherited rankings). P7 reads P6's tables; nothing inside reads P7.
"""
from .intelligence import IntelligenceExporter, IntelligenceExportError
from .context_transfer import ContextPolicyTransfer, ContextTransferError
from .compatibility import DestinationProfile, ModelCompatibilityValidator, CompatibilityValidationError
from .restoration import IntelligenceRestorer, RestorationError
from .portability import CrossInstallationHarness, ScenarioResult, PortabilityTestError, build_summary
from .adaptation import AdaptedRanking, DestinationIntelligenceAdapter, EffectiveMultiplier, RetrievalIntegrationError
from .benchmark import BenchmarkError, RetrievalBenchmark, make_dataset_row

__all__ = [
    "IntelligenceExporter", "IntelligenceExportError", "ContextPolicyTransfer", "ContextTransferError",
    "DestinationProfile", "ModelCompatibilityValidator", "CompatibilityValidationError", "IntelligenceRestorer", "RestorationError",
    "CrossInstallationHarness", "ScenarioResult", "PortabilityTestError", "build_summary",
    "AdaptedRanking", "DestinationIntelligenceAdapter", "EffectiveMultiplier", "RetrievalIntegrationError",
    "BenchmarkError", "RetrievalBenchmark", "make_dataset_row",
]
