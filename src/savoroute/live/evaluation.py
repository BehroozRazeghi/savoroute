"""Offline, annotation-dependent discovery quality metrics.

This module never calls the model and never treats synthetic fixtures as
real-world evidence. Precision is computed only against explicit labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from savoroute.live.contracts import LiveDiscoveryInput
from savoroute.live.validation import _safe_url, canonical_cuisine, place_matches


@dataclass(frozen=True)
class EvaluationSummary:
    cases: int
    answerable_cases: int
    unanswerable_cases: int
    results: int
    precision_at_5: float | None
    success_at_5_answerable: float | None
    correct_abstention_unanswerable: float | None
    hard_constraint_violation_rate: float | None
    cited_url_coverage: float | None
    notes: str = (
        "Metrics use supplied relevance annotations only. A web-tool URL is NOT independent "
        "verification. Synthetic examples are regression fixtures, not measured market quality."
    )


def _fraction(success: int, total: int) -> float | None:
    return round(success / total, 4) if total else None


def evaluate_dataset(dataset: dict[str, Any]) -> EvaluationSummary:
    """Evaluate annotated cases; reject malformed or unlabeled cases explicitly."""
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("evaluation requires a nonempty cases array")
    seen: set[str] = set()
    answerable_count = absent_count = produced = violations = cited = 0
    precision_sum = found_count = abstention_count = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("case needs an id")
        if case["id"] in seen:
            raise ValueError("duplicate evaluation case id")
        seen.add(case["id"])
        if type(case.get("answerable")) is not bool:
            raise ValueError("each case requires a reviewed answerable flag")
        relevant = case.get("relevant_ids")
        displayed = case.get("results")
        if not (isinstance(relevant, list) and all(isinstance(x, str) for x in relevant)
                and isinstance(displayed, list)):
            raise ValueError("reviewed relevance ids and displayed results are required")
        if len(set(relevant)) != len(relevant):
            raise ValueError("duplicate relevance ids")
        if case["answerable"] and not relevant:
            raise ValueError("answerable case requires at least one labeled relevant id")
        if not case["answerable"] and relevant:
            raise ValueError("unanswerable case cannot have relevant ids")
        request = LiveDiscoveryInput.model_validate({
            **case["request"], "consent_remote_processing": True,
        })
        answerable_count += int(case["answerable"])
        absent_count += int(not case["answerable"])
        relevant_set = set(relevant)
        top_five_ids: list[str] = []
        for row in displayed:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("each displayed result needs a stable id")
            if len(top_five_ids) < 5:
                top_five_ids.append(row["id"])
            produced += 1
            if not (
                place_matches(str(row.get("city", "")), str(row.get("region", "")),
                              str(row.get("country", "")), request)
                and canonical_cuisine(str(row.get("cuisine", ""))) ==
                canonical_cuisine(request.cuisine)
            ):
                violations += 1
            cited += int(_safe_url(str(row.get("source_url", ""))) is not None)
        precision_sum += sum(item in relevant_set for item in top_five_ids)
        found_count += int(case["answerable"] and bool(relevant_set.intersection(top_five_ids)))
        abstention_count += int(not case["answerable"] and not displayed)
    return EvaluationSummary(
        cases=len(cases), answerable_cases=answerable_count,
        unanswerable_cases=absent_count, results=produced,
        precision_at_5=_fraction(precision_sum, len(cases) * 5),
        success_at_5_answerable=_fraction(found_count, answerable_count),
        correct_abstention_unanswerable=_fraction(abstention_count, absent_count),
        hard_constraint_violation_rate=_fraction(violations, produced),
        cited_url_coverage=_fraction(cited, produced),
    )
