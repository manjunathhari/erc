"""P7.4 Intelligence Restoration and Activation.

Restores a validated P7.2 context-intelligence transfer into destination-local
P7 tables, stages it, and activates it through an explicit transactional action.

This module does not modify P1-P6, Engrams.retrieve(), Config, or local P6.3
learned policies. It exposes an active-prior read API for a future P6 consumer.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from ._rows import NamedRows
import hashlib
import json
import math
import sqlite3
import uuid
from typing import Any


class RestorationError(ValueError):
    """Invalid transfer, validation report, or restoration state."""


class IntelligenceRestorer:
    SCHEMA_VERSION = 1

    def __init__(self, db: sqlite3.Connection, installation_id: str):
        if not installation_id or not installation_id.strip():
            raise ValueError("installation_id must be non-empty")
        self.db = NamedRows(db)  # never changes the shared connection's row_factory
        self.installation_id = installation_id
        self._create_schema()

    @staticmethod
    def _canonical(value: Any) -> bytes:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RestorationError(f"non-JSON data: {exc}") from None

    @classmethod
    def _sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @contextmanager
    def _transaction(self):
        # Savepoints work both with an idle connection and inside an outer
        # caller-owned transaction, without committing that outer transaction.
        name = "p74_" + uuid.uuid4().hex
        self.db.execute(f"SAVEPOINT {name}")
        try:
            yield
        except Exception:
            self.db.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.db.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            self.db.execute(f"RELEASE SAVEPOINT {name}")

    def _create_schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS p7_restored_models (
            transfer_sha256 TEXT PRIMARY KEY,
            format_version INTEGER NOT NULL,
            transfer_algorithm TEXT NOT NULL,
            source_p71_sha256 TEXT NOT NULL,
            source_p63_version INTEGER NOT NULL,
            source_p63_algorithm TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            imported_by TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('staged','active','retired')),
            warnings_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK(warnings_acknowledged IN (0,1)),
            transfer_json TEXT NOT NULL,
            row_checksum TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS p7_restored_context_priors (
            transfer_sha256 TEXT NOT NULL,
            context_key TEXT NOT NULL,
            source_policy_version INTEGER NOT NULL,
            source_algorithm TEXT NOT NULL,
            prior_multiplier REAL NOT NULL,
            prior_strength REAL NOT NULL,
            confidence REAL NOT NULL,
            log_multiplier_dispersion REAL NOT NULL,
            source_policy_count INTEGER NOT NULL,
            effective_policy_count REAL NOT NULL,
            support_status TEXT NOT NULL,
            semantics TEXT NOT NULL,
            PRIMARY KEY (transfer_sha256, context_key),
            FOREIGN KEY (transfer_sha256)
                REFERENCES p7_restored_models(transfer_sha256)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS p7_active_intelligence (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            transfer_sha256 TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            activated_by TEXT NOT NULL,
            activation_reason TEXT NOT NULL,
            FOREIGN KEY (transfer_sha256)
                REFERENCES p7_restored_models(transfer_sha256)
        );

        CREATE TABLE IF NOT EXISTS p7_activation_history (
            activation_id TEXT PRIMARY KEY,
            transfer_sha256 TEXT,
            previous_transfer_sha256 TEXT,
            action TEXT NOT NULL CHECK(action IN ('activate','rollback','deactivate')),
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            validation_report_sha256 TEXT,
            FOREIGN KEY (transfer_sha256)
                REFERENCES p7_restored_models(transfer_sha256)
        );

        CREATE TABLE IF NOT EXISTS p7_restoration_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        row = self.db.execute(
            "SELECT value FROM p7_restoration_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self.db.execute(
                "INSERT INTO p7_restoration_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )
        elif row["value"] != str(self.SCHEMA_VERSION):
            raise RestorationError(
                f"unsupported P7 restoration schema version: {row['value']}"
            )

    @classmethod
    def _verify_envelope(cls, document: dict, payload_key: str, digest_key: str) -> dict:
        if not isinstance(document, dict) or set(document) != {payload_key, "integrity"}:
            raise RestorationError(f"invalid {payload_key} envelope")
        payload, integrity = document[payload_key], document["integrity"]
        if not isinstance(payload, dict) or not isinstance(integrity, dict):
            raise RestorationError("envelope members must be objects")
        if integrity.get("algorithm") != "sha256":
            raise RestorationError("unsupported integrity algorithm")
        if cls._sha256(payload) != integrity.get(digest_key):
            raise RestorationError(f"{payload_key} checksum mismatch")
        return payload

    def _verify_inputs(self, transfer_document: dict, validation_report: dict,
                       acknowledge_warnings: bool) -> tuple[dict, dict]:
        transfer = self._verify_envelope(
            transfer_document, "transfer", "transfer_sha256"
        )
        report = self._verify_envelope(
            validation_report, "report", "report_sha256"
        )

        if transfer.get("format") != "engram-context-intelligence-transfer":
            raise RestorationError("unrecognised P7.2 transfer format")
        if transfer.get("format_version") != 1:
            raise RestorationError("unsupported P7.2 transfer version")
        if report.get("format") != "engram-p7.3-validation-report":
            raise RestorationError("unrecognised P7.3 validation report")
        if report.get("format_version") != 1:
            raise RestorationError("unsupported P7.3 validation report version")

        transfer_digest = transfer_document["integrity"]["transfer_sha256"]
        if report.get("transfer_sha256") != transfer_digest:
            raise RestorationError("P7.3 report does not validate this exact P7.2 transfer")
        if report.get("destination_installation_id") != self.installation_id:
            raise RestorationError("P7.3 report was generated for a different destination")
        if report.get("status") == "incompatible":
            raise RestorationError("P7.3 marked this destination incompatible")
        if report.get("status") not in ("compatible", "compatible_with_warnings"):
            raise RestorationError("P7.3 report has an unknown validation status")
        if report.get("blockers"):
            raise RestorationError("P7.3 report contains blocking issues")
        if report.get("summary", {}).get("compatible_for_restoration") is not True:
            raise RestorationError("P7.3 report does not approve restoration compatibility")
        if report.get("activation_authorized") is not False:
            raise RestorationError("unexpected P7.3 activation authorization state")

        warnings = report.get("warnings", [])
        if warnings and not acknowledge_warnings:
            raise RestorationError(
                "P7.3 warnings require explicit acknowledgement before restoration"
            )

        profile = report.get("destination_profile", {})
        if profile.get("installation_id") != self.installation_id:
            raise RestorationError("destination profile identity mismatch")
        if profile.get("supports_context_prior_consumption") is not True:
            raise RestorationError("destination has no declared context-prior consumer")
        if profile.get("context_prior_api_version", 0) < 1:
            raise RestorationError("destination context-prior API is unavailable")
        return transfer, report

    @staticmethod
    def _validate_prior(prior: dict):
        required = {
            "context_key", "source_policy_version", "source_algorithm",
            "prior_multiplier", "prior_strength", "confidence",
            "log_multiplier_dispersion", "source_policy_count",
            "effective_policy_count", "support_status", "semantics",
        }
        missing = required - set(prior)
        if missing:
            raise RestorationError(
                "context prior missing fields: " + ", ".join(sorted(missing))
            )
        if not isinstance(prior["context_key"], str) or not prior["context_key"]:
            raise RestorationError("invalid context key")
        for field in (
            "prior_multiplier", "prior_strength", "confidence",
            "log_multiplier_dispersion", "source_policy_count",
            "effective_policy_count",
        ):
            value = prior[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise RestorationError(f"invalid numeric context prior field: {field}")
        if prior["prior_multiplier"] <= 0 or prior["prior_strength"] < 0:
            raise RestorationError("invalid multiplier or prior strength")
        if not 0 <= prior["confidence"] <= 1:
            raise RestorationError("context prior confidence must be in [0,1]")
        if prior["log_multiplier_dispersion"] < 0:
            raise RestorationError("context prior dispersion cannot be negative")
        if prior["support_status"] == "insufficient_support":
            if prior["prior_multiplier"] != 1.0 or prior["prior_strength"] != 0:
                raise RestorationError("insufficient-support prior must be neutral")
        elif prior["support_status"] != "supported":
            raise RestorationError("unknown context prior support status")
        if prior["semantics"] != "context_prior_for_destination_local_learning":
            raise RestorationError("unsupported context prior semantics")

    def restore(
        self,
        transfer_document: dict,
        validation_report: dict,
        *,
        imported_by: str,
        acknowledge_warnings: bool = False,
    ) -> dict:
        """Verify and stage imported intelligence. Does not activate it."""
        if not imported_by or not imported_by.strip():
            raise ValueError("imported_by must be non-empty")
        transfer, report = self._verify_inputs(
            transfer_document, validation_report, acknowledge_warnings
        )
        priors = transfer.get("context_priors")
        if not isinstance(priors, list) or not priors:
            raise RestorationError("transfer has no context priors")
        for prior in priors:
            if not isinstance(prior, dict):
                raise RestorationError("context prior must be an object")
            self._validate_prior(prior)

        transfer_digest = transfer_document["integrity"]["transfer_sha256"]
        source = transfer.get("source", {})
        model_config = transfer.get("model_configuration", {})
        p63 = model_config.get("p63", {})
        if not source.get("p71_package_sha256"):
            raise RestorationError("source P7.1 lineage is missing")
        if not isinstance(p63.get("config"), dict) or not p63.get("algorithm"):
            raise RestorationError("P6.3 model configuration is incomplete")

        transfer_json = self._canonical(transfer).decode("utf-8")
        row_payload = {
            "transfer_sha256": transfer_digest,
            "format_version": transfer["format_version"],
            "transfer_algorithm": transfer["transfer_algorithm"],
            "source_p71_sha256": source["p71_package_sha256"],
            "source_p63_version": source["p6_3_version"],
            "source_p63_algorithm": source["p6_3_algorithm"],
            "transfer_json": transfer_json,
        }
        row_checksum = self._sha256(row_payload)

        with self._transaction():
            existing = self.db.execute(
                "SELECT row_checksum,status,warnings_acknowledged FROM p7_restored_models WHERE transfer_sha256=?",
                (transfer_digest,),
            ).fetchone()
            if existing:
                if existing["row_checksum"] != row_checksum:
                    raise RestorationError("existing restored model has a different checksum")
                count = self.db.execute(
                    "SELECT COUNT(*) FROM p7_restored_context_priors WHERE transfer_sha256=?",
                    (transfer_digest,),
                ).fetchone()[0]
                if count != len(priors):
                    raise RestorationError("existing staged model has incomplete context priors")
                if acknowledge_warnings and not existing["warnings_acknowledged"]:
                    self.db.execute(
                        "UPDATE p7_restored_models SET warnings_acknowledged=1 WHERE transfer_sha256=?",
                        (transfer_digest,),
                    )
                return {
                    "transfer_sha256": transfer_digest,
                    "status": existing["status"],
                    "idempotent": True,
                    "context_prior_count": count,
                    "validation_report_sha256": validation_report["integrity"]["report_sha256"],
                }

            self.db.execute(
                """INSERT INTO p7_restored_models(
                    transfer_sha256,format_version,transfer_algorithm,source_p71_sha256,
                    source_p63_version,source_p63_algorithm,imported_at,imported_by,
                    status,warnings_acknowledged,transfer_json,row_checksum
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    transfer_digest, transfer["format_version"], transfer["transfer_algorithm"],
                    source["p71_package_sha256"], source["p6_3_version"],
                    source["p6_3_algorithm"], self._now(), imported_by, "staged",
                    1 if acknowledge_warnings else 0, transfer_json, row_checksum,
                ),
            )
            for prior in priors:
                self.db.execute(
                    """INSERT INTO p7_restored_context_priors(
                        transfer_sha256,context_key,source_policy_version,source_algorithm,
                        prior_multiplier,prior_strength,confidence,log_multiplier_dispersion,
                        source_policy_count,effective_policy_count,support_status,semantics
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        transfer_digest, prior["context_key"], prior["source_policy_version"],
                        prior["source_algorithm"], prior["prior_multiplier"], prior["prior_strength"],
                        prior["confidence"], prior["log_multiplier_dispersion"],
                        prior["source_policy_count"], prior["effective_policy_count"],
                        prior["support_status"], prior["semantics"],
                    ),
                )

        return {
            "transfer_sha256": transfer_digest,
            "status": "staged",
            "idempotent": False,
            "context_prior_count": len(priors),
            "validation_report_sha256": validation_report["integrity"]["report_sha256"],
        }

    def activate(
        self,
        transfer_sha256: str,
        *,
        activated_by: str,
        reason: str,
        validation_report: dict,
    ) -> dict:
        """Explicitly activate a staged transfer, preserving prior activation for rollback."""
        if not activated_by or not activated_by.strip():
            raise ValueError("activated_by must be non-empty")
        if not reason or not reason.strip():
            raise ValueError("activation reason must be non-empty")
        report = self._verify_envelope(validation_report, "report", "report_sha256")
        if report.get("destination_installation_id") != self.installation_id:
            raise RestorationError("validation report belongs to another destination")
        if report.get("status") == "incompatible" or report.get("blockers"):
            raise RestorationError("cannot activate an incompatible transfer")
        if report.get("summary", {}).get("compatible_for_restoration") is not True:
            raise RestorationError("validation report does not permit restoration")
        if report.get("transfer_sha256") != transfer_sha256:
            raise RestorationError("validation report does not match staged transfer")
        if report.get("warnings") and not report.get("warnings_acknowledged_for_activation", False):
            # Warnings were acknowledged during restore, but P7.3 report remains
            # immutable. Require explicit activation reason to record that decision.
            if len(reason.strip()) < 12:
                raise RestorationError(
                    "when activating a warning-bearing transfer, provide a reason of at least 12 characters"
                )

        with self._transaction():
            model = self.db.execute(
                "SELECT status,row_checksum,transfer_json,warnings_acknowledged FROM p7_restored_models WHERE transfer_sha256=?",
                (transfer_sha256,),
            ).fetchone()
            if not model:
                raise RestorationError("transfer has not been restored to this destination")
            try:
                payload = json.loads(model["transfer_json"])
                row_payload = {
                    "transfer_sha256": transfer_sha256,
                    "format_version": payload["format_version"],
                    "transfer_algorithm": payload["transfer_algorithm"],
                    "source_p71_sha256": payload["source"]["p71_package_sha256"],
                    "source_p63_version": payload["source"]["p6_3_version"],
                    "source_p63_algorithm": payload["source"]["p6_3_algorithm"],
                    "transfer_json": model["transfer_json"],
                }
            except (ValueError, KeyError, TypeError):
                raise RestorationError("staged model integrity check failed") from None
            if self._sha256(row_payload) != model["row_checksum"]:
                raise RestorationError("staged model integrity check failed")
            if report.get("warnings") and not model["warnings_acknowledged"]:
                raise RestorationError("P7.3 warnings were not acknowledged during restoration")
            prior_count = self.db.execute(
                "SELECT COUNT(*) FROM p7_restored_context_priors WHERE transfer_sha256=?",
                (transfer_sha256,),
            ).fetchone()[0]
            if prior_count != len(payload.get("context_priors", [])):
                raise RestorationError("staged context priors are incomplete")

            previous = self.db.execute(
                "SELECT transfer_sha256 FROM p7_active_intelligence WHERE singleton=1"
            ).fetchone()
            previous_digest = previous["transfer_sha256"] if previous else None
            if previous_digest == transfer_sha256:
                return {
                    "transfer_sha256": transfer_sha256,
                    "status": "active",
                    "idempotent": True,
                    "previous_transfer_sha256": previous_digest,
                }

            if previous_digest:
                self.db.execute(
                    "UPDATE p7_restored_models SET status='retired' WHERE transfer_sha256=?",
                    (previous_digest,),
                )
            self.db.execute(
                "UPDATE p7_restored_models SET status='active' WHERE transfer_sha256=?",
                (transfer_sha256,),
            )
            self.db.execute(
                """INSERT INTO p7_active_intelligence(
                    singleton,transfer_sha256,activated_at,activated_by,activation_reason
                ) VALUES(1,?,?,?,?)
                ON CONFLICT(singleton) DO UPDATE SET
                    transfer_sha256=excluded.transfer_sha256,
                    activated_at=excluded.activated_at,
                    activated_by=excluded.activated_by,
                    activation_reason=excluded.activation_reason""",
                (transfer_sha256, self._now(), activated_by, reason),
            )
            self.db.execute(
                """INSERT INTO p7_activation_history(
                    activation_id,transfer_sha256,previous_transfer_sha256,action,
                    occurred_at,actor,reason,validation_report_sha256
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex, transfer_sha256, previous_digest, "activate",
                    self._now(), activated_by, reason,
                    validation_report["integrity"]["report_sha256"],
                ),
            )
        return {
            "transfer_sha256": transfer_sha256,
            "status": "active",
            "idempotent": False,
            "previous_transfer_sha256": previous_digest,
        }

    def rollback(self, *, actor: str, reason: str) -> dict:
        """Restore the immediately previous activation recorded in history."""
        if not actor or not actor.strip() or not reason or not reason.strip():
            raise ValueError("actor and reason are required")
        with self._transaction():
            active = self.db.execute(
                "SELECT transfer_sha256 FROM p7_active_intelligence WHERE singleton=1"
            ).fetchone()
            if not active:
                raise RestorationError("there is no active intelligence to roll back")
            current = active["transfer_sha256"]
            prior_event = self.db.execute(
                """SELECT previous_transfer_sha256 FROM p7_activation_history
                   WHERE action='activate' AND transfer_sha256=?
                   ORDER BY occurred_at DESC, rowid DESC LIMIT 1""",
                (current,),
            ).fetchone()
            previous = prior_event["previous_transfer_sha256"] if prior_event else None
            if not previous:
                raise RestorationError("no previous activation is available for rollback")
            exists = self.db.execute(
                "SELECT 1 FROM p7_restored_models WHERE transfer_sha256=?",
                (previous,),
            ).fetchone()
            if not exists:
                raise RestorationError("previous model is missing; rollback refused")

            self.db.execute(
                "UPDATE p7_restored_models SET status='retired' WHERE transfer_sha256=?",
                (current,),
            )
            self.db.execute(
                "UPDATE p7_restored_models SET status='active' WHERE transfer_sha256=?",
                (previous,),
            )
            self.db.execute(
                """UPDATE p7_active_intelligence SET transfer_sha256=?,
                   activated_at=?,activated_by=?,activation_reason=? WHERE singleton=1""",
                (previous, self._now(), actor, "rollback: " + reason),
            )
            self.db.execute(
                """INSERT INTO p7_activation_history(
                    activation_id,transfer_sha256,previous_transfer_sha256,action,
                    occurred_at,actor,reason,validation_report_sha256
                ) VALUES(?,?,?,?,?,?,?,NULL)""",
                (uuid.uuid4().hex, previous, current, "rollback", self._now(), actor, reason),
            )
        return {"active_transfer_sha256": previous, "rolled_back_from": current}

    def deactivate(self, *, actor: str, reason: str) -> dict:
        """Remove active pointer without deleting staged or historical intelligence."""
        if not actor or not actor.strip() or not reason or not reason.strip():
            raise ValueError("actor and reason are required")
        with self._transaction():
            active = self.db.execute(
                "SELECT transfer_sha256 FROM p7_active_intelligence WHERE singleton=1"
            ).fetchone()
            if not active:
                return {"status": "inactive", "idempotent": True}
            current = active["transfer_sha256"]
            self.db.execute(
                "DELETE FROM p7_active_intelligence WHERE singleton=1"
            )
            self.db.execute(
                "UPDATE p7_restored_models SET status='retired' WHERE transfer_sha256=?",
                (current,),
            )
            self.db.execute(
                """INSERT INTO p7_activation_history(
                    activation_id,transfer_sha256,previous_transfer_sha256,action,
                    occurred_at,actor,reason,validation_report_sha256
                ) VALUES(?,?,?,?,?,?,?,NULL)""",
                (uuid.uuid4().hex, None, current, "deactivate", self._now(), actor, reason),
            )
        return {"status": "inactive", "deactivated_transfer_sha256": current}

    def active_model(self) -> dict | None:
        row = self.db.execute(
            """SELECT m.transfer_sha256,m.format_version,m.transfer_algorithm,
                      m.source_p71_sha256,m.source_p63_version,m.source_p63_algorithm,
                      a.activated_at,a.activated_by,a.activation_reason
               FROM p7_active_intelligence a
               JOIN p7_restored_models m ON m.transfer_sha256=a.transfer_sha256
               WHERE a.singleton=1"""
        ).fetchone()
        return dict(row) if row else None

    def get_active_prior(self, context_key: str) -> dict | None:
        """Read the active context prior; no retrieval integration is performed here."""
        row = self.db.execute(
            """SELECT p.* FROM p7_active_context_priors p
               WHERE p.context_key=?""",
            (context_key,),
        ).fetchone() if "p7_active_context_priors" in self._tables() else None
        if row:
            return dict(row)
        active = self.active_model()
        if not active:
            return None
        row = self.db.execute(
            """SELECT * FROM p7_restored_context_priors
               WHERE transfer_sha256=? AND context_key=?""",
            (active["transfer_sha256"], context_key),
        ).fetchone()
        return dict(row) if row else None

    def _tables(self):
        return {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
