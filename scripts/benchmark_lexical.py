"""Local latency microbenchmark for stateless vs catalog-bound lexical retrieval.

This measures the exact same scoring implementation with or without reuse of
precomputed index statistics. It does NOT measure relevance, user experience,
request-network latency, or production throughput. Do not treat small timing
samples or fabricated catalog expansion as a population estimate.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

from savoroute.data.catalog import load_catalog
from savoroute.retrieval.lexical import LexicalIndex, search_catalog

QUERIES = (
    "spicy tofu noodles", "Italian food", "hummus vegan options",
    "soup", "vegetarian restaurant", "pasta tomato",
)


def _latency_summary(samples_ns: list[int]) -> dict[str, float | int]:
    sorted_samples = sorted(samples_ns)
    p95_index = min(len(sorted_samples) - 1, (95 * len(sorted_samples) + 99) // 100 - 1)
    return {
        "count": len(samples_ns),
        "p50_ms": round(statistics.median(samples_ns) / 1_000_000, 4),
        "p95_ms": round(sorted_samples[p95_index] / 1_000_000, 4),
    }


def _expanded_catalog(base, repeat: int):
    """Replicate existing records with new IDs; synthetic load test, not new evidence."""
    if repeat == 1:
        return base
    return tuple(replace(item, item_id=f"{item.item_id}__loadtest_{copy:05d}")
                 for copy in range(repeat) for item in base)


def run_benchmark(catalog_path: str | None, *, repeat: int, loops: int, warmup: int) -> dict:
    if type(repeat) is not int or not 1 <= repeat <= 2000:
        raise ValueError("repeat must be an integer in [1, 2000]")
    if type(loops) is not int or not 1 <= loops <= 200:
        raise ValueError("loops must be an integer in [1, 200]")
    if type(warmup) is not int or not 0 <= warmup <= 100:
        raise ValueError("warmup must be an integer in [0, 100]")
    original = load_catalog(catalog_path)
    if len(original.items) * repeat > 100_000:
        raise ValueError("synthetic benchmark exceeds 100,000 records")
    items = _expanded_catalog(original.items, repeat)
    if not items:
        raise ValueError("cannot benchmark an empty catalog")
    started = time.perf_counter_ns()
    index = LexicalIndex.build(items)
    build_ns = time.perf_counter_ns() - started

    for method in ("bm25", "overlap"):
        for query in QUERIES:
            stateless = search_catalog(items, query, method=method, limit=10)
            indexed = index.search(query, method=method, limit=10)
            if stateless != indexed:
                raise AssertionError("indexed retrieval changed ranked results or scores")

    measurements = {}
    for method in ("bm25", "overlap"):
        results: dict[str, list[int]] = {"stateless": [], "indexed": []}
        for cycle in range(warmup + loops):
            # Alternate order across cycles to limit systematic heat/order bias.
            order = ("stateless", "indexed") if cycle % 2 == 0 else ("indexed", "stateless")
            for mode in order:
                for query in QUERIES:
                    start = time.perf_counter_ns()
                    if mode == "indexed":
                        index.search(query, limit=10, method=method)
                    else:
                        search_catalog(items, query, limit=10, method=method)
                    if cycle >= warmup:
                        results[mode].append(time.perf_counter_ns() - start)
        stateless = _latency_summary(results["stateless"])
        indexed = _latency_summary(results["indexed"])
        measurements[method] = {
            "stateless": stateless,
            "indexed": indexed,
            "median_ratio_stateless_over_indexed": (
                round(stateless["p50_ms"] / indexed["p50_ms"], 3)
                if indexed["p50_ms"] else None
            ),
        }

    return {
        "kind": "local_lexical_latency_microbenchmark_v1",
        "interpretation": (
            "Stateless rebuilds the same lexical index per query; indexed reuses one index. "
            "Synthetic repetition is a load exercise, not distinct restaurant evidence. "
            "Results are machine-specific and do not measure retrieval effectiveness."
        ),
        "catalog_name": original.dataset_name,
        "original_items": len(original.items),
        "measured_items": len(items),
        "replication_factor": repeat,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "query_count": len(QUERIES),
        "loops": loops,
        "warmup_loops": warmup,
        "index_build_ms": round(build_ns / 1_000_000, 4),
        "methods": measurements,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", help="catalog JSON; default: packaged fictional demo")
    parser.add_argument("--repeat", type=int, default=1, help="synthetic load multiplier")
    parser.add_argument("--loops", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--output", type=Path, help="new JSON report path; never overwrite")
    arguments = parser.parse_args(argv)
    try:
        report = run_benchmark(arguments.catalog, repeat=arguments.repeat,
                               loops=arguments.loops, warmup=arguments.warmup)
        encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if arguments.output is None:
            print(encoded, end="")
        else:
            with arguments.output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
            print(f"Wrote {arguments.output}")
    except (ValueError, OSError) as exc:
        print(f"Benchmark error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
