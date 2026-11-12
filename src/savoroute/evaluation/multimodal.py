"""Labeled text-to-image and image-to-image retrieval evaluation.

Case judgments are supplied independently of the retrieval implementation.
A self-match case is explicitly marked and must not be treated as a generalization result.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.retrieval.vector import (
    VectorIndex,
    VectorIndexError,
    local_image_path,
    search_with_encoder,
)


@dataclass(frozen=True, slots=True)
class MultimodalCase:
    case_id: str
    query_type: Literal["text", "image"]
    query: str
    relevant_record_ids: frozenset[str]
    exclude_record_ids: frozenset[str]
    self_match: bool = False


@dataclass(frozen=True, slots=True)
class MultimodalBenchmark:
    name: str
    dataset_name: str
    synthetic: bool
    cases: tuple[MultimodalCase, ...]
    base_dir: Path


@dataclass(frozen=True, slots=True)
class MultimodalScore:
    case_id: str
    query_type: str
    retrieved_record_ids: tuple[str, ...]
    recall_at_k: float
    reciprocal_rank_at_k: float
    ndcg_at_k: float
    self_match: bool


@dataclass(frozen=True, slots=True)
class MultimodalSummary:
    benchmark: str
    k: int
    cases: tuple[MultimodalScore, ...]
    mean_recall_at_k: float
    mrr_at_k: float
    mean_ndcg_at_k: float
    synthetic: bool
    self_match_cases: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark, "k": self.k, "queries": len(self.cases),
            "synthetic": self.synthetic, "self_match_cases": self.self_match_cases,
            "mean_recall_at_k": self.mean_recall_at_k, "mrr_at_k": self.mrr_at_k,
            "mean_ndcg_at_k": self.mean_ndcg_at_k,
            "cases": [{"case_id": case.case_id, "query_type": case.query_type,
                       "retrieved_record_ids": list(case.retrieved_record_ids),
                       "recall_at_k": case.recall_at_k,
                       "reciprocal_rank_at_k": case.reciprocal_rank_at_k,
                       "ndcg_at_k": case.ndcg_at_k, "self_match": case.self_match}
                      for case in self.cases],
        }


def load_multimodal_benchmark(path: str | Path) -> MultimodalBenchmark:
    file = Path(path)
    if file.stat().st_size > 256 * 1024:
        raise VectorIndexError("multimodal benchmark exceeds 256 KiB")
    doc = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or set(doc) != {
        "schema_version", "name", "dataset_name", "synthetic", "cases"
    } or type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise VectorIndexError("invalid multimodal benchmark schema")
    if (not isinstance(doc["name"], str) or not doc["name"].strip()
            or not isinstance(doc["dataset_name"], str) or not doc["dataset_name"].strip()
            or type(doc["synthetic"]) is not bool):
        raise VectorIndexError("invalid multimodal benchmark metadata")
    cases = doc["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise VectorIndexError("benchmark must contain 1 to 200 cases")
    seen: set[str] = set()
    parsed = []
    for row in cases:
        if (not isinstance(row, dict)
                or set(row) != {"case_id", "query_type", "query", "relevant_record_ids",
                                   "exclude_record_ids", "self_match"}):
            raise VectorIndexError("invalid benchmark case keys")
        if (not isinstance(row["case_id"], str) or not row["case_id"].strip()
                or row["case_id"] in seen or row["query_type"] not in ("text", "image")
                or not isinstance(row["query"], str) or not row["query"].strip()
                or type(row["self_match"]) is not bool):
            raise VectorIndexError("invalid benchmark case identity")
        for field in ("relevant_record_ids", "exclude_record_ids"):
            values = row[field]
            if (not isinstance(values, list) or any(not isinstance(x, str) or not x
                                                   for x in values)
                    or len(set(values)) != len(values)):
                raise VectorIndexError("invalid benchmark relevance list")
        relevant = frozenset(row["relevant_record_ids"])
        exclude = frozenset(row["exclude_record_ids"])
        if not relevant or relevant & exclude:
            raise VectorIndexError("relevant IDs must be nonempty and not excluded")
        seen.add(row["case_id"])
        parsed.append(MultimodalCase(row["case_id"], row["query_type"], row["query"],
                                     relevant, exclude, row["self_match"]))
    return MultimodalBenchmark(doc["name"], doc["dataset_name"], doc["synthetic"],
                               tuple(parsed), file.resolve().parent)


def evaluate_multimodal(
    index: VectorIndex, encoder: JointTextImageEmbedder, benchmark: MultimodalBenchmark,
    *, k: int = 5,
) -> MultimodalSummary:
    if benchmark.dataset_name != index.dataset_name or benchmark.synthetic != index.synthetic:
        raise VectorIndexError("benchmark dataset does not match the index")
    image_ids = {row.record_id for row in index.records if row.modality == "image"}
    if not image_ids:
        raise VectorIndexError("benchmark requires indexed images")
    scores = []
    for case in benchmark.cases:
        if not case.relevant_record_ids <= image_ids:
            raise VectorIndexError("benchmark references missing image record IDs")
        if not case.exclude_record_ids <= {r.record_id for r in index.records}:
            raise VectorIndexError("benchmark excludes unknown record IDs")
        query_image = (local_image_path(benchmark.base_dir, case.query)
                       if case.query_type == "image" else None)
        hits = search_with_encoder(
            index, encoder, text=case.query if case.query_type == "text" else None,
            image=query_image, target="image", k=k, exclude=case.exclude_record_ids,
        )
        retrieved = tuple(hit.record_id for hit in hits)
        count = len(case.relevant_record_ids)
        matches = [rank for rank, record_id in enumerate(retrieved, start=1)
                   if record_id in case.relevant_record_ids]
        recall = len(matches) / count
        reciprocal = 1 / matches[0] if matches else 0.0
        dcg = sum(1 / math.log2(rank + 1) for rank in matches)
        ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, count) + 1))
        scores.append(MultimodalScore(case.case_id, case.query_type, retrieved,
                                      recall, reciprocal, dcg / ideal, case.self_match))
    n = len(scores)
    return MultimodalSummary(
        benchmark.name, k, tuple(scores),
        sum(case.recall_at_k for case in scores) / n,
        sum(case.reciprocal_rank_at_k for case in scores) / n,
        sum(case.ndcg_at_k for case in scores) / n,
        benchmark.synthetic, sum(case.self_match for case in scores),
    )
