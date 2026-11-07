"""P7.2 Policy and Context Transfer.

Transforms P7.1 source-installation policy records into portable context priors.
It never maps source policies to destination memories and never mutates P1-P6.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class ContextTransferError(ValueError):
    """Invalid, incomplete, or incompatible P7.1 intelligence package."""


class ContextPolicyTransfer:
    FORMAT = "engram-context-intelligence-transfer"
    FORMAT_VERSION = 1
    ALGORITHM = "confidence_weighted_log_pool_v1"

    def __init__(
        self,
        *,
        max_prior_strength: float = 4.0,
        min_policy_count: int = 2,
        min_confidence: float = 0.05,
        default_min_multiplier: float = 0.80,
        default_max_multiplier: float = 1.20,
    ):
        if max_prior_strength <= 0:
            raise ValueError("max_prior_strength must be positive")
        if min_policy_count < 1:
            raise ValueError("min_policy_count must be at least 1")
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0 < default_min_multiplier <= default_max_multiplier:
            raise ValueError("invalid multiplier bounds")
        self.max_prior_strength = float(max_prior_strength)
        self.min_policy_count = int(min_policy_count)
        self.min_confidence = float(min_confidence)
        self.default_min_multiplier = float(default_min_multiplier)
        self.default_max_multiplier = float(default_max_multiplier)

    @staticmethod
    def _canonical(value: Any) -> bytes:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ContextTransferError(f"non-JSON transfer data: {exc}") from None

    @classmethod
    def _sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

    @classmethod
    def verify_p71(cls, document: dict) -> None:
        if not isinstance(document, dict) or set(document) != {"package", "integrity"}:
            raise ContextTransferError("invalid P7.1 package envelope")
        package = document["package"]
        integrity = document["integrity"]
        if integrity.get("algorithm") != "sha256":
            raise ContextTransferError("unsupported P7.1 integrity algorithm")
        if cls._sha256(package) != integrity.get("package_sha256"):
            raise ContextTransferError("P7.1 checksum mismatch")
        if package.get("format") != "engram-intelligence-package":
            raise ContextTransferError("input is not an Engram P7.1 package")
        if package.get("format_version") != 1:
            raise ContextTransferError("unsupported P7.1 package version")
        privacy = package.get("privacy", {})
        if privacy.get("conversation_content_included") is not False:
            raise ContextTransferError("P7.1 privacy declaration is missing or unsafe")
        if privacy.get("p61_experience_events_included") is not False:
            raise ContextTransferError("P7.1 must not include raw P6.1 experience events")
        if privacy.get("p1_p5_knowledge_included") is not False:
            raise ContextTransferError("P7.1 must not include P1-P5 knowledge")

    @staticmethod
    def _weighted_geometric_mean(values: list[float], weights: list[float]) -> float:
        total = sum(weights)
        if total <= 0:
            return 1.0
        return math.exp(sum(w * math.log(v) for v, w in zip(values, weights)) / total)

    @staticmethod
    def _weighted_variance_log(values: list[float], weights: list[float], mean: float) -> float:
        total = sum(weights)
        if total <= 0:
            return 0.0
        mu = math.log(mean)
        return sum(w * (math.log(v) - mu) ** 2 for v, w in zip(values, weights)) / total

    @staticmethod
    def _effective_count(weights: list[float]) -> float:
        total = sum(weights)
        squares = sum(w * w for w in weights)
        return (total * total / squares) if squares else 0.0

    @staticmethod
    def _validate_policy(policy: dict) -> None:
        required = {
            "version", "context_key", "positive_count", "negative_count",
            "posterior_mean", "confidence", "adjustment", "multiplier",
            "evidence_count", "assessment", "algorithm", "config",
        }
        missing = required - set(policy)
        if missing:
            raise ContextTransferError(
                "P7.1 policy record missing fields: " + ", ".join(sorted(missing))
            )
        numeric_fields = (
            "positive_count", "negative_count", "posterior_mean", "confidence",
            "adjustment", "multiplier", "evidence_count",
        )
        for field in numeric_fields:
            value = policy[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContextTransferError(f"policy {field} must be numeric")
            if not math.isfinite(float(value)):
                raise ContextTransferError(f"policy {field} must be finite")
        if policy["confidence"] < 0 or policy["confidence"] > 1:
            raise ContextTransferError("policy confidence must be in [0,1]")
        if policy["multiplier"] <= 0:
            raise ContextTransferError("policy multiplier must be positive")
        if policy["evidence_count"] < 0:
            raise ContextTransferError("policy evidence_count cannot be negative")
        if not isinstance(policy["config"], dict):
            raise ContextTransferError("policy config must be an object")

    def _bounds(self, p63_config: dict) -> tuple[float, float]:
        lo = float(p63_config.get("min_multiplier", self.default_min_multiplier))
        hi = float(p63_config.get("max_multiplier", self.default_max_multiplier))
        if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= hi):
            raise ContextTransferError("invalid multiplier bounds in P6.3 config")
        return lo, hi

    def build(self, p71_document: dict) -> dict:
        """Build a self-contained destination-oriented context transfer artifact."""
        self.verify_p71(p71_document)
        package = p71_document["package"]
        intelligence = package.get("intelligence", {})
        p63 = intelligence.get("p63", {})
        p64 = intelligence.get("p64", {})
        retrieval = intelligence.get("retrieval", {})
        bundle = intelligence.get("selected_bundle", {})

        selected_version = p63.get("selected_version")
        context_key = p63.get("context_key")
        algorithm = p63.get("algorithm")
        p63_config = p63.get("config")
        if not isinstance(selected_version, int) or not context_key or not algorithm:
            raise ContextTransferError("P7.1 selected P6.3 model metadata is incomplete")
        if not isinstance(p63_config, dict):
            raise ContextTransferError("P7.1 P6.3 config is missing")
        if not isinstance(p64.get("config"), dict):
            raise ContextTransferError("P7.1 P6.4 config is missing")
        if not isinstance(retrieval.get("config"), dict):
            raise ContextTransferError("P7.1 retrieval config is missing")

        policies = p63.get("source_scoped_policy_archive")
        if not isinstance(policies, list):
            raise ContextTransferError("P7.1 source policy archive is missing")

        # Only the selected immutable version contributes to the current prior.
        # Earlier versions are lineage, not additional independent observations.
        selected = []
        for policy in policies:
            if not isinstance(policy, dict):
                raise ContextTransferError("policy archive contains a non-object")
            self._validate_policy(policy)
            if policy["context_key"] != context_key:
                raise ContextTransferError("policy context does not match selected context")
            if policy["algorithm"] != algorithm:
                raise ContextTransferError("policy algorithm does not match selected algorithm")
            if policy["version"] == selected_version:
                selected.append(policy)

        if not selected:
            raise ContextTransferError("no policy rows exist for the selected P6.3 version")

        lo, hi = self._bounds(p63_config)
        values = []
        weights = []
        confidence_values = []
        for policy in selected:
            multiplier = float(policy["multiplier"])
            if multiplier < lo - 1e-9 or multiplier > hi + 1e-9:
                raise ContextTransferError("policy multiplier falls outside P6.3 bounds")
            confidence = float(policy["confidence"])
            evidence = float(policy["evidence_count"])
            # Confidence controls influence; sqrt(evidence) prevents a single
            # high-exposure policy from dominating linearly.
            weight = confidence * math.sqrt(evidence)
            values.append(multiplier)
            weights.append(weight)
            confidence_values.append(confidence)

        total_weight = sum(weights)
        effective_count = self._effective_count(weights)
        weighted_confidence = (
            sum(w * c for w, c in zip(weights, confidence_values)) / total_weight
            if total_weight else 0.0
        )
        pooled = self._weighted_geometric_mean(values, weights)
        pooled = min(hi, max(lo, pooled))
        variance = self._weighted_variance_log(values, weights, pooled)
        dispersion = math.sqrt(max(0.0, variance))

        enough_support = (
            len(selected) >= self.min_policy_count
            and weighted_confidence >= self.min_confidence
            and total_weight > 0
        )
        prior_strength = (
            min(self.max_prior_strength, effective_count * weighted_confidence)
            if enough_support else 0.0
        )
        if not enough_support:
            # Neutral prior is safer than transferring weak or single-policy
            # evidence as a confident context behaviour.
            pooled = 1.0
            dispersion = 0.0

        prior = {
            "context_key": context_key,
            "source_policy_version": selected_version,
            "source_algorithm": algorithm,
            "prior_multiplier": round(pooled, 8),
            "prior_strength": round(prior_strength, 8),
            "confidence": round(weighted_confidence if enough_support else 0.0, 8),
            "log_multiplier_dispersion": round(dispersion, 8),
            "source_policy_count": len(selected),
            "effective_policy_count": round(effective_count, 8),
            "support_status": "supported" if enough_support else "insufficient_support",
            "semantics": "context_prior_for_destination_local_learning",
        }

        p71_digest = p71_document["integrity"]["package_sha256"]
        transfer_payload = {
            "format": self.FORMAT,
            "format_version": self.FORMAT_VERSION,
            "transfer_algorithm": self.ALGORITHM,
            "source": {
                "p71_package_sha256": p71_digest,
                "p6_3_version": selected_version,
                "p6_3_algorithm": algorithm,
                "p6_6_bundle_version": bundle.get("bundle_version"),
            },
            "context_priors": [prior],
            "model_configuration": {
                "p63": {
                    "algorithm": algorithm,
                    "config": p63_config,
                },
                "p64": {
                    "config": p64["config"],
                    "status": "configuration_transferred",
                },
                "retrieval": {
                    "config": retrieval["config"],
                    "status": "configuration_transferred_not_applied",
                },
            },
            "destination_contract": {
                "source_memory_ids_required": False,
                "source_conversations_required": False,
                "source_experience_events_required": False,
                "source_per_memory_policies_are_executable": False,
                "context_prior_is_initialization_not_destination_fact": True,
                "destination_feedback_must_update_local_policy": True,
                "destination_knowledge_is_not_modified": True,
            },
            "privacy": {
                "conversation_content_included": False,
                "p61_experience_events_included": False,
                "p1_p5_knowledge_included": False,
                "source_memory_identifiers_included": False,
                "source_per_memory_policy_rows_included": False,
            },
        }
        return {
            "transfer": transfer_payload,
            "integrity": {
                "algorithm": "sha256",
                "transfer_sha256": self._sha256(transfer_payload),
                "canonicalization": "UTF-8 JSON, sorted keys, compact separators",
            },
        }

    @classmethod
    def verify_transfer(cls, document: dict) -> bool:
        if not isinstance(document, dict) or set(document) != {"transfer", "integrity"}:
            raise ContextTransferError("invalid P7.2 transfer envelope")
        integrity = document["integrity"]
        if integrity.get("algorithm") != "sha256":
            raise ContextTransferError("unsupported P7.2 integrity algorithm")
        digest = cls._sha256(document["transfer"])
        if digest != integrity.get("transfer_sha256"):
            raise ContextTransferError("P7.2 transfer checksum mismatch")
        transfer = document["transfer"]
        if transfer.get("format") != cls.FORMAT:
            raise ContextTransferError("unrecognised P7.2 transfer format")
        if transfer.get("format_version") != cls.FORMAT_VERSION:
            raise ContextTransferError("unsupported P7.2 transfer version")
        return True

    @classmethod
    def write_json(cls, document: dict, path: str) -> str:
        cls.verify_transfer(document)
        with open(path, "wb") as f:
            f.write(cls._canonical(document))
        return path
