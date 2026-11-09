"""Example batch experiment using the same installable Savoroute library as the CLI.

Usage: python scripts/run_offline_baselines.py --output outputs/phase0-metrics.json
No model or network access is needed. Output files are gitignored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from savoroute.data.catalog import load_catalog
from savoroute.evaluation.retrieval import evaluate_search, load_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a reproducible synthetic benchmark")
    parser.add_argument("--catalog", help="optional catalog JSON; default bundled")
    parser.add_argument("--benchmark", help="optional judgment JSON; default bundled")
    parser.add_argument("--at-k", type=int, default=5)
    parser.add_argument("--output", type=Path, help="optional JSON result file")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    judgments = load_benchmark(args.benchmark)
    report = {
        "dataset_name": catalog.dataset_name,
        "synthetic": catalog.synthetic,
        "benchmark_cases": len(judgments),
        "retrieval": [
            evaluate_search(catalog.items, judgments, at_k=args.at_k, method=method).as_dict()
            for method in ("bm25", "overlap")
        ],
        "disclaimer": "Synthetic catalog and relevance labels; not real-world performance.",
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
