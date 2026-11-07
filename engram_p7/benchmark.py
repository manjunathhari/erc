"""P7.7 Cross-Installation Retrieval Benchmark and Intelligence Effectiveness.

Evaluates three frozen retrieval conditions against independent query-level
relevance judgments. It never creates judgments or trains a model.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
import random
from typing import Any, Iterable


class BenchmarkError(ValueError):
    pass


CONDITIONS = ("baseline", "inherited", "inherited_local")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise BenchmarkError(f"{name} must be finite")
    return value


def _unique_refs(values, name):
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise BenchmarkError(f"{name} must be an array of non-empty memory references")
    if len(set(values)) != len(values):
        raise BenchmarkError(f"{name} contains duplicate memory references")
    return set(values)


@dataclass(frozen=True)
class QueryJudgment:
    query_id: str
    context_key: str
    query_time: str
    relevant_refs: tuple[str, ...]
    rare_important_refs: tuple[str, ...] = ()
    correction_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    query_id: str
    condition: str
    metrics: dict[str, float]


class RetrievalBenchmark:
    """Evaluate precomputed ranked lists with independent relevance labels.

    Dataset format:
      {
        "format": "engram-p7.7-benchmark-dataset",
        "format_version": 1,
        "judgment_source": "human_adjudicated_holdout",
        "queries": [{
          "query_id": "...", "context_key": "...", "query_time": ISO-8601,
          "relevant_refs": [...],
          "rare_important_refs": [...], "correction_refs": [...],
          "rankings": {
             "baseline": [...], "inherited": [...], "inherited_local": [...]
          },
          "provenance": {
             "baseline_cutoff": ISO-8601,
             "inherited_cutoff": ISO-8601,
             "inherited_local_cutoff": ISO-8601
          }
        }]
      }

    The benchmark expects the same candidate universe for all three conditions
    within a query. It verifies no duplicate refs and no policy/evidence cutoff
    later than query_time. The caller is responsible for creating frozen
    rankings without using held-out relevance labels.
    """

    FORMAT = "engram-p7.7-benchmark-dataset"
    VERSION = 1

    def __init__(self, *, k_values=(1, 3, 5, 10), bootstrap_samples=2000,
                 permutation_samples=5000, seed=77):
        if not k_values or any(isinstance(k, bool) or not isinstance(k, int) or k < 1 for k in k_values):
            raise BenchmarkError("k_values must contain positive integers")
        if len(set(k_values)) != len(k_values):
            raise BenchmarkError("k_values must be unique")
        if bootstrap_samples < 100 or permutation_samples < 100:
            raise BenchmarkError("resampling counts must be at least 100")
        self.k_values = tuple(sorted(k_values))
        self.bootstrap_samples = int(bootstrap_samples)
        self.permutation_samples = int(permutation_samples)
        self.seed = int(seed)

    @staticmethod
    def _parse_time(value, field):
        if not isinstance(value, str) or not value.strip():
            raise BenchmarkError(f"{field} must be an ISO-8601 timestamp")
        from datetime import datetime
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise BenchmarkError(f"{field} is not a valid ISO-8601 timestamp") from None
        if parsed.tzinfo is None:
            raise BenchmarkError(f"{field} must include timezone")
        return parsed

    def validate_dataset(self, dataset):
        if not isinstance(dataset, dict) or dataset.get("format") != self.FORMAT:
            raise BenchmarkError("unrecognised benchmark dataset format")
        if dataset.get("format_version") != self.VERSION:
            raise BenchmarkError("unsupported benchmark dataset version")
        if dataset.get("judgment_source") != "human_adjudicated_holdout":
            raise BenchmarkError("judgment_source must declare independent human-adjudicated holdout labels")
        queries = dataset.get("queries")
        if not isinstance(queries, list) or not queries:
            raise BenchmarkError("dataset must contain at least one query")
        seen = set()
        validated = []
        for row in queries:
            qid = row.get("query_id")
            if not isinstance(qid, str) or not qid.strip() or qid in seen:
                raise BenchmarkError("query_id must be unique and non-empty")
            seen.add(qid)
            context = row.get("context_key")
            if not isinstance(context, str) or not context.strip():
                raise BenchmarkError(f"{qid}: context_key is required")
            query_time = self._parse_time(row.get("query_time"), f"{qid}.query_time")
            relevant = _unique_refs(row.get("relevant_refs"), f"{qid}.relevant_refs")
            rare = _unique_refs(row.get("rare_important_refs", []), f"{qid}.rare_important_refs")
            correction = _unique_refs(row.get("correction_refs", []), f"{qid}.correction_refs")
            if not rare.issubset(relevant):
                raise BenchmarkError(f"{qid}: rare_important_refs must be a subset of relevant_refs")
            if not correction.issubset(relevant):
                raise BenchmarkError(f"{qid}: correction_refs must be a subset of relevant_refs")
            rankings = row.get("rankings")
            if not isinstance(rankings, dict) or set(rankings) != set(CONDITIONS):
                raise BenchmarkError(f"{qid}: rankings must contain exactly {CONDITIONS}")
            parsed_rankings = {}
            candidate_sets = []
            for condition in CONDITIONS:
                ranking = rankings[condition]
                if not isinstance(ranking, list) or any(not isinstance(x, str) or not x.strip() for x in ranking):
                    raise BenchmarkError(f"{qid}.{condition} ranking must be an array of refs")
                if len(set(ranking)) != len(ranking):
                    raise BenchmarkError(f"{qid}.{condition} ranking contains duplicates")
                parsed_rankings[condition] = ranking
                candidate_sets.append(set(ranking))
            if not all(s == candidate_sets[0] for s in candidate_sets[1:]):
                raise BenchmarkError(f"{qid}: conditions must rank the same candidate set")
            provenance = row.get("provenance")
            if not isinstance(provenance, dict):
                raise BenchmarkError(f"{qid}: provenance cutoffs are required")
            for condition in CONDITIONS:
                cutoff = self._parse_time(
                    provenance.get(f"{condition}_cutoff"),
                    f"{qid}.provenance.{condition}_cutoff",
                )
                if cutoff > query_time:
                    raise BenchmarkError(
                        f"{qid}: {condition} policy/evidence cutoff occurs after query_time (leakage)"
                    )
            validated.append({
                "query_id": qid, "context_key": context, "query_time": query_time,
                "relevant": relevant, "rare": rare, "correction": correction,
                "rankings": parsed_rankings,
            })
        return validated

    @staticmethod
    def _dcg(ranking, relevant, k):
        total = 0.0
        for rank, ref in enumerate(ranking[:k], start=1):
            if ref in relevant:
                total += 1.0 / math.log2(rank + 1)
        return total

    @classmethod
    def _ndcg(cls, ranking, relevant, k):
        if not relevant:
            return 0.0
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
        return cls._dcg(ranking, relevant, k) / ideal if ideal else 0.0

    def _query_metrics(self, ranking, relevant, rare, correction):
        result = {}
        for k in self.k_values:
            top = ranking[:k]
            hits = [ref for ref in top if ref in relevant]
            result[f"precision@{k}"] = len(hits) / k
            result[f"recall@{k}"] = len(hits) / len(relevant) if relevant else 0.0
            result[f"ndcg@{k}"] = self._ndcg(ranking, relevant, k)
            result[f"rare_important_recall@{k}"] = (
                len(set(top) & rare) / len(rare) if rare else 0.0
            )
            result[f"correction_rate@{k}"] = (
                len(set(top) & correction) / len(top) if top else 0.0
            )
        first = next((i + 1 for i, ref in enumerate(ranking) if ref in relevant), None)
        result["mrr"] = 1.0 / first if first else 0.0
        return result

    @staticmethod
    def _mean(values):
        return sum(values) / len(values) if values else 0.0

    def _bootstrap_ci(self, values, rng):
        n = len(values)
        samples = []
        for _ in range(self.bootstrap_samples):
            draw = [values[rng.randrange(n)] for _ in range(n)]
            samples.append(self._mean(draw))
        samples.sort()
        lo = samples[int(0.025 * (len(samples) - 1))]
        hi = samples[int(0.975 * (len(samples) - 1))]
        return [lo, hi]

    def _permutation_p(self, differences, rng):
        observed = abs(self._mean(differences))
        extreme = 0
        n = len(differences)
        for _ in range(self.permutation_samples):
            permuted = [d if rng.getrandbits(1) else -d for d in differences]
            if abs(self._mean(permuted)) >= observed - 1e-15:
                extreme += 1
        return (extreme + 1) / (self.permutation_samples + 1)

    def run(self, dataset):
        queries = self.validate_dataset(dataset)
        per_query = {condition: [] for condition in CONDITIONS}
        for query in queries:
            for condition in CONDITIONS:
                metrics = self._query_metrics(
                    query["rankings"][condition], query["relevant"],
                    query["rare"], query["correction"],
                )
                per_query[condition].append(QueryResult(
                    query["query_id"], condition, metrics
                ))

        metric_names = sorted(per_query["baseline"][0].metrics)
        aggregate = {
            condition: {
                metric: round(self._mean([r.metrics[metric] for r in per_query[condition]]), 8)
                for metric in metric_names
            }
            for condition in CONDITIONS
        }

        rng = random.Random(self.seed)
        comparisons = {}
        for candidate in ("inherited", "inherited_local"):
            comparisons[candidate + "_vs_baseline"] = {}
            for metric in metric_names:
                diffs = [
                    per_query[candidate][i].metrics[metric]
                    - per_query["baseline"][i].metrics[metric]
                    for i in range(len(queries))
                ]
                comparisons[candidate + "_vs_baseline"][metric] = {
                    "mean_delta": round(self._mean(diffs), 8),
                    "paired_bootstrap_95_ci": [
                        round(x, 8) for x in self._bootstrap_ci(diffs, rng)
                    ],
                    "sign_flip_permutation_p": round(self._permutation_p(diffs, rng), 8),
                    "queries": len(diffs),
                }

        report = {
            "format": "engram-p7.7-retrieval-benchmark-report",
            "format_version": 1,
            "status": "completed",
            "dataset_sha256": _sha256(dataset),
            "query_count": len(queries),
            "conditions": list(CONDITIONS),
            "k_values": list(self.k_values),
            "aggregate_metrics": aggregate,
            "paired_comparisons": comparisons,
            "query_results": {
                condition: [asdict(r) for r in rows]
                for condition, rows in per_query.items()
            },
            "method": {
                "unit_of_analysis": "query",
                "bootstrap": "paired query-level percentile bootstrap",
                "permutation": "paired sign-flip permutation test",
                "bootstrap_samples": self.bootstrap_samples,
                "permutation_samples": self.permutation_samples,
                "seed": self.seed,
                "judgments": "independent human-adjudicated holdout",
            },
            "limitations": [
                "Metrics describe only the supplied held-out queries and relevance judgments.",
                "The evaluator does not create rankings, train policies, or generate relevance labels.",
                "Statistical significance does not establish clinical or user-level utility.",
                "Correction rate is the proportion of top-k results explicitly labeled correction-relevant; it is not a generic error rate.",
                "Queries with no rare-important or correction labels receive zero for that metric and should be interpreted with label coverage.",
                "The caller must ensure all three conditions use identical candidate sets and no held-out labels enter adaptation.",
            ],
        }
        report["integrity"] = {
            "algorithm": "sha256",
            "report_sha256": _sha256(report),
        }
        return report

    @staticmethod
    def write_report(report, path):
        payload = dict(report)
        integrity = payload.pop("integrity", None)
        if not isinstance(integrity, dict) or _sha256(payload) != integrity.get("report_sha256"):
            raise BenchmarkError("report integrity verification failed")
        with open(path, "wb") as f:
            f.write(_canonical(report))
        return path


def make_dataset_row(query_id, context_key, query_time, relevant, rare, correction,
                     baseline, inherited, inherited_local, cutoff):
    """Small helper for building a row after rankings and labels are frozen."""
    return {
        "query_id": query_id,
        "context_key": context_key,
        "query_time": query_time,
        "relevant_refs": list(relevant),
        "rare_important_refs": list(rare),
        "correction_refs": list(correction),
        "rankings": {
            "baseline": list(baseline),
            "inherited": list(inherited),
            "inherited_local": list(inherited_local),
        },
        "provenance": {
            "baseline_cutoff": cutoff,
            "inherited_cutoff": cutoff,
            "inherited_local_cutoff": cutoff,
        },
    }
