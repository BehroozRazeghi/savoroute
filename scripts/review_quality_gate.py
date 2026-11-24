"""Fail closed on incomplete human labels; enforce offline controlled-beta quality gates.

Real reviewer judgments are required. No network/provider calls are made.
Thresholds are provisional release criteria, NOT evidence of achieved quality.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from savoroute.live.evaluation import evaluate_dataset


def validate_reviewed_dataset(data: dict, *, minimum: int = 100) -> None:
    kind = str(data.get("dataset_type", "")).casefold()
    if any(word in kind for word in ("synthetic", "template", "fixture", "unreviewed")):
        raise ValueError("Real-world evaluation cannot use template or synthetic datasets")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) < minimum:
        raise ValueError(f"At least {minimum} human-reviewed real queries are required")
    for row in cases:
        if not isinstance(row, dict) or row.get("review_status") != "reviewed":
            raise ValueError("Every case must have review_status=reviewed")
        if not isinstance(row.get("reviewed_by"), str) or len(row["reviewed_by"].strip()) < 3:
            raise ValueError("Every case requires a reviewer identity")
        if not isinstance(row.get("reviewer_notes"), str) or len(row["reviewer_notes"].strip()) < 10:
            raise ValueError("Every case requires meaningful evidence/reviewer notes")
        try:
            when = date.fromisoformat(row["reviewed_at"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("Every case requires a valid reviewed_at date") from exc
        if when > date.today():
            raise ValueError("Review date cannot be in the future")
    # This also validates consistent answerability, relevance IDs and constraints.
    evaluate_dataset(data)


def run_gate(data: dict, *, minimum: int, minimum_answerable: int,
             minimum_unanswerable: int, success: float, abstention: float,
             source_coverage: float) -> dict:
    validate_reviewed_dataset(data, minimum=minimum)
    result = evaluate_dataset(data)
    checks = {
        "sufficient_answerable": result.answerable_cases >= minimum_answerable,
        "sufficient_unanswerable": result.unanswerable_cases >= minimum_unanswerable,
        "zero_hard_constraint_violations": result.hard_constraint_violation_rate in (None, 0),
        "answerable_success_at_5": (
            result.success_at_5_answerable is not None
            and result.success_at_5_answerable >= success
        ),
        "correct_abstention": (
            (minimum_unanswerable == 0 and result.unanswerable_cases == 0)
            or (result.correct_abstention_unanswerable is not None
                and result.correct_abstention_unanswerable >= abstention)
        ),
        "source_coverage": (
            result.cited_url_coverage is not None
            and result.cited_url_coverage >= source_coverage
        ),
    }
    return {"passed": all(checks.values()), "checks": checks, "cases": result.cases,
            "success_at_5_answerable": result.success_at_5_answerable,
            "correct_abstention_unanswerable": result.correct_abstention_unanswerable,
            "hard_constraint_violation_rate": result.hard_constraint_violation_rate,
            "cited_url_coverage": result.cited_url_coverage}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--min-cases", type=int, default=100)
    parser.add_argument("--min-answerable", type=int, default=20)
    parser.add_argument("--min-unanswerable", type=int, default=20)
    parser.add_argument("--min-success", type=float, default=0.8)
    parser.add_argument("--min-abstention", type=float, default=0.9)
    parser.add_argument("--min-cited", type=float, default=0.95)
    args = parser.parse_args()
    if args.min_cases < 1 or any(not 0 <= value <= 1 for value in
        (args.min_success, args.min_abstention, args.min_cited)):
        parser.error("Invalid minimum cases or target fractions")
    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    report = run_gate(data, minimum=args.min_cases,
                      minimum_answerable=args.min_answerable,
                      minimum_unanswerable=args.min_unanswerable,
                      success=args.min_success, abstention=args.min_abstention,
                      source_coverage=args.min_cited)
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
