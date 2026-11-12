"""Deterministic synthetic-vector latency and exact-agreement harness.

The generated vectors are not relevance judgments. Wall-clock latency must be
measured on the target machine; do not assert fixed thresholds in unit tests.
"""

from __future__ import annotations

import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Literal

from savoroute.retrieval.dense import load_dense_index, search_dense, write_dense_index
from savoroute.retrieval.vector import VectorIndex, VectorRecord, search_vectors


@dataclass(frozen=True, slots=True)
class DenseBenchmark:
    backend: str
    records: int
    dimension: int
    queries: int
    k: int
    seed: int
    build_seconds: float
    median_ms: float
    p95_ms: float
    mean_exact_overlap_at_k: float

    def as_dict(self) -> dict[str, str | int | float]:
        return {"backend": self.backend, "records": self.records,
                "dimension": self.dimension, "queries": self.queries,
                "k": self.k, "seed": self.seed,
                "build_seconds": round(self.build_seconds, 4),
                "median_ms": round(self.median_ms, 4),
                "p95_ms": round(self.p95_ms, 4),
                "mean_exact_overlap_at_k": round(self.mean_exact_overlap_at_k, 6)}


def generated_records(n: int, dimension: int, seed: int):
    """Stream repeatable unit vectors in ordinal-ID order."""
    rng = random.Random(seed)
    for ordinal in range(n):
        values = [rng.gauss(0, 1) for _ in range(dimension)]
        norm = sum(value * value for value in values) ** 0.5
        yield VectorRecord(
            f"text:synthetic-{ordinal:08d}", f"item-{ordinal:08d}",
            "text", "a" * 64, tuple(value / norm for value in values),
        )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(fraction * len(ordered) + 0.999999) - 1))]


def benchmark_dense(
    *, backend: Literal["sqlite", "faiss-hnsw"] = "sqlite",
    records: int = 1000, dimension: int = 32, queries: int = 20,
    k: int = 10, seed: int = 7,
) -> DenseBenchmark:
    if (type(records) is not int or not 10 <= records <= 20_000
            or type(dimension) is not int or not 1 <= dimension <= 512
            or records * dimension > 1_000_000
            or type(queries) is not int or not 1 <= queries <= 1000
            or type(k) is not int or not 1 <= k <= min(records, 1000)
            or type(seed) is not int or not 0 <= seed < 2**31):
        raise ValueError("invalid benchmark parameters")
    rows = tuple(generated_records(records, dimension, seed))
    reference = VectorIndex("benchmark-v1", "synthetic-space-v1", dimension,
                            "synthetic-latency", True, "0" * 64, rows)
    query_rng = random.Random(seed + 1)
    positions = [query_rng.randrange(records) for _ in range(queries)]
    with tempfile.TemporaryDirectory(prefix="savoroute-benchmark-") as temp:
        start = time.perf_counter()
        write_dense_index(rows, Path(temp) / "dense", model_id=reference.model_id,
                          embedding_space_id=reference.embedding_space_id,
                          dimension=reference.dimension, dataset_name=reference.dataset_name,
                          synthetic=True, catalog_sha256=reference.catalog_sha256,
                          engine=backend)
        build_seconds = time.perf_counter() - start
        dense = load_dense_index(Path(temp) / "dense")
        # Warm-up is excluded from latency measurements.
        search_dense(dense, rows[positions[0]].vector, k=k)
        timings = []
        agreement = []
        for pos in positions:
            query = rows[pos].vector
            truth = search_vectors(reference, query, k=k)
            start = time.perf_counter_ns()
            actual = search_dense(dense, query, k=k)
            timings.append((time.perf_counter_ns() - start) / 1_000_000)
            truth_ids = {hit.record_id for hit in truth}
            agreement.append(sum(hit.record_id in truth_ids for hit in actual) / k)
    return DenseBenchmark(backend, records, dimension, queries, k, seed,
                          build_seconds, median(timings), _percentile(timings, 0.95),
                          sum(agreement) / len(agreement))
