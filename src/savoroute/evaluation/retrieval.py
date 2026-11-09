"""Reproducible, small-scale evaluation of catalog retrieval.

No-match queries have their own correctness metric and are not assigned a
meaningless zero for positive-only metrics. These are synthetic demo judgments.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from savoroute.domain.models import CatalogItem
from savoroute.retrieval.lexical import (
    Method,
    SearchFilters,
    filter_catalog,
    search_catalog,
)


class BenchmarkError(ValueError):
    """Raised when a benchmark has an invalid schema or inconsistent judgments."""


@dataclass(frozen=True, slots=True)
class QueryJudgment:
    case_id: str
    query: str
    relevant_item_ids: frozenset[str]
    filters: SearchFilters


@dataclass(frozen=True, slots=True)
class QueryEvaluation:
    case_id: str
    query: str
    retrieved_item_ids: tuple[str, ...]
    recall_at_k: float | None
    reciprocal_rank_at_k: float | None
    ndcg_at_k: float | None
    correct_empty: bool | None


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    method: Method
    at_k: int
    positive_queries: int
    empty_queries: int
    mean_recall_at_k: float | None
    mrr_at_k: float | None
    mean_ndcg_at_k: float | None
    correct_empty_rate: float | None
    cases: tuple[QueryEvaluation, ...]

    def as_dict(self) -> dict[str, int | str | float | None]:
        return {
            "method": self.method,
            "k": self.at_k,
            "positive_queries": self.positive_queries,
            "no_match_queries": self.empty_queries,
            "recall_at_k": self.mean_recall_at_k,
            "mrr_at_k": self.mrr_at_k,
            "ndcg_at_k": self.mean_ndcg_at_k,
            "correct_no_match_rate": self.correct_empty_rate,
        }


def parse_benchmark(payload: Any) -> tuple[QueryJudgment, ...]:
    if not isinstance(payload, dict) or set(payload) != {"benchmark_version", "queries"}:
        raise BenchmarkError("benchmark must contain benchmark_version and queries")
    if type(payload["benchmark_version"]) is not int or payload["benchmark_version"] != 1:
        raise BenchmarkError("unsupported benchmark_version (expected 1)")
    if not isinstance(payload["queries"], list) or not payload["queries"]:
        raise BenchmarkError("queries must be a nonempty array")
    cases: list[QueryJudgment] = []
    seen: set[str] = set()
    for index, value in enumerate(payload["queries"]):
        context = f"queries[{index}]"
        if not isinstance(value, dict) or set(value) != {
            "case_id", "query", "relevant_item_ids", "filters"
        }:
            raise BenchmarkError(f"{context} has an invalid structure")
        case_id, query = value["case_id"], value["query"]
        relevant, raw_filters = value["relevant_item_ids"], value["filters"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise BenchmarkError(f"{context}.case_id must be unique and nonempty")
        seen.add(case_id)
        if not isinstance(query, str) or not query.strip():
            raise BenchmarkError(f"{context}.query must be a nonempty string")
        if not isinstance(relevant, list) or any(
            not isinstance(identifier, str) or not identifier.strip() for identifier in relevant
        ) or len(set(relevant)) != len(relevant):
            raise BenchmarkError(f"{context}.relevant_item_ids must be unique strings")
        if not isinstance(raw_filters, dict) or set(raw_filters) - {
            "kind", "cuisine", "location", "max_price_tier", "dietary_tags"
        }:
            raise BenchmarkError(f"{context}.filters has invalid keys")
        tags = raw_filters.get("dietary_tags", [])
        if not isinstance(tags, list):
            raise BenchmarkError(f"{context}.filters.dietary_tags must be an array")
        try:
            filters = SearchFilters(
                kind=raw_filters.get("kind"),
                cuisine=raw_filters.get("cuisine"),
                location=raw_filters.get("location"),
                max_price_tier=raw_filters.get("max_price_tier"),
                dietary_tags=tuple(tags),
            )
        except (ValueError, TypeError) as exc:
            raise BenchmarkError(f"{context}.filters: {exc}") from exc
        cases.append(QueryJudgment(case_id, query, frozenset(relevant), filters))
    return tuple(cases)


def load_benchmark(path: str | Path | None = None) -> tuple[QueryJudgment, ...]:
    if path is None:
        text = files("savoroute.resources").joinpath("demo_benchmark.json").read_text(
            encoding="utf-8"
        )
    else:
        text = Path(path).read_text(encoding="utf-8")
    return parse_benchmark(json.loads(text))


def evaluate_search(
    items: Iterable[CatalogItem],
    judgments: Iterable[QueryJudgment],
    *,
    at_k: int = 5,
    method: Method = "bm25",
) -> EvaluationSummary:
    """Compute macro binary Recall@k, MRR@k, nDCG@k, no-match rate."""
    if type(at_k) is not int or at_k < 1:
        raise ValueError("at_k must be a positive integer")
    if method not in ("bm25", "overlap"):
        raise ValueError("method must be 'bm25' or 'overlap'")
    records = tuple(items)
    cases = tuple(judgments)
    ids = {item.item_id for item in records}
    if len(ids) != len(records):
        raise BenchmarkError("catalog contains duplicate item IDs")
    if not cases:
        raise BenchmarkError("benchmark must contain at least one query")
    if len({case.case_id for case in cases}) != len(cases):
        raise BenchmarkError("duplicate benchmark case_id")
    results: list[QueryEvaluation] = []
    for case in cases:
        unknown = case.relevant_item_ids - ids
        if unknown:
            raise BenchmarkError(f"{case.case_id}: unknown relevant item IDs {sorted(unknown)}")
        admissible = {item.item_id for item in filter_catalog(records, case.filters)}
        outside = case.relevant_item_ids - admissible
        if outside:
            raise BenchmarkError(f"{case.case_id}: relevant items violate filters {sorted(outside)}")
        ranked = tuple(hit.item.item_id for hit in search_catalog(
            records, case.query, case.filters, method=method, limit=at_k
        ))
        if not case.relevant_item_ids:
            results.append(QueryEvaluation(case.case_id, case.query, ranked,
                                           None, None, None, not ranked))
            continue
        binary = [int(identifier in case.relevant_item_ids) for identifier in ranked]
        found = sum(binary)
        reciprocal = next((1 / rank for rank, rel in enumerate(binary, start=1) if rel), 0.0)
        dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(binary, start=1))
        ideal = sum(1 / math.log2(rank + 1) for rank in range(
            1, min(at_k, len(case.relevant_item_ids)) + 1
        ))
        results.append(QueryEvaluation(
            case.case_id, case.query, ranked, found / len(case.relevant_item_ids),
            reciprocal, dcg / ideal, None,
        ))

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return EvaluationSummary(
        method=method,
        at_k=at_k,
        positive_queries=sum(case.recall_at_k is not None for case in results),
        empty_queries=sum(case.correct_empty is not None for case in results),
        mean_recall_at_k=mean([case.recall_at_k for case in results
                              if case.recall_at_k is not None]),
        mrr_at_k=mean([case.reciprocal_rank_at_k for case in results
                       if case.reciprocal_rank_at_k is not None]),
        mean_ndcg_at_k=mean([case.ndcg_at_k for case in results
                             if case.ndcg_at_k is not None]),
        correct_empty_rate=mean([float(case.correct_empty) for case in results
                                 if case.correct_empty is not None]),
        cases=tuple(results),
    )
