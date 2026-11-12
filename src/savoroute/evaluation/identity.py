"""Evaluate review-candidate generation against explicitly annotated record pairs."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from savoroute.identity.matching import MatchRecord, is_review_candidate
from savoroute.ingestion.sources import IngestionError

MAX_BENCHMARK_RECORDS = 1000
MAX_ANNOTATED_PAIRS = 10000


@dataclass(frozen=True, slots=True)
class IdentityPair:
    left_id: str
    right_id: str
    same_entity: bool


@dataclass(frozen=True, slots=True)
class IdentityBenchmark:
    name: str
    synthetic: bool
    annotation_provenance: str
    records: dict[str, MatchRecord]
    pairs: tuple[IdentityPair, ...]


@dataclass(frozen=True, slots=True)
class IdentityEvaluation:
    name: str
    synthetic: bool
    pairs: int
    positives: int
    negatives: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    false_positive_pairs: tuple[tuple[str, str], ...]
    false_negative_pairs: tuple[tuple[str, str], ...]

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        # Direct contingency-table definition; well-defined when positives
        # exist but no candidates were predicted (F1 = 0).
        denominator = 2 * self.true_positive + self.false_positive + self.false_negative
        return 2 * self.true_positive / denominator if denominator else None

    @property
    def review_rate(self) -> float:
        return (self.true_positive + self.false_positive) / self.pairs

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.name, "synthetic": self.synthetic,
            "pairs": self.pairs, "positives": self.positives, "negatives": self.negatives,
            "tp": self.true_positive, "fp": self.false_positive,
            "fn": self.false_negative, "tn": self.true_negative,
            "precision": self.precision, "recall": self.recall,
            "f1": self.f1, "review_rate": self.review_rate,
            "false_positive_pairs": [list(pair) for pair in self.false_positive_pairs],
            "false_negative_pairs": [list(pair) for pair in self.false_negative_pairs],
        }


def _object(raw: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != keys:
        raise IngestionError(f"{label} must contain exactly {sorted(keys)}")
    return raw


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 256) or value != value.strip():
        raise IngestionError(f"{label} must be a trimmed string (1–256 characters)")
    if not allow_empty and not value:
        raise IngestionError(f"{label} cannot be empty")
    return value


def parse_identity_benchmark(payload: Any) -> IdentityBenchmark:
    """Validate an independent, complete pair annotation set; no inferred labels."""
    obj = _object(payload, {"schema_version", "dataset", "records", "pairs"}, "benchmark")
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise IngestionError("identity benchmark schema_version must be 1")
    dataset = _object(obj["dataset"], {"name", "synthetic", "annotation_provenance"},
                      "dataset")
    name = _text(dataset["name"], "dataset.name")
    provenance = _text(dataset["annotation_provenance"], "dataset.annotation_provenance")
    if type(dataset["synthetic"]) is not bool:
        raise IngestionError("dataset.synthetic must be a boolean")
    entries = obj["records"]
    pairs = obj["pairs"]
    if not isinstance(entries, list) or not 2 <= len(entries) <= MAX_BENCHMARK_RECORDS:
        raise IngestionError("records must contain 2–1000 records")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_ANNOTATED_PAIRS:
        raise IngestionError("pairs must contain 1–10000 annotations")
    records: dict[str, MatchRecord] = {}
    for index, raw in enumerate(entries):
        row = _object(raw, {"record_id", "name", "address", "latitude", "longitude"},
                      f"records[{index}]")
        record_id = _text(row["record_id"], "record_id")
        if record_id in records:
            raise IngestionError(f"duplicate record_id {record_id}")
        title = _text(row["name"], "record.name")
        address = row["address"]
        if address is not None:
            address = _text(address, "record.address")
        lat, lon = row["latitude"], row["longitude"]
        if (lat is None) != (lon is None):
            raise IngestionError("record coordinates must be both present or both null")
        if lat is not None and (
            type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
        ):
            raise IngestionError("record coordinates are invalid")
        records[record_id] = MatchRecord(title, address, lat, lon)
    annotated: list[IdentityPair] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, raw in enumerate(pairs):
        row = _object(raw, {"left_id", "right_id", "same_entity"}, f"pairs[{index}]")
        left, right = row["left_id"], row["right_id"]
        if not isinstance(left, str) or not isinstance(right, str):
            raise IngestionError("pair IDs must be strings")
        if left not in records or right not in records or left == right:
            raise IngestionError("pair must contain distinct, known record IDs")
        key = tuple(sorted((left, right)))
        if key in seen_pairs:
            raise IngestionError("duplicate annotated pair (including reversed order)")
        seen_pairs.add(key)
        if type(row["same_entity"]) is not bool:
            raise IngestionError("same_entity requires an explicit boolean annotation")
        annotated.append(IdentityPair(left, right, row["same_entity"]))
    return IdentityBenchmark(name, dataset["synthetic"], provenance, records,
                             tuple(annotated))


def load_identity_benchmark(path: str | Path) -> IdentityBenchmark:
    try:
        return parse_identity_benchmark(json.loads(Path(path).read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise IngestionError("identity benchmark is not valid JSON") from exc


def evaluate_identity_candidates(benchmark: IdentityBenchmark) -> IdentityEvaluation:
    tp = fp = fn = tn = 0
    false_positives: list[tuple[str, str]] = []
    false_negatives: list[tuple[str, str]] = []
    for pair in benchmark.pairs:
        predicted = is_review_candidate(benchmark.records[pair.left_id],
                                        benchmark.records[pair.right_id])
        key = (pair.left_id, pair.right_id)
        if predicted and pair.same_entity:
            tp += 1
        elif predicted and not pair.same_entity:
            fp += 1
            false_positives.append(key)
        elif not predicted and pair.same_entity:
            fn += 1
            false_negatives.append(key)
        else:
            tn += 1
    return IdentityEvaluation(
        benchmark.name, benchmark.synthetic, len(benchmark.pairs), tp + fn, fp + tn,
        tp, fp, fn, tn, tuple(false_positives), tuple(false_negatives),
    )
