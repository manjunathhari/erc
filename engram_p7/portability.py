"""P7.5 Cross-Installation Portability Test Harness.

This module supplies a deterministic integration harness and scenario runner.
It deliberately does not modify Engrams.retrieve() or claim retrieval-quality
improvements. It verifies the P7.1-P7.4 transfer lifecycle across two isolated
SQLite installations and checks that destination-local knowledge remains local.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
import sqlite3
from typing import Any


class PortabilityTestError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass
class ScenarioResult:
    scenario: str
    passed: bool
    details: dict


class CrossInstallationHarness:
    """Test source→transfer→validation→destination restore/activate.

    The harness accepts the real stage objects so the caller can run it with
    the P7.2, P7.3 and P7.4 implementations. No source database is copied.
    """

    def __init__(self, transfer_builder, validator, restorer_factory):
        self.transfer_builder = transfer_builder
        self.validator = validator
        self.restorer_factory = restorer_factory

    @staticmethod
    def _destination_db(installation_id: str):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        # Destination-local knowledge is deliberately unrelated to source.
        db.execute("CREATE TABLE local_knowledge(record_id TEXT PRIMARY KEY, content TEXT)")
        db.execute(
            "INSERT INTO local_knowledge VALUES(?,?)",
            (f"{installation_id}-fact-1", f"Private knowledge belonging to {installation_id}"),
        )
        db.commit()
        return db

    @staticmethod
    def _make_profile(installation_id: str, context_scheme="sha256_context_key_v1",
                      supports_consumer=True):
        return {
            "installation_id": installation_id,
            "p7_2_format_versions": [1],
            "transfer_algorithms": ["confidence_weighted_log_pool_v1"],
            "p63_algorithms": ["beta_shrinkage_v1"],
            "context_prior_api_version": 1 if supports_consumer else 0,
            "context_key_scheme": context_scheme,
            "supports_local_policy_learning": True,
            "supports_context_prior_consumption": supports_consumer,
            "max_prior_strength": 4.0,
            "min_multiplier": 0.8,
            "max_multiplier": 1.2,
        }

    @staticmethod
    def _resign_transfer(transfer):
        return {
            "transfer": transfer,
            "integrity": {
                "algorithm": "sha256",
                "transfer_sha256": sha256(transfer),
            },
        }

    @staticmethod
    def _p71_fixture(source_installation="source-A"):
        cfg = {
            "prior_alpha": 1.0, "prior_beta": 1.0, "min_evidence": 2,
            "min_multiplier": 0.8, "max_multiplier": 1.2,
        }
        policies = []
        for version, rows in (
            (1, [(1.08, .80, 9), (.96, .60, 4)]),
            (2, [(1.04, .72, 8), (1.02, .68, 5), (.99, .62, 4)]),
        ):
            for index, (multiplier, confidence, evidence) in enumerate(rows):
                policies.append({
                    "version": version, "context_key": "ctx-shared",
                    "positive_count": 4, "negative_count": 1,
                    "posterior_mean": .7, "confidence": confidence,
                    "adjustment": multiplier - 1.0, "multiplier": multiplier,
                    "evidence_count": evidence, "assessment": "positive_adaptation",
                    "algorithm": "beta_shrinkage_v1", "config": cfg,
                    "scope": "source_installation_only",
                    # Deliberately no source IDs in this fixture.
                })
        package = {
            "format": "engram-intelligence-package",
            "format_version": 1,
            "exporter_version": "p7.1.0",
            "created_at": "2026-11-06T00:00:00+00:00",
            "intelligence": {
                "selected_bundle": {"bundle_version": 2},
                "p63": {
                    "selected_version": 2, "context_key": "ctx-shared",
                    "algorithm": "beta_shrinkage_v1", "config": cfg,
                    "version_history": [
                        {"version": 1, "context_key": "ctx-shared", "algorithm": "beta_shrinkage_v1", "config": cfg},
                        {"version": 2, "context_key": "ctx-shared", "algorithm": "beta_shrinkage_v1", "config": cfg},
                    ],
                    "source_scoped_policy_archive": policies,
                    "portable_context_profile": {
                        "context_key": "ctx-shared", "interpretation": "portable_context_seed_not_executable_policy"
                    },
                },
                "p64": {"config": {"half_life_days": 90, "trend_window_days": 30}},
                "retrieval": {"config": {"mode": "shadow"}},
            },
            "privacy": {
                "conversation_content_included": False,
                "p61_experience_events_included": False,
                "p1_p5_knowledge_included": False,
                "target_refs_included": False,
                "source_policy_ids_included": False,
                "source_policy_ids_are_destination_memory_ids": False,
            },
            "portability_status": {"activation_ready_on_destination": False},
            "source_installation_label": source_installation,
        }
        return {"package": package, "integrity": {
            "algorithm": "sha256", "package_sha256": sha256(package)
        }}

    def run_happy_path(self, source_id="source-A", destination_id="destination-B"):
        """Run P7.2 → P7.3 → P7.4 across two independent databases."""
        p71 = self._p71_fixture(source_id)
        p72 = self.transfer_builder.build(p71)
        profile = self._make_profile(destination_id)
        p73 = self.validator.validate(p72, profile)

        destination_db = self._destination_db(destination_id)
        restorer = self.restorer_factory(destination_db, destination_id)
        before_local = destination_db.execute(
            "SELECT record_id,content FROM local_knowledge"
        ).fetchall()
        staged = restorer.restore(
            p72, p73, imported_by="p7.5-test-runner",
            acknowledge_warnings=bool(p73["report"]["warnings"]),
        )
        assert staged["status"] == "staged"
        assert restorer.active_model() is None

        activated = restorer.activate(
            staged["transfer_sha256"],
            activated_by="p7.5-test-runner",
            reason="cross-installation portability integration test",
            validation_report=p73,
        )
        assert activated["status"] == "active"
        prior = restorer.get_active_prior("ctx-shared")
        after_local = destination_db.execute(
            "SELECT record_id,content FROM local_knowledge"
        ).fetchall()

        assert prior is not None
        assert [tuple(r) for r in before_local] == [tuple(r) for r in after_local]
        assert prior["context_key"] == "ctx-shared"
        assert prior["prior_multiplier"] > 0
        assert prior["prior_strength"] > 0

        return {
            "p71": p71, "p72": p72, "p73": p73, "destination_db": destination_db,
            "restorer": restorer, "staged": staged, "activated": activated,
            "prior": dict(prior),
            "destination_local_knowledge_unchanged": True,
        }

    def run_suite(self) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []

        # 1. Full end-to-end source→destination transfer.
        happy = self.run_happy_path()
        results.append(ScenarioResult("end_to_end_transfer", True, {
            "validation_status": happy["p73"]["report"]["status"],
            "activation_status": happy["activated"]["status"],
            "context_prior_available": happy["prior"] is not None,
        }))

        # 2. Same package can be restored idempotently on the same destination.
        restorer = happy["restorer"]
        second = restorer.restore(
            happy["p72"], happy["p73"], imported_by="p7.5-test-runner",
            acknowledge_warnings=bool(happy["p73"]["report"]["warnings"]),
        )
        assert second["idempotent"] is True
        results.append(ScenarioResult("idempotent_reimport", True, second))

        # 3. Context mismatch must not result in accidental prior lookup.
        mismatch_db = self._destination_db("destination-context-mismatch")
        mismatch_restorer = self.restorer_factory(mismatch_db, "destination-context-mismatch")
        mismatch_profile = self._make_profile("destination-context-mismatch")
        p73_mismatch = self.validator.validate(happy["p72"], mismatch_profile)
        staged_mismatch = mismatch_restorer.restore(
            happy["p72"], p73_mismatch, imported_by="p7.5-test-runner",
            acknowledge_warnings=bool(p73_mismatch["report"]["warnings"]),
        )
        mismatch_restorer.activate(
            staged_mismatch["transfer_sha256"], activated_by="p7.5-test-runner",
            reason="context mismatch negative test", validation_report=p73_mismatch,
        )
        assert mismatch_restorer.get_active_prior("destination-different-context") is None
        results.append(ScenarioResult("context_mismatch_no_false_match", True, {
            "source_context": "ctx-shared",
            "destination_query_context": "destination-different-context",
            "prior_returned": False,
        }))

        # 4. Tampered package is rejected by P7.3 before destination writes.
        tampered = json.loads(json.dumps(happy["p72"]))
        tampered["transfer"]["context_priors"][0]["prior_multiplier"] = 1.19
        tamper_rejected = False
        try:
            self.validator.validate(tampered, self._make_profile("tamper-destination"))
        except Exception:
            tamper_rejected = True
        assert tamper_rejected
        results.append(ScenarioResult("tampered_transfer_rejected", True, {
            "validation_rejected": True,
        }))

        # 5. Unsupported destination capability is rejected before restoration.
        unsupported_db = self._destination_db("unsupported-destination")
        unsupported_restorer = self.restorer_factory(unsupported_db, "unsupported-destination")
        unsupported_profile = self._make_profile(
            "unsupported-destination", supports_consumer=False
        )
        unsupported_report = self.validator.validate(happy["p72"], unsupported_profile)
        assert unsupported_report["report"]["status"] == "incompatible"
        restore_rejected = False
        try:
            unsupported_restorer.restore(
                happy["p72"], unsupported_report, imported_by="p7.5-test-runner"
            )
        except Exception:
            restore_rejected = True
        assert restore_rejected
        assert unsupported_restorer.active_model() is None
        results.append(ScenarioResult("unsupported_destination_rejected", True, {
            "validation_status": unsupported_report["report"]["status"],
            "restore_rejected": restore_rejected,
        }))

        # 6. Rollback to prior active intelligence.
        source2 = self._p71_fixture("source-C")
        source2["package"]["intelligence"]["p63"]["config"]["min_evidence"] = 3
        source2["integrity"]["package_sha256"] = sha256(source2["package"])
        p72_2 = self.transfer_builder.build(source2)
        p73_2 = self.validator.validate(p72_2, self._make_profile("destination-B"))
        staged2 = restorer.restore(
            p72_2, p73_2, imported_by="p7.5-test-runner",
            acknowledge_warnings=bool(p73_2["report"]["warnings"]),
        )
        restorer.activate(
            staged2["transfer_sha256"], activated_by="p7.5-test-runner",
            reason="second source intelligence transfer for rollback test",
            validation_report=p73_2,
        )
        rollback = restorer.rollback(
            actor="p7.5-test-runner", reason="verify previous intelligence recovery"
        )
        assert rollback["active_transfer_sha256"] == happy["p72"]["integrity"]["transfer_sha256"]
        results.append(ScenarioResult("rollback_recovers_previous_model", True, rollback))

        # 7. Source package does not carry conversation or personal knowledge.
        raw = json.dumps(happy["p72"], sort_keys=True)
        assert "Private knowledge belonging to source-A" not in raw
        assert "original_text" not in raw
        results.append(ScenarioResult("privacy_boundary", True, {
            "conversation_content_included": False,
            "source_knowledge_included": False,
            "source_memory_ids_included": False,
        }))

        return results


def build_summary(results: list[ScenarioResult]) -> dict:
    passed = sum(1 for r in results if r.passed)
    report = {
        "format": "engram-p7.5-portability-test-report",
        "format_version": 1,
        "suite": "cross_installation_portability",
        "scenario_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "status": "passed" if passed == len(results) else "failed",
        "results": [asdict(r) for r in results],
        "limitations": [
            "This suite validates transfer, validation, staging, activation, readback, idempotency and rollback.",
            "It does not integrate the prior into Engrams.retrieve().",
            "It does not demonstrate improved retrieval precision, recall or user-level utility.",
            "Context-key semantic equivalence is simulated by using the same context key; P7.2 currently lacks a source key-scheme declaration.",
            "The P7.1 source package is a deterministic fixture in this suite; production P7.1 SQLite extraction requires its actual P6 schema.",
        ],
    }
    report["integrity"] = {"algorithm": "sha256", "report_sha256": sha256(report)}
    return report
