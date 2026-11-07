"""P7.6 destination-side intelligence adaptation and retrieval integration.

P7.4 supplies the active portable context prior. P6.3 supplies destination-local
per-memory policies. This adapter combines them at read time and optionally
reorders the candidate indices returned by the existing Engrams.retrieve() API.

It does not write P1-P5, P6.1 events, P6.3 policy rows, or P7.4 activation state.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any, Mapping, Sequence


class RetrievalIntegrationError(ValueError):
    """Invalid adapter configuration or retrieval input."""


@dataclass(frozen=True)
class EffectiveMultiplier:
    target_ref: str
    destination_context_key: str
    source_context_key: str
    multiplier: float
    source: str
    prior_multiplier: float
    prior_strength: float
    local_multiplier: float
    local_weight: float
    local_policy_version: int | None
    explanation: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AdaptedRanking:
    """Both proposed and actually returned order are retained for audit."""
    original_indices: tuple[int, ...]
    proposed_indices: tuple[int, ...]
    indices: tuple[int, ...]
    mode: str
    applied: bool
    trace: tuple[dict, ...]

    def to_dict(self):
        return {
            "original_indices": list(self.original_indices),
            "proposed_indices": list(self.proposed_indices),
            "indices": list(self.indices),
            "mode": self.mode,
            "applied": self.applied,
            "trace": [dict(x) for x in self.trace],
        }


class DestinationIntelligenceAdapter:
    """Combines a restored context prior with destination-local P6.3 policies.

    Parameters
    ----------
    prior_provider:
        P7.4 IntelligenceRestorer instance (or compatible provider) exposing
        get_active_prior(context_key). Only active priors are consumed.
    adaptive_scorer:
        Destination-local P6.3 AdaptiveScorer instance bound to the same
        destination SQLite database.
    context_map:
        Optional explicit mapping: destination context key -> source context
        key. Without a mapping, exact context-key equality is required.
    mode:
        "shadow" (default) computes a proposed ranking but returns original
        order; "apply" returns the adapted order.
    """

    MODES = {"shadow", "apply"}

    def __init__(
        self,
        prior_provider,
        adaptive_scorer,
        *,
        context_map: Mapping[str, str] | None = None,
        mode: str = "shadow",
        min_multiplier: float | None = None,
        max_multiplier: float | None = None,
        max_local_weight: float = 32.0,
    ):
        if not callable(getattr(prior_provider, "get_active_prior", None)):
            raise RetrievalIntegrationError("prior_provider must expose get_active_prior(context_key)")
        if not callable(getattr(adaptive_scorer, "get_policy", None)):
            raise RetrievalIntegrationError("adaptive_scorer must expose get_policy(target_ref, context_key)")
        if mode not in self.MODES:
            raise RetrievalIntegrationError("mode must be 'shadow' or 'apply'")
        if context_map is None:
            context_map = {}
        if not isinstance(context_map, Mapping):
            raise RetrievalIntegrationError("context_map must be a mapping")
        clean_map = {}
        for destination_key, source_key in context_map.items():
            if not isinstance(destination_key, str) or not destination_key.strip():
                raise RetrievalIntegrationError("destination context mapping keys must be non-empty strings")
            if not isinstance(source_key, str) or not source_key.strip():
                raise RetrievalIntegrationError("source context mapping values must be non-empty strings")
            clean_map[destination_key] = source_key
        if not math.isfinite(max_local_weight) or max_local_weight <= 0:
            raise RetrievalIntegrationError("max_local_weight must be finite and positive")

        scorer_min = float(getattr(adaptive_scorer, "min_multiplier", 0.80))
        scorer_max = float(getattr(adaptive_scorer, "max_multiplier", 1.20))
        self.min_multiplier = scorer_min if min_multiplier is None else float(min_multiplier)
        self.max_multiplier = scorer_max if max_multiplier is None else float(max_multiplier)
        if not (0 < self.min_multiplier <= self.max_multiplier):
            raise RetrievalIntegrationError("invalid multiplier bounds")
        self.prior_provider = prior_provider
        self.adaptive_scorer = adaptive_scorer
        self.context_map = clean_map
        self.mode = mode
        self.max_local_weight = float(max_local_weight)

    def _source_context(self, destination_context_key: str) -> str:
        if not isinstance(destination_context_key, str) or not destination_context_key.strip():
            raise RetrievalIntegrationError("destination_context_key is required")
        return self.context_map.get(destination_context_key, destination_context_key)

    @staticmethod
    def _finite(value, field: str, *, minimum: float | None = None) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RetrievalIntegrationError(f"{field} must be numeric")
        result = float(value)
        if not math.isfinite(result) or (minimum is not None and result < minimum):
            raise RetrievalIntegrationError(f"{field} is outside its valid range")
        return result

    def effective_multiplier(
        self, target_ref: str, destination_context_key: str
    ) -> EffectiveMultiplier:
        if not isinstance(target_ref, str) or not target_ref.strip():
            raise RetrievalIntegrationError("target_ref must be a non-empty stable memory reference")
        source_key = self._source_context(destination_context_key)
        prior = self.prior_provider.get_active_prior(source_key)

        prior_multiplier = 1.0
        prior_strength = 0.0
        if prior is not None:
            prior_multiplier = self._finite(
                prior.get("prior_multiplier"), "prior_multiplier", minimum=0.000001
            )
            prior_strength = self._finite(
                prior.get("prior_strength"), "prior_strength", minimum=0.0
            )
            if prior_multiplier < self.min_multiplier - 1e-9 or prior_multiplier > self.max_multiplier + 1e-9:
                raise RetrievalIntegrationError("active prior multiplier falls outside destination bounds")
            if prior_strength > 4.0 + 1e-9:
                raise RetrievalIntegrationError("active prior strength exceeds supported P7.2 maximum")

        local = self.adaptive_scorer.get_policy(target_ref, destination_context_key)
        local_multiplier = 1.0
        local_weight = 0.0
        local_version = None
        if local is not None:
            local_multiplier = self._finite(
                local.get("multiplier"), "local multiplier", minimum=0.000001
            )
            confidence = self._finite(local.get("confidence", 0.0), "local confidence", minimum=0.0)
            evidence = self._finite(local.get("evidence_count", 0), "local evidence_count", minimum=0.0)
            if confidence > 1.0:
                raise RetrievalIntegrationError("local policy confidence must be in [0,1]")
            if local_multiplier < self.min_multiplier - 1e-9 or local_multiplier > self.max_multiplier + 1e-9:
                raise RetrievalIntegrationError("local policy multiplier falls outside destination bounds")
            # Effective evidence weight grows sublinearly and is capped. A large
            # local history can progressively outweigh the imported prior.
            local_weight = min(self.max_local_weight, confidence * math.sqrt(evidence))
            local_version = local.get("version")

        # Log-space pooling preserves multiplicative semantics and bounds.
        # The imported prior initializes context behaviour; local evidence
        # increasingly controls a memory-specific multiplier as it accumulates.
        total_weight = prior_strength + local_weight
        if total_weight <= 0:
            multiplier = 1.0
            source = "neutral"
            explanation = "No supported active prior or local policy; neutral multiplier."
        elif prior_strength <= 0:
            multiplier = local_multiplier
            source = "destination_local"
            explanation = "Destination-local P6.3 policy only."
        elif local_weight <= 0:
            multiplier = prior_multiplier
            source = "inherited_context_prior"
            explanation = "Active P7.4 context prior; no local evidence for this memory."
        else:
            multiplier = math.exp(
                (prior_strength * math.log(prior_multiplier)
                 + local_weight * math.log(local_multiplier)) / total_weight
            )
            source = "prior_plus_local"
            explanation = "Log-space blend; destination-local evidence progressively outweighs the inherited prior."

        multiplier = min(self.max_multiplier, max(self.min_multiplier, multiplier))
        return EffectiveMultiplier(
            target_ref=target_ref,
            destination_context_key=destination_context_key,
            source_context_key=source_key,
            multiplier=round(multiplier, 8),
            source=source,
            prior_multiplier=round(prior_multiplier, 8),
            prior_strength=round(prior_strength, 8),
            local_multiplier=round(local_multiplier, 8),
            local_weight=round(local_weight, 8),
            local_policy_version=local_version,
            explanation=explanation,
        )

    @staticmethod
    def _memory_ref(memory: Any) -> str | None:
        if isinstance(memory, Mapping):
            value = memory.get("id")
        else:
            value = getattr(memory, "id", None)
        return value if isinstance(value, str) and value.strip() else None

    def rank(
        self,
        candidate_indices: Sequence[int],
        memories: Sequence[Any],
        destination_context_key: str,
        *,
        mode: str | None = None,
    ) -> AdaptedRanking:
        """Rerank only the supplied candidate indices; candidate recall is unchanged."""
        selected_mode = self.mode if mode is None else mode
        if selected_mode not in self.MODES:
            raise RetrievalIntegrationError("mode must be 'shadow' or 'apply'")
        indices = tuple(candidate_indices)
        if any(isinstance(i, bool) or not isinstance(i, int) for i in indices):
            raise RetrievalIntegrationError("candidate indices must be integers")
        if len(set(indices)) != len(indices):
            raise RetrievalIntegrationError("candidate indices must be unique")
        if any(i < 0 or i >= len(memories) for i in indices):
            raise RetrievalIntegrationError("candidate index is outside memories sequence")

        rows = []
        for rank_position, index in enumerate(indices):
            ref = self._memory_ref(memories[index])
            if ref is None:
                # Fail closed: missing stable IDs receive neutral adjustment.
                effective = EffectiveMultiplier(
                    target_ref=f"unidentified-index-{index}",
                    destination_context_key=destination_context_key,
                    source_context_key=self._source_context(destination_context_key),
                    multiplier=1.0, source="neutral_missing_reference",
                    prior_multiplier=1.0, prior_strength=0.0,
                    local_multiplier=1.0, local_weight=0.0,
                    local_policy_version=None,
                    explanation="No stable memory id; adaptation skipped.",
                )
            else:
                effective = self.effective_multiplier(ref, destination_context_key)
            base_score = 1.0 / (rank_position + 1)
            adjusted_score = base_score * effective.multiplier
            rows.append({
                "index": index,
                "target_ref": ref,
                "original_rank": rank_position + 1,
                "base_score": round(base_score, 8),
                "effective_multiplier": effective.multiplier,
                "adjusted_score": round(adjusted_score, 8),
                "source": effective.source,
                "prior_strength": effective.prior_strength,
                "local_weight": effective.local_weight,
                "local_policy_version": effective.local_policy_version,
                "explanation": effective.explanation,
            })

        # Stable tie-break: preserve original retrieval order.
        rows.sort(key=lambda item: (-item["adjusted_score"], item["original_rank"]))
        proposed = tuple(item["index"] for item in rows)
        applied = selected_mode == "apply"
        returned = proposed if applied else indices
        return AdaptedRanking(
            original_indices=indices,
            proposed_indices=proposed,
            indices=returned,
            mode=selected_mode,
            applied=applied,
            trace=tuple(rows),
        )

    def retrieve_with_trace(
        self, retriever, memories: Sequence[Any], query: str,
        destination_context_key: str, *, mode: str | None = None, **retrieve_kwargs
    ) -> AdaptedRanking:
        """Call the existing retrieve API, then adapt its returned candidate order."""
        if not callable(getattr(retriever, "retrieve", None)):
            raise RetrievalIntegrationError("retriever must expose retrieve(query, ...)")
        candidate_indices = retriever.retrieve(query, **retrieve_kwargs)
        return self.rank(
            candidate_indices, memories, destination_context_key, mode=mode
        )

    def retrieve(
        self, retriever, memories: Sequence[Any], query: str,
        destination_context_key: str, *, mode: str | None = None, **retrieve_kwargs
    ) -> list[int]:
        """Convenience wrapper returning the same list[int] shape as Engrams.retrieve()."""
        return list(self.retrieve_with_trace(
            retriever, memories, query, destination_context_key,
            mode=mode, **retrieve_kwargs
        ).indices)
