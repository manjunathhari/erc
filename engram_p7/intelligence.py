"""P7.1 Intelligence Extraction and Packaging.

Extracts the learned P6 adaptive state pinned by a P6.6 bundle into a
checksummed, conversation-free portability artifact.

Important boundary:
P6.3 policies are currently keyed by target_ref (individual memory identity).
P7.1 therefore preserves policy values as source-installation-scoped records
(without exporting target_ref) and derives portable context-level summaries.
Those summaries are seed information, not executable destination policies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from ._rows import NamedRows
import hashlib
import json
import sqlite3
from typing import Any


class IntelligenceExportError(ValueError):
    """Raised when source intelligence is incomplete or inconsistent."""


class IntelligenceExporter:
    FORMAT = "engram-intelligence-package"
    FORMAT_VERSION = 1
    EXPORTER_VERSION = "p7.1.0"

    POLICY_COLUMNS = (
        "policy_id", "version", "context_key", "positive_count",
        "negative_count", "posterior_mean", "confidence", "adjustment",
        "multiplier", "evidence_count", "source_event_count", "assessment",
        "created_at", "algorithm", "config_json",
    )
    VERSION_COLUMNS = (
        "version", "context_key", "created_at", "algorithm", "config_json",
        "source_max_event_id", "policy_count", "note",
    )

    def __init__(self, db: sqlite3.Connection):
        self.db = NamedRows(db)  # never changes the shared connection's row_factory
        self._require_schema()

    def _tables(self) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

    def _columns(self, table: str) -> set[str]:
        return {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}

    def _require_schema(self) -> None:
        required = {"p6_policy_versions", "p6_scoring_policies", "p6_model_bundles"}
        missing = required - self._tables()
        if missing:
            raise IntelligenceExportError(
                "required P6 tables are missing: " + ", ".join(sorted(missing))
            )
        for table, columns in (
            ("p6_policy_versions", set(self.VERSION_COLUMNS)),
            ("p6_scoring_policies", set(self.POLICY_COLUMNS) | {"target_ref"}),
            ("p6_model_bundles", {
                "bundle_id", "bundle_version", "created_at", "p63_policy_version",
                "p63_context_key", "p63_algorithm", "p63_config_json",
                "p64_config_json", "retrieval_config_json", "bundle_sha256", "note",
            }),
        ):
            missing_cols = columns - self._columns(table)
            if missing_cols:
                raise IntelligenceExportError(
                    f"{table} schema is incomplete: {', '.join(sorted(missing_cols))}"
                )

    @staticmethod
    def _canonical(value: Any) -> bytes:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise IntelligenceExportError(f"package contains non-JSON data: {exc}") from None

    @classmethod
    def _sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

    @staticmethod
    def _json_object(raw: str, label: str) -> dict:
        try:
            value = json.loads(raw)
        except Exception:
            raise IntelligenceExportError(f"{label} is invalid JSON") from None
        if not isinstance(value, dict):
            raise IntelligenceExportError(f"{label} must be a JSON object")
        return value

    def _bundle_row(self, bundle_id: str | None):
        if bundle_id is None:
            if "p6_model_bundle_active" not in self._tables():
                raise IntelligenceExportError(
                    "no active bundle table; provide bundle_id explicitly"
                )
            active = self.db.execute(
                "SELECT bundle_id FROM p6_model_bundle_active WHERE singleton=1"
            ).fetchone()
            if not active:
                raise IntelligenceExportError("there is no active P6.6 model bundle")
            bundle_id = active["bundle_id"]
        row = self.db.execute(
            """SELECT bundle_id,bundle_version,created_at,p63_policy_version,
                      p63_context_key,p63_algorithm,p63_config_json,p64_config_json,
                      retrieval_config_json,bundle_sha256,note
               FROM p6_model_bundles WHERE bundle_id=?""",
            (bundle_id,),
        ).fetchone()
        if not row:
            raise IntelligenceExportError(f"P6.6 bundle not found: {bundle_id}")
        return row

    def _verify_p66_bundle(self, row) -> dict:
        payload = {
            "format_version": 1,
            "bundle_id": row["bundle_id"],
            "bundle_version": row["bundle_version"],
            "created_at": row["created_at"],
            "p63_policy_version": row["p63_policy_version"],
            "p63_context_key": row["p63_context_key"],
            "p63_algorithm": row["p63_algorithm"],
            "p63_config": self._json_object(row["p63_config_json"], "P6.6 P6.3 config"),
            "p64_config": self._json_object(row["p64_config_json"], "P6.6 P6.4 config"),
            "retrieval_config": self._json_object(
                row["retrieval_config_json"], "P6.6 retrieval config"
            ),
            "note": row["note"],
        }
        digest = self._sha256(payload)
        if digest != row["bundle_sha256"]:
            raise IntelligenceExportError("P6.6 bundle checksum mismatch")
        return payload

    def extract(self, bundle_id: str | None = None, *, include_version_history: bool = True) -> dict:
        """Return a conversation-free, checksummed intelligence package.

        No source rows are changed. No P6.1 events, target refs, user facts,
        original sentences, or knowledge records are exported.
        """
        bundle_row = self._bundle_row(bundle_id)
        bundle = self._verify_p66_bundle(bundle_row)

        version = bundle["p63_policy_version"]
        context = bundle["p63_context_key"]
        manifest = self.db.execute(
            """SELECT version,context_key,created_at,algorithm,config_json,
                      source_max_event_id,policy_count,note
               FROM p6_policy_versions WHERE version=?""",
            (version,),
        ).fetchone()
        if not manifest:
            raise IntelligenceExportError("referenced P6.3 policy version is missing")
        if manifest["context_key"] != context:
            raise IntelligenceExportError("P6.3 context does not match P6.6 bundle")
        if manifest["algorithm"] != bundle["p63_algorithm"]:
            raise IntelligenceExportError("P6.3 algorithm does not match P6.6 bundle")
        manifest_config = self._json_object(manifest["config_json"], "P6.3 manifest config")
        if manifest_config != bundle["p63_config"]:
            raise IntelligenceExportError("P6.3 config does not match P6.6 bundle")

        versions = []
        if include_version_history:
            version_rows = self.db.execute(
                """SELECT version,context_key,created_at,algorithm,config_json,
                          source_max_event_id,policy_count,note
                   FROM p6_policy_versions
                   WHERE context_key=? AND version<=? ORDER BY version""",
                (context, version),
            ).fetchall()
        else:
            version_rows = [manifest]

        source_scoped_records = []
        for vrow in version_rows:
            v = dict(vrow)
            v["config"] = self._json_object(v.pop("config_json"), "P6.3 version config")
            # Event IDs and policy IDs are installation-local linkage identifiers,
            # not transferable intelligence; retain version metadata without them.
            v.pop("source_max_event_id", None)
            actual = self.db.execute(
                """SELECT COUNT(*) FROM p6_scoring_policies
                   WHERE version=? AND context_key=?""",
                (v["version"], context),
            ).fetchone()[0]
            if actual != v["policy_count"]:
                raise IntelligenceExportError(
                    f"P6.3 version {v['version']} policy count does not match its manifest"
                )
            versions.append(v)
            rows = self.db.execute(
                """SELECT policy_id,version,context_key,positive_count,negative_count,
                          posterior_mean,confidence,adjustment,multiplier,evidence_count,
                          source_event_count,assessment,created_at,algorithm,config_json
                   FROM p6_scoring_policies
                   WHERE version=? AND context_key=? ORDER BY policy_id""",
                (v["version"], context),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item.pop("policy_id", None)
                item["config"] = self._json_object(item.pop("config_json"), "policy config")
                item["source_policy_ordinal"] = len(source_scoped_records) + 1
                item["scope"] = "source_installation_only"
                item["destination_mapping_required"] = True
                source_scoped_records.append(item)

        selected_records = [
            p for p in source_scoped_records if p["version"] == version
        ]
        if len(selected_records) != manifest["policy_count"]:
            raise IntelligenceExportError("selected P6.3 policy rows are incomplete")

        # Context-level aggregate is the only target-independent learning signal
        # available in the current P6.3 representation.
        multipliers = [p["multiplier"] for p in selected_records]
        posteriors = [p["posterior_mean"] for p in selected_records]
        confidences = [p["confidence"] for p in selected_records]
        assessments: dict[str, int] = {}
        for p in selected_records:
            assessments[p["assessment"]] = assessments.get(p["assessment"], 0) + 1

        context_profile = {
            "context_key": context,
            "source_policy_count": len(selected_records),
            "mean_multiplier": round(sum(multipliers) / len(multipliers), 6) if multipliers else None,
            "median_multiplier": self._median(multipliers),
            "mean_posterior": round(sum(posteriors) / len(posteriors), 6) if posteriors else None,
            "mean_confidence": round(sum(confidences) / len(confidences), 6) if confidences else None,
            "assessment_counts": dict(sorted(assessments.items())),
            "interpretation": "portable_context_seed_not_executable_policy",
        }

        package_payload = {
            "format": self.FORMAT,
            "format_version": self.FORMAT_VERSION,
            "exporter_version": self.EXPORTER_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "intelligence": {
                "selected_bundle": bundle,
                "p63": {
                    "algorithm": bundle["p63_algorithm"],
                    "selected_version": version,
                    "context_key": context,
                    "config": bundle["p63_config"],
                    "version_history": versions,
                    "source_scoped_policy_archive": source_scoped_records,
                    "portable_context_profile": context_profile,
                },
                "p64": {
                    "config": bundle["p64_config"],
                    "transfer_status": "configuration_only",
                },
                "retrieval": {
                    "config": bundle["retrieval_config"],
                    "transfer_status": "configuration_only",
                },
            },
            "privacy": {
                "conversation_content_included": False,
                "p61_experience_events_included": False,
                "p1_p5_knowledge_included": False,
                "target_refs_included": False,
                "source_policy_ids_included": False,
                "source_policy_ids_are_destination_memory_ids": False,
            },
            "portability_status": {
                "package_integrity": "checksummed",
                "configuration_transfer": "portable",
                "per_memory_policy_transfer": "source_scoped_requires_mapping",
                "context_profile": "portable_seed_only",
                "activation_ready_on_destination": False,
                "reason": (
                    "Current P6.3 policies are keyed by source target_ref. "
                    "P7.1 does not invent destination memory mappings or treat "
                    "aggregate context statistics as executable policies."
                ),
            },
        }
        digest = self._sha256(package_payload)
        return {
            "package": package_payload,
            "integrity": {
                "algorithm": "sha256",
                "package_sha256": digest,
                "canonicalization": "UTF-8 JSON, sorted keys, compact separators",
            },
        }

    @staticmethod
    def _median(values: list[float]):
        if not values:
            return None
        ordered = sorted(values)
        n = len(ordered)
        mid = n // 2
        value = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        return round(value, 6)

    @classmethod
    def verify_package(cls, document: dict) -> bool:
        if not isinstance(document, dict) or set(document) != {"package", "integrity"}:
            raise IntelligenceExportError("invalid P7.1 package envelope")
        integrity = document["integrity"]
        if integrity.get("algorithm") != "sha256":
            raise IntelligenceExportError("unsupported integrity algorithm")
        digest = cls._sha256(document["package"])
        if digest != integrity.get("package_sha256"):
            raise IntelligenceExportError("P7.1 package checksum mismatch")
        package = document["package"]
        if package.get("format") != cls.FORMAT:
            raise IntelligenceExportError("unrecognised P7.1 package format")
        if package.get("format_version") != cls.FORMAT_VERSION:
            raise IntelligenceExportError("unsupported P7.1 package version")
        return True

    @classmethod
    def write_json(cls, document: dict, path: str) -> str:
        cls.verify_package(document)
        with open(path, "wb") as f:
            f.write(cls._canonical(document))
        return path
