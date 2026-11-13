"""Frozen study analysis: reviewer coverage, paired uncertainty, and error attribution.

No part of this module supplies relevance labels. Missing or unadjudicated
judgments prevent analysis. The unit of resampling is a query, never a pair.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from savoroute.data.catalog import load_catalog
from savoroute.evaluation.annotations import (
    finalize_relevance_workbook,
    split_reviewer_sheets,
)
from savoroute.evaluation.study import (
    MAX_JSON_BYTES,
    StudyError,
    _read_limited,
    _sha,
    evaluate_reviewed_study,
    verify_osm_study,
)
from savoroute.services.storage import write_json_file

METRICS = (
    "recall_at_k", "reciprocal_rank_at_k", "ndcg_at_k", "correct_empty",
)
BASELINES = ("bm25", "overlap")
MAX_RESAMPLES = 20_000


def _read_json(path: str | Path) -> tuple[Any, bytes]:
    raw = _read_limited(Path(path), MAX_JSON_BYTES)
    try:
        return json.loads(raw), raw
    except ValueError as exc:
        raise StudyError("invalid evaluation JSON") from exc


def _bound_sheet(template: dict[str, Any], given: Any, slot: str) -> dict:
    if not isinstance(given, dict) or set(given) != set(template):
        raise StudyError(f"{slot}: reviewer-sheet keys differ from frozen template")
    for key in template.keys() - {"judgments"}:
        if given[key] != template[key]:
            raise StudyError(f"{slot}: reviewer-sheet identity differs: {key}")
    rows = given["judgments"]
    expected = {(row["case_id"], row["item_id"]) for row in template["judgments"]}
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise StudyError(f"{slot}: incomplete or extraneous pair coverage")
    results = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "item_id", "relevant", "note"}:
            raise StudyError(f"{slot}: malformed judgment row")
        if (not isinstance(row["case_id"], str)
                or not isinstance(row["item_id"], str)):
            raise StudyError(f"{slot}: pair identifiers must be strings")
        key = (row["case_id"], row["item_id"])
        if key not in expected or key in results:
            raise StudyError(f"{slot}: duplicate or unknown pair")
        label, note = row["relevant"], row["note"]
        if not isinstance(note, str) or len(note) > 4000:
            raise StudyError(f"{slot}: note must be text of at most 4000 characters")
        if label is not None and type(label) is not bool:
            raise StudyError(f"{slot}: decision must be true, false, or null")
        if label is True and not note.strip():
            raise StudyError(f"{slot}: positive judgment requires a rationale")
        results[key] = label
    return results


def audit_reviewer_progress(
    study_dir: str | Path,
    reviewer_a: str | Path,
    reviewer_b: str | Path,
) -> dict[str, Any]:
    """Validate two version-bound sheets, including *partial* completion.

    Counts only are reported, never peer judgments or item-level disagreements.
    Blank and incomplete sheets are valid audit inputs but not final labels.
    """
    manifest = verify_osm_study(study_dir)
    root = Path(study_dir)
    catalog = load_catalog(root / "catalog.json")
    frozen, _ = _read_json(root / "review_template.json")
    a_template, b_template = split_reviewer_sheets(catalog, frozen)
    a, a_raw = _read_json(reviewer_a)
    b, b_raw = _read_json(reviewer_b)
    left = _bound_sheet(a_template, a, "reviewer_a")
    right = _bound_sheet(b_template, b, "reviewer_b")
    split_by_case = {row["case_id"]: row["split"] for row in frozen["queries"]}

    def counters(keys: list[tuple[str, str]]) -> dict:
        n_a = sum(left[key] is not None for key in keys)
        n_b = sum(right[key] is not None for key in keys)
        n_both = sum(left[key] is not None and right[key] is not None for key in keys)
        conflicts = sum(
            left[key] is not None and right[key] is not None and left[key] != right[key]
            for key in keys
        )
        return {
            "pairs": len(keys), "reviewer_a_complete": n_a,
            "reviewer_b_complete": n_b, "both_complete": n_both,
            "disagreements_on_both_complete": conflicts,
            "ready_to_merge": n_both == len(keys),
        }

    all_keys = list(left)
    result = {
        "audit_version": 1,
        "study_manifest_sha256": _sha(_read_limited(root / "manifest.json", MAX_JSON_BYTES)),
        "catalog_fingerprint": manifest["catalog_fingerprint"],
        "reviewer_sheet_sha256": {"reviewer_a": _sha(a_raw), "reviewer_b": _sha(b_raw)},
        "overall": counters(all_keys),
        "partitions": {
            split: counters([key for key in all_keys if split_by_case[key[0]] == split])
            for split in ("development", "test")
        },
        "annotation_status": (
            "review_sheets_complete_not_adjudicated"
            if all(left[key] is not None and right[key] is not None for key in all_keys)
            else "review_incomplete"
        ),
        "limitations": (
            "Counts do not authenticate reviewer identity or independence. "
            "Do not share individual labels between reviewers before submission. "
            "Disagreements require explicit adjudication."
        ),
    }
    return result


def _validate_settings(*, at_k: int, resamples: int, seed: int, primary_metric: str) -> None:
    if type(at_k) is not int or not 1 <= at_k <= 1000:
        raise StudyError("at_k must be an integer in [1, 1000]")
    if type(resamples) is not int or not 200 <= resamples <= MAX_RESAMPLES:
        raise StudyError("resamples must be an integer in [200, 20000]")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise StudyError("seed must be a nonnegative 32-bit integer")
    if primary_metric not in METRICS:
        raise StudyError(f"primary_metric must be one of {', '.join(METRICS)}")


def prepare_analysis_plan(
    study_dir: str | Path,
    output: str | Path,
    *,
    at_k: int = 5,
    primary_metric: str = "ndcg_at_k",
    resamples: int = 2000,
    seed: int = 2026,
) -> dict[str, Any]:
    """Declare *software* analysis settings before examining final test results.

    This deterministic file has no cryptographic signature or reliable timestamp.
    Independent registration of the plan is needed for preregistration claims.
    """
    _validate_settings(at_k=at_k, resamples=resamples, seed=seed,
                       primary_metric=primary_metric)
    manifest = verify_osm_study(study_dir)
    root = Path(study_dir)
    plan = {
        "analysis_plan_version": 1,
        "study_manifest_sha256": _sha(_read_limited(root / "manifest.json", MAX_JSON_BYTES)),
        "catalog_fingerprint": manifest["catalog_fingerprint"],
        "queries_sha256": manifest["files"]["queries.json"],
        "baselines": list(BASELINES),
        "metrics": list(METRICS),
        "primary_metric": primary_metric,
        "at_k": at_k,
        "resamples": resamples,
        "seed": seed,
        "confidence_level": 0.95,
        "uncertainty_method": "paired_percentile_query_bootstrap",
        "report_policy": "development_first_test_only_after_explicit_release",
    }
    write_json_file(plan, output)
    return plan


def _validate_plan(study_dir: str | Path, plan: Any, raw: bytes) -> str:
    if not isinstance(plan, dict) or set(plan) != {
        "analysis_plan_version", "study_manifest_sha256", "catalog_fingerprint",
        "queries_sha256", "baselines", "metrics", "primary_metric", "at_k",
        "resamples", "seed", "confidence_level", "uncertainty_method", "report_policy",
    } or type(plan["analysis_plan_version"]) is not int or plan["analysis_plan_version"] != 1:
        raise StudyError("unsupported analysis plan schema")
    root = Path(study_dir)
    manifest = verify_osm_study(root)
    if (plan["study_manifest_sha256"] != _sha(_read_limited(root / "manifest.json", MAX_JSON_BYTES))
            or plan["catalog_fingerprint"] != manifest["catalog_fingerprint"]
            or plan["queries_sha256"] != manifest["files"]["queries.json"]):
        raise StudyError("analysis plan does not match frozen study")
    _validate_settings(at_k=plan["at_k"], resamples=plan["resamples"],
                       seed=plan["seed"], primary_metric=plan["primary_metric"])
    if (plan["baselines"] != list(BASELINES) or plan["metrics"] != list(METRICS)
            or plan["confidence_level"] != 0.95
            or plan["uncertainty_method"] != "paired_percentile_query_bootstrap"
            or plan["report_policy"] != "development_first_test_only_after_explicit_release"):
        raise StudyError("analysis plan method or baseline configuration changed")
    return _sha(raw)


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation of order statistics, inclusive of endpoints."""
    position = (len(sorted_values) - 1) * q
    lo = math.floor(position)
    hi = math.ceil(position)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (position - lo)


def _paired_bootstrap(
    left: list[float], right: list[float], *, resamples: int, seed: int, metric: str,
) -> dict:
    if len(left) != len(right):
        raise StudyError("paired runs are missing the same query IDs")
    n = len(left)
    if n == 0:
        return {"n_queries": 0, "estimate": None, "ci95": None,
                "note": "metric is undefined for this query stratum"}
    delta = sum(x - y for x, y in zip(left, right, strict=True)) / n
    if n < 2:
        return {"n_queries": n, "estimate": delta, "ci95": None,
                "note": "fewer than two queries; no interval reported"}
    # Reproducible per-metric streams, independent of Python's randomized hash().
    derived = int.from_bytes(hashlib.sha256(
        f"{seed}:{metric}".encode()
    ).digest()[:8], "big")
    rng = random.Random(derived)
    deltas = [x - y for x, y in zip(left, right, strict=True)]
    sampled = sorted(
        sum(deltas[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(resamples)
    )
    return {"n_queries": n, "estimate": delta,
            "ci95": [_quantile(sampled, 0.025), _quantile(sampled, 0.975)],
            "note": "percentile interval; query-level paired bootstrap, not a significance test"}


def _single_bootstrap(values: list[float], *, resamples: int, seed: int, metric: str) -> dict:
    return _paired_bootstrap(values, [0.0] * len(values), resamples=resamples,
                             seed=seed, metric=metric)


def _case_errors(case: dict, relevant_ids: frozenset[str], at_k: int) -> dict:
    retrieved = case["retrieved_item_ids"]
    if len(retrieved) > at_k or len(retrieved) != len(set(retrieved)):
        raise StudyError("invalid ranking: duplicate IDs or results exceeding k")
    retrieved_set = set(retrieved)
    false_positives = [item for item in retrieved if item not in relevant_ids]
    false_negatives = sorted(relevant_ids - retrieved_set)
    if not relevant_ids:
        failure = "false_positive_on_no_match" if retrieved else "correct_no_match"
    elif not retrieved:
        failure = "no_results_for_positive_query"
    elif len(false_negatives) == len(relevant_ids):
        failure = "zero_recall"
    elif false_negatives:
        failure = "partial_recall"
    else:
        failure = "all_relevant_retrieved"
    return {
        "case_id": case["case_id"], "failure_type": failure,
        "relevant_count": len(relevant_ids), "retrieved_count": len(retrieved),
        "false_positive_item_ids_at_k": false_positives,
        "missed_relevant_item_ids": false_negatives,
        "retrieved_item_ids": retrieved,
        "ndcg_at_k": case["ndcg_at_k"], "recall_at_k": case["recall_at_k"],
    }


def analyze_reviewed_study(
    study_dir: str | Path, workbook_path: str | Path, plan_path: str | Path,
    *, split: Literal["development", "test"] = "development", allow_test: bool = False,
) -> dict[str, Any]:
    """Compare fixed lexical baselines on identical, fully adjudicated query sets."""
    plan, plan_raw = _read_json(plan_path)
    plan_sha = _validate_plan(study_dir, plan, plan_raw)
    baseline_report = evaluate_reviewed_study(
        study_dir, workbook_path, split=split, at_k=plan["at_k"], allow_test=allow_test,
    )
    root = Path(study_dir)
    catalog = load_catalog(root / "catalog.json")
    workbook, _ = _read_json(workbook_path)
    # The prior evaluator verifies the frozen query rows and full human adjudication.
    dev, test, _ = finalize_relevance_workbook(catalog, workbook)
    benchmark = dev if split == "development" else test
    judgments = {row["case_id"]: frozenset(row["relevant_item_ids"])
                 for row in benchmark["queries"]}
    cases_by_method = {
        method: {case["case_id"]: case for case in baseline_report["systems"][method]["cases"]}
        for method in BASELINES
    }
    case_ids = sorted(judgments)
    for method in BASELINES:
        if set(cases_by_method[method]) != set(case_ids):
            raise StudyError("retrieval runs have different query coverage")

    metrics: dict[str, dict] = {}
    for metric in METRICS:
        positive_only = metric != "correct_empty"
        selected = [case_id for case_id in case_ids
                    if bool(judgments[case_id]) == positive_only]
        values = {
            method: [cases_by_method[method][case_id][metric] for case_id in selected]
            for method in BASELINES
        }
        if any(any(v is None or type(v) not in ((bool,) if metric == "correct_empty"
                                                  else (int, float)) or not math.isfinite(v)
                       for v in records) for records in values.values()):
            raise StudyError("expected defined per-query metric values")
        numbers = {method: [float(v) for v in records]
                   for method, records in values.items()}
        metrics[metric] = {
            "query_population": "no_match" if metric == "correct_empty" else "positive",
            "n_queries": len(selected),
            "systems": {
                method: _single_bootstrap(numbers[method], resamples=plan["resamples"],
                                          seed=plan["seed"], metric=f"{metric}:{method}")
                for method in BASELINES
            },
            "bm25_minus_overlap": _paired_bootstrap(
                numbers["bm25"], numbers["overlap"], resamples=plan["resamples"],
                seed=plan["seed"], metric=f"{metric}:paired",
            ),
        }
    if metrics[plan["primary_metric"]]["n_queries"] == 0:
        raise StudyError("primary metric is undefined: no queries in its evaluation stratum")
    errors = {
        method: [_case_errors(cases_by_method[method][case_id], judgments[case_id],
                              plan["at_k"]) for case_id in case_ids]
        for method in BASELINES
    }
    failure_counts = {
        method: dict(sorted(Counter(row["failure_type"] for row in cases).items()))
        for method, cases in errors.items()
    }
    return {
        "analysis_version": 1,
        "study_report": baseline_report,
        "analysis_plan_sha256": plan_sha,
        "primary_metric": plan["primary_metric"],
        "confidence_level": 0.95,
        "bootstrap": {"unit": "query", "paired": True,
                      "resamples": plan["resamples"], "seed": plan["seed"],
                      "type": "percentile", "stratification": "positive_vs_no_match"},
        "metrics": metrics,
        "query_errors": errors,
        "failure_counts": failure_counts,
        "limitations": [
            "All metrics are binary and limited to the frozen catalog/query distribution.",
            "The OSM study is exhaustive within its eligible catalog, not in the real world.",
            "CI estimates reflect variation over queries, not labeling or OSM measurement error.",
            "Very small query strata make bootstrap intervals unstable; no claims of significance.",
            "The analysis plan is checksum-bound but not independently timestamped or registered.",
            "Reviewer independence and correctness cannot be established by software.",
            "No-match queries use a separate exact-empty-output metric.",
            "Baselines are fixed lexical BM25 and weighted overlap; no vector/model evaluation.",
        ],
    }
