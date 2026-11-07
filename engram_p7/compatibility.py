"""P7.3 Model Compatibility and Integrity Validation.

Validates a P7.2 context-intelligence transfer against an explicit destination
capability profile. Validation is read-only and never activates or imports a model.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
from typing import Any


class CompatibilityValidationError(ValueError):
    """Malformed transfer or invalid destination capability declaration."""


@dataclass(frozen=True)
class DestinationProfile:
    """Capabilities declared by the destination Engram installation.

    The profile must describe implemented capabilities, not planned features.
    """
    installation_id: str
    p7_2_format_versions: tuple[int, ...] = (1,)
    transfer_algorithms: tuple[str, ...] = ("confidence_weighted_log_pool_v1",)
    p63_algorithms: tuple[str, ...] = ("beta_shrinkage_v1",)
    context_prior_api_version: int = 0
    context_key_scheme: str = "unknown"
    p64_supported_config_keys: tuple[str, ...] = (
        "half_life_days", "prior_alpha", "prior_beta", "confidence_scale",
        "max_adjustment", "min_multiplier", "max_multiplier",
        "min_weighted_evidence", "trend_window_days", "trend_threshold",
    )
    p63_supported_config_keys: tuple[str, ...] = (
        "prior_alpha", "prior_beta", "confidence_scale", "max_adjustment",
        "min_multiplier", "max_multiplier", "min_evidence",
    )
    supports_local_policy_learning: bool = False
    supports_context_prior_consumption: bool = False
    max_prior_strength: float = 4.0
    min_multiplier: float = 0.80
    max_multiplier: float = 1.20

    def __post_init__(self):
        if not self.installation_id.strip():
            raise ValueError("installation_id must be non-empty")
        if self.context_prior_api_version < 0:
            raise ValueError("context_prior_api_version cannot be negative")
        if not math.isfinite(self.max_prior_strength) or self.max_prior_strength <= 0:
            raise ValueError("max_prior_strength must be finite and positive")
        if not (0 < self.min_multiplier <= self.max_multiplier):
            raise ValueError("invalid destination multiplier bounds")


class ModelCompatibilityValidator:
    TRANSFER_FORMAT = "engram-context-intelligence-transfer"
    TRANSFER_ALGORITHM = "confidence_weighted_log_pool_v1"
    REPORT_FORMAT = "engram-p7.3-validation-report"
    REPORT_VERSION = 1

    @staticmethod
    def _canonical(value: Any) -> bytes:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CompatibilityValidationError(f"non-JSON data: {exc}") from None

    @classmethod
    def _sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

    @classmethod
    def _verify_transfer_envelope(cls, document: dict) -> dict:
        if not isinstance(document, dict) or set(document) != {"transfer", "integrity"}:
            raise CompatibilityValidationError("invalid P7.2 transfer envelope")
        transfer = document["transfer"]
        integrity = document["integrity"]
        if not isinstance(transfer, dict) or not isinstance(integrity, dict):
            raise CompatibilityValidationError("P7.2 envelope members must be objects")
        if integrity.get("algorithm") != "sha256":
            raise CompatibilityValidationError("unsupported P7.2 integrity algorithm")
        if cls._sha256(transfer) != integrity.get("transfer_sha256"):
            raise CompatibilityValidationError("P7.2 transfer checksum mismatch")
        if transfer.get("format") != cls.TRANSFER_FORMAT:
            raise CompatibilityValidationError("unrecognised P7.2 transfer format")
        if transfer.get("format_version") != 1:
            raise CompatibilityValidationError("unsupported P7.2 transfer format version")
        if transfer.get("transfer_algorithm") != cls.TRANSFER_ALGORITHM:
            raise CompatibilityValidationError("unrecognised P7.2 transfer algorithm")
        return transfer

    @staticmethod
    def _issue(code: str, message: str, severity: str) -> dict:
        return {"code": code, "message": message, "severity": severity}

    @staticmethod
    def _is_finite_number(value) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )

    def validate(
        self,
        transfer_document: dict,
        destination: DestinationProfile | dict,
    ) -> dict:
        """Return a deterministic compatibility report; no writes or activation."""
        if isinstance(destination, dict):
            try:
                destination = DestinationProfile(**{
                    **destination,
                    **{
                        k: tuple(v) for k, v in destination.items()
                        if isinstance(v, list)
                    },
                })
            except Exception as exc:
                raise CompatibilityValidationError(
                    f"invalid destination profile: {exc}"
                ) from None
        if not isinstance(destination, DestinationProfile):
            raise CompatibilityValidationError("destination must be a DestinationProfile or dict")

        transfer = self._verify_transfer_envelope(transfer_document)
        blockers: list[dict] = []
        warnings: list[dict] = []
        checks: dict[str, str] = {}

        def block(code, message):
            blockers.append(self._issue(code, message, "blocker"))

        def warn(code, message):
            warnings.append(self._issue(code, message, "warning"))

        checks["package_integrity"] = "passed"
        checks["transfer_format"] = "passed"

        if transfer["format_version"] not in destination.p7_2_format_versions:
            block("UNSUPPORTED_TRANSFER_FORMAT",
                  "Destination does not support this P7.2 package format version.")
        if transfer["transfer_algorithm"] not in destination.transfer_algorithms:
            block("UNSUPPORTED_TRANSFER_ALGORITHM",
                  "Destination does not support the P7.2 context aggregation algorithm.")

        context_priors = transfer.get("context_priors")
        if not isinstance(context_priors, list) or not context_priors:
            block("MISSING_CONTEXT_PRIORS", "Transfer contains no context priors.")
            context_priors = []
        else:
            checks["context_prior_structure"] = "passed"

        p63 = transfer.get("model_configuration", {}).get("p63", {})
        p64 = transfer.get("model_configuration", {}).get("p64", {})
        retrieval = transfer.get("model_configuration", {}).get("retrieval", {})
        if not isinstance(p63, dict) or not isinstance(p63.get("config"), dict):
            block("MISSING_P63_CONFIG", "P6.3 algorithm/configuration is missing.")
            p63 = {}
        if not isinstance(p64, dict) or not isinstance(p64.get("config"), dict):
            block("MISSING_P64_CONFIG", "P6.4 temporal configuration is missing.")
            p64 = {}
        if not isinstance(retrieval, dict) or not isinstance(retrieval.get("config"), dict):
            block("MISSING_RETRIEVAL_CONFIG", "Retrieval configuration is missing.")
            retrieval = {}

        p63_algorithm = p63.get("algorithm")
        if p63_algorithm not in destination.p63_algorithms:
            block("UNSUPPORTED_P63_ALGORITHM",
                  f"Destination does not support P6.3 algorithm: {p63_algorithm!r}.")
        else:
            checks["p63_algorithm"] = "passed"

        p63_config = p63.get("config", {})
        unknown_p63 = sorted(set(p63_config) - set(destination.p63_supported_config_keys))
        if unknown_p63:
            block("UNSUPPORTED_P63_CONFIG_KEYS",
                  "Destination does not declare support for P6.3 config keys: "
                  + ", ".join(unknown_p63))
        else:
            checks["p63_config"] = "passed"

        p64_config = p64.get("config", {})
        unknown_p64 = sorted(set(p64_config) - set(destination.p64_supported_config_keys))
        if unknown_p64:
            warn("UNRECOGNISED_P64_CONFIG_KEYS",
                 "P6.4 configuration keys are not declared by destination: "
                 + ", ".join(unknown_p64)
                 + ". They must not be applied until explicitly supported.")

        retrieval_config = retrieval.get("config", {})
        if retrieval_config:
            warn("RETRIEVAL_CONFIG_NOT_APPLIED",
                 "Retrieval configuration is carried as metadata only; P7.3 does not change retrieval behaviour.")

        if not destination.supports_context_prior_consumption:
            block("NO_CONTEXT_PRIOR_CONSUMER",
                  "Destination has no implemented P6 context-prior consumer.")
        elif destination.context_prior_api_version < 1:
            block("CONTEXT_PRIOR_API_MISSING",
                  "Destination context-prior API version is below the required version 1.")
        else:
            checks["context_prior_api"] = "passed"

        if not destination.supports_local_policy_learning:
            warn("NO_LOCAL_POLICY_LEARNING",
                 "Destination cannot yet refine the imported prior through local P6.3 learning.")

        # P7.2 currently does not declare a context-key derivation scheme.
        # Do not assume matching hashes imply equivalent semantics.
        if destination.context_key_scheme in ("", "unknown", None):
            warn("CONTEXT_KEY_SCHEME_UNDECLARED",
                 "Destination context-key derivation scheme is unknown; context matching cannot be verified.")
        else:
            warn("CONTEXT_KEY_SCHEME_UNVERIFIED",
                 "P7.2 does not declare its source context-key scheme; compare source and destination schemes before activation.")

        for index, prior in enumerate(context_priors):
            if not isinstance(prior, dict):
                block("INVALID_CONTEXT_PRIOR", f"Context prior {index} is not an object.")
                continue
            required = (
                "context_key", "source_policy_version", "source_algorithm",
                "prior_multiplier", "prior_strength", "confidence",
                "log_multiplier_dispersion", "source_policy_count",
                "effective_policy_count", "support_status", "semantics",
            )
            missing = [k for k in required if k not in prior]
            if missing:
                block("INCOMPLETE_CONTEXT_PRIOR",
                      f"Context prior {index} is missing: {', '.join(missing)}.")
                continue
            if not isinstance(prior["context_key"], str) or not prior["context_key"]:
                block("INVALID_CONTEXT_KEY", f"Context prior {index} has an invalid context key.")
            if prior["source_algorithm"] != p63_algorithm:
                block("CONTEXT_ALGORITHM_MISMATCH",
                      f"Context prior {index} algorithm differs from model configuration.")
            for field in (
                "prior_multiplier", "prior_strength", "confidence",
                "log_multiplier_dispersion", "source_policy_count",
                "effective_policy_count",
            ):
                if not self._is_finite_number(prior[field]):
                    block("NONFINITE_PRIOR_VALUE",
                          f"Context prior {index} field {field} is not a finite number.")
            if any(not self._is_finite_number(prior[f]) for f in (
                "prior_multiplier", "prior_strength", "confidence",
                "log_multiplier_dispersion", "source_policy_count",
                "effective_policy_count",
            )):
                continue
            if prior["prior_multiplier"] < destination.min_multiplier or prior["prior_multiplier"] > destination.max_multiplier:
                block("PRIOR_MULTIPLIER_OUT_OF_BOUNDS",
                      f"Context prior {index} multiplier is outside destination bounds.")
            if prior["prior_strength"] < 0 or prior["prior_strength"] > destination.max_prior_strength:
                block("PRIOR_STRENGTH_OUT_OF_BOUNDS",
                      f"Context prior {index} strength is outside destination bounds.")
            if not 0 <= prior["confidence"] <= 1:
                block("PRIOR_CONFIDENCE_OUT_OF_BOUNDS",
                      f"Context prior {index} confidence is outside [0,1].")
            if prior["log_multiplier_dispersion"] < 0:
                block("NEGATIVE_PRIOR_DISPERSION",
                      f"Context prior {index} dispersion cannot be negative.")
            if prior["source_policy_count"] < 0 or prior["effective_policy_count"] < 0:
                block("NEGATIVE_POLICY_COUNT",
                      f"Context prior {index} policy counts cannot be negative.")
            if prior["support_status"] not in ("supported", "insufficient_support"):
                block("UNKNOWN_SUPPORT_STATUS",
                      f"Context prior {index} has an unknown support status.")
            if prior["support_status"] == "insufficient_support":
                if prior["prior_multiplier"] != 1.0 or prior["prior_strength"] != 0:
                    block("UNSAFE_INSUFFICIENT_PRIOR",
                          f"Context prior {index} claims insufficient support but is not neutral.")
            if prior["semantics"] != "context_prior_for_destination_local_learning":
                block("UNKNOWN_PRIOR_SEMANTICS",
                      f"Context prior {index} has unsupported semantics.")

        contract = transfer.get("destination_contract", {})
        required_contract = {
            "source_memory_ids_required": False,
            "source_conversations_required": False,
            "source_experience_events_required": False,
            "source_per_memory_policies_are_executable": False,
            "context_prior_is_initialization_not_destination_fact": True,
            "destination_feedback_must_update_local_policy": True,
            "destination_knowledge_is_not_modified": True,
        }
        if not isinstance(contract, dict):
            block("MISSING_DESTINATION_CONTRACT", "Destination contract is missing.")
        else:
            for key, expected in required_contract.items():
                if contract.get(key) is not expected:
                    block("UNSAFE_DESTINATION_CONTRACT",
                          f"Destination contract field {key} must be {expected!r}.")

        privacy = transfer.get("privacy", {})
        privacy_expected = {
            "conversation_content_included": False,
            "p61_experience_events_included": False,
            "p1_p5_knowledge_included": False,
            "source_memory_identifiers_included": False,
            "source_per_memory_policy_rows_included": False,
        }
        if not isinstance(privacy, dict):
            block("MISSING_PRIVACY_DECLARATION", "Privacy declaration is missing.")
        else:
            for key, expected in privacy_expected.items():
                if privacy.get(key) is not expected:
                    block("PRIVACY_DECLARATION_FAILED",
                          f"Privacy declaration {key} must be {expected!r}.")

        source = transfer.get("source", {})
        if not isinstance(source, dict) or not source.get("p71_package_sha256"):
            block("MISSING_SOURCE_LINEAGE", "P7.1 source package lineage is missing.")
        else:
            checks["source_lineage"] = "present"

        if blockers:
            status = "incompatible"
        elif warnings:
            status = "compatible_with_warnings"
        else:
            status = "compatible"

        report_payload = {
            "format": self.REPORT_FORMAT,
            "format_version": self.REPORT_VERSION,
            "destination_installation_id": destination.installation_id,
            "status": status,
            "checks": checks,
            "blockers": blockers,
            "warnings": warnings,
            "activation_authorized": False,
            "validation_only": True,
            "transfer_sha256": transfer_document["integrity"]["transfer_sha256"],
            "destination_profile": asdict(destination),
            "summary": {
                "context_prior_count": len(context_priors),
                "blocker_count": len(blockers),
                "warning_count": len(warnings),
                "compatible_for_restoration": not blockers,
                "ready_for_activation": False,
            },
        }
        return {
            "report": report_payload,
            "integrity": {
                "algorithm": "sha256",
                "report_sha256": self._sha256(report_payload),
                "canonicalization": "UTF-8 JSON, sorted keys, compact separators",
            },
        }

    @classmethod
    def verify_report(cls, document: dict) -> bool:
        if not isinstance(document, dict) or set(document) != {"report", "integrity"}:
            raise CompatibilityValidationError("invalid P7.3 report envelope")
        report = document["report"]
        integrity = document["integrity"]
        if integrity.get("algorithm") != "sha256":
            raise CompatibilityValidationError("unsupported P7.3 report integrity algorithm")
        if cls._sha256(report) != integrity.get("report_sha256"):
            raise CompatibilityValidationError("P7.3 report checksum mismatch")
        if report.get("format") != cls.REPORT_FORMAT:
            raise CompatibilityValidationError("unrecognised P7.3 report format")
        return True

    @classmethod
    def write_json(cls, document: dict, path: str) -> str:
        cls.verify_report(document)
        with open(path, "wb") as f:
            f.write(cls._canonical(document))
        return path
