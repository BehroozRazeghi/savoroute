"""Offline quality measurement from reviewed data, without API calls."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from savoroute.live.evaluation import evaluate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="JSON with annotated cases and result lists")
    parser.add_argument("--require-zero-violations", action="store_true")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    metrics = evaluate_dataset(dataset)
    print(json.dumps({"dataset_type": dataset.get("dataset_type", "unlabeled"),
                      **asdict(metrics)}, indent=2))
    if args.require_zero_violations and metrics.hard_constraint_violation_rate not in (None, 0):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
