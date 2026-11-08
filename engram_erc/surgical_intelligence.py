"""Deprecated: module name from the 0.4.0 surgical release. Use ``engram_erc.case_intelligence``.

Re-exports the 0.4.0 names from ``case_intelligence``. Removed in the next release.
"""
import warnings as _warnings

from .case_intelligence import *  # noqa: F401,F403
from .case_intelligence import (  # noqa: F401
    CaseIntelligenceReport as _Report,
    CaseIntelligenceRequest as _Request,
    ExecutionPolicy, ExecutionStage, ExecutionStatus, StageResult,
    execute_case_intelligence as _execute,
)

_warnings.warn(
    "engram_erc.surgical_intelligence is deprecated since ERC-4.0 General Core; use engram_erc.case_intelligence. "
    "It will be removed in the next release.", DeprecationWarning, stacklevel=2)

SurgicalIntelligenceRequest = _Request
SurgicalIntelligenceReport = _Report
execute_surgical_intelligence = _execute
