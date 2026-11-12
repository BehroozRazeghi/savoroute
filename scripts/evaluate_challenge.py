"""Report category-level retrieval metrics for the fictional challenge benchmark."""

from __future__ import annotations

import json
from collections import defaultdict

from savoroute.data.catalog import load_catalog
from savoroute.evaluation.fusion import evaluate_fusion
from savoroute.evaluation.retrieval import load_benchmark
from savoroute.retrieval.fusion import FusionWeights


def main() -> None:
    catalog = load_catalog("data/sample/catalog.json")
    judgments = load_benchmark("data/sample/relevance_challenge_v1.json")
    groups = defaultdict(list)
    for case in judgments:
        groups[case.case_id.split("-", 1)[0]].append(case)
    results = {}
    for name, cases in sorted(groups.items()):
        result = evaluate_fusion(catalog, cases, weights=FusionWeights(1, 0, 0), at_k=5)
        results[name] = {key: value for key, value in result.as_dict().items()
                         if key != "cases"}
    print(json.dumps({"dataset": "synthetic-challenge-v1", "groups": results}, indent=2))


if __name__ == "__main__":
    main()
