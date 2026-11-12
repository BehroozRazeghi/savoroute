"""Evaluate item-level fused retrieval using the existing catalog benchmark format."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from savoroute.domain.models import Catalog
from savoroute.evaluation.retrieval import BenchmarkError, QueryEvaluation, QueryJudgment
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.retrieval.dense import DenseIndex, validate_dense_catalog
from savoroute.retrieval.fusion import FusionWeights, search_fused
from savoroute.retrieval.lexical import filter_catalog
from savoroute.retrieval.vector import VectorIndex, validate_catalog


@dataclass(frozen=True, slots=True)
class FusionEvaluation:
    k: int
    positive_queries: int
    empty_queries: int
    recall_at_k: float | None
    mrr_at_k: float | None
    ndcg_at_k: float | None
    correct_empty_rate: float | None
    cases: tuple[QueryEvaluation, ...]

    def as_dict(self) -> dict[str, object]:
        return {"method": "rrf", "k": self.k,
                "positive_queries": self.positive_queries,
                "no_match_queries": self.empty_queries,
                "recall_at_k": self.recall_at_k, "mrr_at_k": self.mrr_at_k,
                "ndcg_at_k": self.ndcg_at_k,
                "correct_no_match_rate": self.correct_empty_rate,
                "cases": [{"case_id": c.case_id, "query": c.query,
                           "retrieved_item_ids": list(c.retrieved_item_ids),
                           "recall_at_k": c.recall_at_k,
                           "reciprocal_rank_at_k": c.reciprocal_rank_at_k,
                           "ndcg_at_k": c.ndcg_at_k,
                           "correct_empty": c.correct_empty} for c in self.cases]}


def evaluate_fusion(
    catalog: Catalog,
    judgments: Iterable[QueryJudgment],
    *,
    index: VectorIndex | DenseIndex | None = None,
    encoder: JointTextImageEmbedder | None = None,
    catalog_dir: Path | None = None,
    weights: FusionWeights | None = None,
    rrf_k: int = 60,
    pool_size: int = 50,
    at_k: int = 5,
) -> FusionEvaluation:
    if type(at_k) is not int or not 1 <= at_k <= 1000:
        raise BenchmarkError("at_k must be an integer in [1, 1000]")
    cases = tuple(judgments)
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise BenchmarkError("benchmark cases must be nonempty with unique IDs")
    item_ids = {item.item_id for item in catalog.items}
    if index is not None:
        if isinstance(index, DenseIndex):
            validate_dense_catalog(index, catalog, catalog_dir=catalog_dir)
        else:
            validate_catalog(index, catalog, catalog_dir=catalog_dir)
    results: list[QueryEvaluation] = []
    for case in cases:
        unknown = case.relevant_item_ids - item_ids
        if unknown:
            raise BenchmarkError(f"{case.case_id}: unknown relevant items {sorted(unknown)}")
        admissible = {item.item_id for item in filter_catalog(catalog.items, case.filters)}
        outside = case.relevant_item_ids - admissible
        if outside:
            raise BenchmarkError(f"{case.case_id}: relevant items violate filters {sorted(outside)}")
        ranked = tuple(hit.item.item_id for hit in search_fused(
            catalog, case.query, index=index, encoder=encoder,
            catalog_dir=catalog_dir, filters=case.filters, weights=weights,
            rrf_k=rrf_k, pool_size=pool_size, limit=at_k,
        ))
        if not case.relevant_item_ids:
            results.append(QueryEvaluation(case.case_id, case.query, ranked,
                                           None, None, None, not ranked))
            continue
        relevance = [int(item_id in case.relevant_item_ids) for item_id in ranked]
        reciprocal = next((1 / rank for rank, is_rel in enumerate(relevance, start=1)
                           if is_rel), 0.0)
        dcg = sum(is_rel / math.log2(rank + 1)
                  for rank, is_rel in enumerate(relevance, start=1))
        ideal = sum(1 / math.log2(rank + 1)
                    for rank in range(1, min(at_k, len(case.relevant_item_ids)) + 1))
        results.append(QueryEvaluation(
            case.case_id, case.query, ranked,
            sum(relevance) / len(case.relevant_item_ids), reciprocal, dcg / ideal, None,
        ))

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return FusionEvaluation(
        k=at_k,
        positive_queries=sum(row.recall_at_k is not None for row in results),
        empty_queries=sum(row.correct_empty is not None for row in results),
        recall_at_k=mean([row.recall_at_k for row in results if row.recall_at_k is not None]),
        mrr_at_k=mean([row.reciprocal_rank_at_k for row in results
                       if row.reciprocal_rank_at_k is not None]),
        ndcg_at_k=mean([row.ndcg_at_k for row in results if row.ndcg_at_k is not None]),
        correct_empty_rate=mean([float(row.correct_empty) for row in results
                                 if row.correct_empty is not None]),
        cases=tuple(results),
    )
