"""Exhaustive, two-reviewer item-relevance annotation workflow.

The workflow records decisions but never generates ground truth. Each query is
judged against every item admitted by its hard filters; partially reviewed
workbooks cannot be exported as evaluation benchmarks.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from savoroute.domain.models import Catalog
from savoroute.evaluation.retrieval import BenchmarkError, parse_benchmark
from savoroute.retrieval.lexical import SearchFilters, filter_catalog
from savoroute.retrieval.vector import catalog_fingerprint


class RelevanceAnnotationError(BenchmarkError):
    """Invalid or incomplete review artifact."""


_FILTER_KEYS = frozenset({"kind", "cuisine", "location", "max_price_tier", "dietary_tags"})


def _filters(payload: Any) -> SearchFilters:
    if not isinstance(payload, dict) or set(payload) - _FILTER_KEYS:
        raise RelevanceAnnotationError("filters must be an object with recognized keys")
    tags = payload.get("dietary_tags", [])
    if not isinstance(tags, list):
        raise RelevanceAnnotationError("dietary_tags must be an array")
    try:
        return SearchFilters(
            kind=payload.get("kind"), cuisine=payload.get("cuisine"),
            location=payload.get("location"),
            max_price_tier=payload.get("max_price_tier"), dietary_tags=tuple(tags),
        )
    except (TypeError, ValueError) as exc:
        raise RelevanceAnnotationError(f"invalid filters: {exc}") from exc


def _query_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"query_set_version", "queries"}:
        raise RelevanceAnnotationError("query set requires query_set_version and queries")
    if type(payload["query_set_version"]) is not int or payload["query_set_version"] != 1:
        raise RelevanceAnnotationError("unsupported query_set_version")
    rows = payload["queries"]
    if not isinstance(rows, list) or len(rows) < 2:
        raise RelevanceAnnotationError("query set needs at least two queries")
    seen: set[str] = set()
    splits: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "query", "filters", "split"}:
            raise RelevanceAnnotationError("query rows require case_id, query, filters, split")
        case_id, query, split = row["case_id"], row["query"], row["split"]
        if (not isinstance(case_id, str) or not case_id.strip() or case_id in seen
                or not isinstance(query, str) or not query.strip()):
            raise RelevanceAnnotationError("query IDs must be unique and query text nonempty")
        if split not in ("development", "test"):
            raise RelevanceAnnotationError("split must be development or test")
        _filters(row["filters"])
        seen.add(case_id)
        splits.add(split)
    if splits != {"development", "test"}:
        raise RelevanceAnnotationError("query set requires development and test partitions")
    return rows


def prepare_relevance_workbook(
    catalog: Catalog, query_set: Any, *, max_pairs: int = 20_000,
) -> dict[str, Any]:
    """Create a deterministic, unjudged and exhaustive reviewer worksheet."""
    if type(max_pairs) is not int or max_pairs < 1:
        raise RelevanceAnnotationError("max_pairs must be a positive integer")
    queries = _query_rows(query_set)
    pairs: list[dict[str, Any]] = []
    for row in queries:
        eligible = sorted(filter_catalog(catalog.items, _filters(row["filters"])),
                          key=lambda item: item.item_id)
        for item in eligible:
            pairs.append({
                "case_id": row["case_id"], "item_id": item.item_id,
                "reviews": {"reviewer_a": None, "reviewer_b": None},
                "reviewer_notes": {"reviewer_a": "", "reviewer_b": ""},
                "final_label": None, "adjudication_note": "",
            })
            if len(pairs) > max_pairs:
                raise RelevanceAnnotationError("exhaustive worksheet exceeds max_pairs")
    return {
        "workbook_version": 1, "dataset_name": catalog.dataset_name,
        "synthetic": catalog.synthetic, "catalog_sha256": catalog_fingerprint(catalog),
        "queries": deepcopy(queries), "judgments": pairs,
    }


def finalize_relevance_workbook(
    catalog: Catalog, workbook: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (development, test, audit); reject any unreviewed eligible pair.

    Evidence notes are reviewer-supplied; neither agreement nor adjudication
    proves independent review or factual correctness of the judgment itself.
    """
    if not isinstance(workbook, dict) or set(workbook) != {
        "workbook_version", "dataset_name", "synthetic", "catalog_sha256", "queries", "judgments"
    } or type(workbook["workbook_version"]) is not int or workbook["workbook_version"] != 1:
        raise RelevanceAnnotationError("unsupported workbook structure or version")
    if (workbook["dataset_name"] != catalog.dataset_name
            or type(workbook["synthetic"]) is not bool
            or workbook["synthetic"] != catalog.synthetic
            or workbook["catalog_sha256"] != catalog_fingerprint(catalog)):
        raise RelevanceAnnotationError("workbook is incompatible with this catalog snapshot")
    queries = _query_rows({"query_set_version": 1, "queries": workbook["queries"]})
    expected = {(row["case_id"], item.item_id)
                for row in queries
                for item in filter_catalog(catalog.items, _filters(row["filters"]))}
    judgments = workbook["judgments"]
    if not isinstance(judgments, list) or len(judgments) != len(expected):
        raise RelevanceAnnotationError("workbook has missing or unexpected judgment rows")
    seen: set[tuple[str, str]] = set()
    labels: dict[str, set[str]] = {row["case_id"]: set() for row in queries}
    observations: list[tuple[bool, bool]] = []
    disagreements = 0
    for row in judgments:
        if not isinstance(row, dict) or set(row) != {
            "case_id", "item_id", "reviews", "reviewer_notes", "final_label", "adjudication_note"
        }:
            raise RelevanceAnnotationError("invalid judgment row")
        key = (row["case_id"], row["item_id"])
        if key not in expected or key in seen:
            raise RelevanceAnnotationError(f"unknown or repeated judgment pair: {key}")
        seen.add(key)
        reviews, notes = row["reviews"], row["reviewer_notes"]
        if (not isinstance(reviews, dict) or set(reviews) != {"reviewer_a", "reviewer_b"}
                or not isinstance(notes, dict) or set(notes) != {"reviewer_a", "reviewer_b"}):
            raise RelevanceAnnotationError("both reviewer slots are required")
        a, b = reviews["reviewer_a"], reviews["reviewer_b"]
        if type(a) is not bool or type(b) is not bool:
            raise RelevanceAnnotationError(f"unfinished reviews for {key}")
        if any(not isinstance(v, str) for v in notes.values()):
            raise RelevanceAnnotationError("reviewer notes must be strings")
        if (a and not notes["reviewer_a"].strip()) or (b and not notes["reviewer_b"].strip()):
            raise RelevanceAnnotationError(f"positive judgments require a review rationale: {key}")
        decision = row["final_label"]
        note = row["adjudication_note"]
        if type(decision) is not bool or not isinstance(note, str):
            raise RelevanceAnnotationError(f"unfinished adjudication for {key}")
        if a == b and decision != a:
            raise RelevanceAnnotationError(f"agreement contradicted by final decision: {key}")
        if a != b:
            disagreements += 1
            if not note.strip():
                raise RelevanceAnnotationError(f"disagreement needs adjudication rationale: {key}")
        if decision:
            labels[row["case_id"]].add(row["item_id"])
        observations.append((a, b))
    if seen != expected:
        raise RelevanceAnnotationError("workbook does not cover every eligible query-item pair")

    def benchmark(split: str) -> dict[str, Any]:
        payload = {"benchmark_version": 1, "queries": [
            {"case_id": row["case_id"], "query": row["query"],
             "relevant_item_ids": sorted(labels[row["case_id"]]), "filters": row["filters"]}
            for row in queries if row["split"] == split
        ]}
        parse_benchmark(payload)
        return payload

    agreement = sum(a == b for a, b in observations) / len(observations) if observations else None
    kappa = None
    if observations:
        n = len(observations)
        p_a = sum(a for a, _ in observations) / n
        p_b = sum(b for _, b in observations) / n
        chance = p_a * p_b + (1 - p_a) * (1 - p_b)
        if not math.isclose(chance, 1.0):
            kappa = (agreement - chance) / (1 - chance)
    workbook_sha256 = hashlib.sha256(json.dumps(
        workbook, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    audit = {
        "audit_version": 1, "dataset_name": catalog.dataset_name,
        "workbook_sha256": workbook_sha256,
        "catalog_sha256": catalog_fingerprint(catalog),
        "synthetic": catalog.synthetic, "query_count": len(queries),
        "judged_pairs": len(observations), "development_queries": sum(
            row["split"] == "development" for row in queries),
        "test_queries": sum(row["split"] == "test" for row in queries),
        "positive_pairs": sum(map(len, labels.values())),
        "disagreements": disagreements, "observed_agreement": agreement,
        "cohen_kappa": kappa, "judgment_scope": "exhaustive_filtered_catalog",
        "annotation_provenance": "reviewer-supplied; independence not verified by software",
    }
    return benchmark("development"), benchmark("test"), audit


def load_query_set(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    _query_rows(payload)
    return payload


def load_relevance_workbook(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RelevanceAnnotationError("workbook must be a JSON object")
    return payload


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def split_reviewer_sheets(
    catalog: Catalog, template: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare separate, blank reviewer files without exposing peer labels."""
    if not isinstance(template, dict) or not isinstance(template.get("judgments"), list):
        raise RelevanceAnnotationError("expected a prepared relevance workbook")
    expected = prepare_relevance_workbook(
        catalog, {"query_set_version": 1, "queries": template.get("queries")},
        max_pairs=max(1, len(template["judgments"])),
    )
    if template != expected:
        raise RelevanceAnnotationError("review template is modified or belongs to another catalog")
    fingerprint = _canonical_sha256(template)
    result = []
    for slot in ("reviewer_a", "reviewer_b"):
        result.append({
            "review_sheet_version": 1, "reviewer_slot": slot,
            "template_sha256": fingerprint,
            "catalog_sha256": template["catalog_sha256"],
            "dataset_name": template["dataset_name"], "synthetic": template["synthetic"],
            "judgments": [
                {"case_id": row["case_id"], "item_id": row["item_id"],
                 "relevant": None, "note": ""}
                for row in template["judgments"]
            ],
        })
    return result[0], result[1]


def merge_reviewer_sheets(
    catalog: Catalog, template: Any, reviewer_a: Any, reviewer_b: Any,
) -> dict[str, Any]:
    """Combine independently filled sheets; leave disagreements for adjudication."""
    a_template, b_template = split_reviewer_sheets(catalog, template)
    received = []
    expected_pairs = {(row["case_id"], row["item_id"])
                      for row in template["judgments"]}
    for given, reference in ((reviewer_a, a_template), (reviewer_b, b_template)):
        if not isinstance(given, dict) or set(given) != set(reference):
            raise RelevanceAnnotationError("invalid reviewer-sheet structure")
        for name in set(reference) - {"judgments"}:
            if given[name] != reference[name]:
                raise RelevanceAnnotationError(f"reviewer-sheet metadata mismatch: {name}")
        rows = given["judgments"]
        if not isinstance(rows, list) or len(rows) != len(expected_pairs):
            raise RelevanceAnnotationError("reviewer-sheet pair coverage mismatch")
        decisions = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "case_id", "item_id", "relevant", "note"
            }:
                raise RelevanceAnnotationError("invalid reviewer judgment row")
            key = (row["case_id"], row["item_id"])
            if key not in expected_pairs or key in decisions:
                raise RelevanceAnnotationError(f"duplicate or unknown reviewer pair: {key}")
            if type(row["relevant"]) is not bool or not isinstance(row["note"], str):
                raise RelevanceAnnotationError(f"reviewer judgment is incomplete: {key}")
            if row["relevant"] and not row["note"].strip():
                raise RelevanceAnnotationError(f"positive review requires a rationale: {key}")
            decisions[key] = (row["relevant"], row["note"])
        received.append(decisions)
    merged = deepcopy(template)
    for row in merged["judgments"]:
        key = (row["case_id"], row["item_id"])
        a, b = received[0][key], received[1][key]
        row["reviews"] = {"reviewer_a": a[0], "reviewer_b": b[0]}
        row["reviewer_notes"] = {"reviewer_a": a[1], "reviewer_b": b[1]}
        row["final_label"] = a[0] if a[0] == b[0] else None
        row["adjudication_note"] = ""
    return merged
