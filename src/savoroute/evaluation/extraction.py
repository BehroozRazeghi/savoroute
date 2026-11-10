"""Attribute-level exact-match evaluation against independently annotated source records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIELDS = ("title", "description", "cuisines", "dietary_tags", "ingredients", "location", "price_tier")
MULTI = frozenset(("cuisines", "dietary_tags", "ingredients"))


class AnnotationError(ValueError):
    """Invalid ground truth, prediction schema, or record identities."""


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _annotations(row: Any, *, context: str) -> dict[str, frozenset[str]]:
    if not isinstance(row, dict) or set(row) != set(FIELDS):
        raise AnnotationError(f"{context}: fields must be exactly {FIELDS}")
    result: dict[str, frozenset[str]] = {}
    for field in FIELDS:
        value = row[field]
        if field in MULTI:
            if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                raise AnnotationError(f"{context}.{field} must be an array of nonempty strings")
            tokens = [_norm(x) for x in value]
        elif value is None:
            if field in {"title", "description"}:
                raise AnnotationError(f"{context}.{field} cannot be null")
            tokens = []
        elif field == "price_tier":
            if type(value) is not int or not 1 <= value <= 4:
                raise AnnotationError(f"{context}.price_tier must be integer 1..4 or null")
            tokens = [str(value)]
        else:
            if not isinstance(value, str) or not value.strip():
                raise AnnotationError(f"{context}.{field} must be nonempty string or null")
            tokens = [_norm(value)]
        if len(set(tokens)) != len(tokens):
            raise AnnotationError(f"{context}.{field} has duplicate values")
        result[field] = frozenset(tokens)
    return result


def parse_gold(payload: Any) -> tuple[str, dict[str, dict[str, frozenset[str]]]]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "dataset", "records"}:
        raise AnnotationError("gold requires schema_version, dataset, records")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise AnnotationError("gold.schema_version must equal 1")
    if not isinstance(payload["dataset"], str) or not payload["dataset"].strip():
        raise AnnotationError("gold.dataset must be nonempty string")
    if not isinstance(payload["records"], list) or not payload["records"]:
        raise AnnotationError("gold.records must be a nonempty array")
    parsed = {}
    for index, row in enumerate(payload["records"]):
        if not isinstance(row, dict) or set(row) != {"source_id", "fields"}:
            raise AnnotationError(f"gold.records[{index}]: requires source_id and fields")
        source_id = row["source_id"]
        if not isinstance(source_id, str) or not source_id.strip() or source_id in parsed:
            raise AnnotationError("gold.source_id must be unique, nonempty string")
        parsed[source_id] = _annotations(row["fields"], context=source_id)
    return payload["dataset"], parsed


def parse_predictions(payload: Any, *, dataset: str) -> dict[str, dict[str, frozenset[str]]]:
    if not isinstance(payload, dict) or payload.get("provenance_schema_version") != 1:
        raise AnnotationError("predictions must be a schema-v1 ingestion provenance report")
    if payload.get("source_dataset") != dataset:
        raise AnnotationError("prediction source_dataset does not match gold.dataset")
    if not isinstance(payload.get("records"), list):
        raise AnnotationError("predictions.records must be an array")
    result = {}
    for row in payload["records"]:
        if not isinstance(row, dict) or not isinstance(row.get("source_id"), str):
            raise AnnotationError("predictions record requires source_id")
        source_id = row["source_id"]
        if source_id in result:
            raise AnnotationError(f"duplicate prediction source_id {source_id}")
        evidence = row.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != set(FIELDS):
            raise AnnotationError(f"predictions[{source_id}].evidence has invalid fields")
        fields = {}
        for field in FIELDS:
            entries = evidence[field]
            if not isinstance(entries, list) or (field not in MULTI and len(entries) > 1):
                raise AnnotationError(f"predictions[{source_id}].{field} invalid entries")
            if any(not isinstance(entry, dict) or "value" not in entry for entry in entries):
                raise AnnotationError(f"predictions[{source_id}].{field} missing value")
            fields[field] = [entry["value"] for entry in entries] if field in MULTI else (
                entries[0]["value"] if entries else None
            )
        result[source_id] = _annotations(fields, context=source_id)
    return result


@dataclass(frozen=True, slots=True)
class FieldScore:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float | None:
        total = self.true_positive + self.false_positive
        return self.true_positive / total if total else None

    @property
    def recall(self) -> float | None:
        total = self.true_positive + self.false_negative
        return self.true_positive / total if total else None

    @property
    def f1(self) -> float | None:
        denominator = 2 * self.true_positive + self.false_positive + self.false_negative
        return 2 * self.true_positive / denominator if denominator else None

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "tp": self.true_positive, "fp": self.false_positive, "fn": self.false_negative,
            "precision": self.precision, "recall": self.recall, "f1": self.f1,
        }


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    gold_records: int
    predicted_records: int
    exact_records: int
    fields: dict[str, FieldScore]
    errors: dict[str, list[str]]

    @property
    def micro(self) -> FieldScore:
        return FieldScore(
            sum(x.true_positive for x in self.fields.values()),
            sum(x.false_positive for x in self.fields.values()),
            sum(x.false_negative for x in self.fields.values()),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "gold_records": self.gold_records,
            "predicted_records": self.predicted_records,
            "exact_records": self.exact_records,
            "record_exact_match_rate": self.exact_records / self.gold_records,
            "micro": self.micro.as_dict(),
            "fields": {key: value.as_dict() for key, value in self.fields.items()},
            "errors": self.errors,
        }


def evaluate_extraction(gold_payload: Any, prediction_payload: Any) -> ExtractionSummary:
    """Exact-match TP/FP/FN over field values; missing predictions count as FN.

    Normalization is limited to Unicode case folding and whitespace. No semantic
    equivalence is assumed; ambiguous annotations require human review.
    """
    dataset, gold = parse_gold(gold_payload)
    predictions = parse_predictions(prediction_payload, dataset=dataset)
    unexpected = set(predictions) - set(gold)
    if unexpected:
        raise AnnotationError(f"prediction source IDs absent from gold: {sorted(unexpected)}")
    counts = {field: [0, 0, 0] for field in FIELDS}
    errors: dict[str, list[str]] = {}
    exact_records = 0
    for source_id, annotated in gold.items():
        predicted = predictions.get(source_id, {field: frozenset() for field in FIELDS})
        wrong = []
        for field in FIELDS:
            tp = len(annotated[field] & predicted[field])
            fp = len(predicted[field] - annotated[field])
            fn = len(annotated[field] - predicted[field])
            counts[field][0] += tp
            counts[field][1] += fp
            counts[field][2] += fn
            if fp or fn:
                wrong.append(field)
        if wrong:
            errors[source_id] = wrong
        else:
            exact_records += 1
    return ExtractionSummary(
        len(gold), len(predictions), exact_records,
        {field: FieldScore(*counts[field]) for field in FIELDS}, errors,
    )


def load_gold(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    parse_gold(payload)
    return payload
