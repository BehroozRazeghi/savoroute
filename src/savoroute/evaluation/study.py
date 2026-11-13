"""Frozen OSM study snapshots and provenance-bound retrieval evaluation.

This module does not collect queries, assign relevance, or verify that a human
reviewer is independent. A study becomes evaluable only after the established
relevance-review workflow has produced a complete adjudicated workbook.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.evaluation.annotations import (
    finalize_relevance_workbook,
    load_query_set,
    prepare_relevance_workbook,
    split_reviewer_sheets,
)
from savoroute.evaluation.retrieval import evaluate_search
from savoroute.ingestion.osm import import_osm_snapshot, parse_osm_elements
from savoroute.retrieval.vector import catalog_fingerprint
from savoroute.services.storage import json_text, write_json_file

STUDY_FILES = (
    "source.json", "catalog.json", "queries.json", "review_template.json",
    "reviewer_a.json", "reviewer_b.json", "review_reference.json",
)
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024


class StudyError(ValueError):
    """Malformed, modified, or insufficiently documented evaluation study."""


def _read_limited(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.stat().st_size > limit:
        raise StudyError(f"missing or oversized study input: {path.name}")
    return path.read_bytes()


def _json_bytes(payload: Any) -> bytes:
    return json_text(payload).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise StudyError(f"{name} must be a nonempty description (at most 2000 characters)")
    return value.strip()


def _query_signature(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _check_query_leakage(queries: list[dict[str, Any]]) -> None:
    observed: dict[str, str] = {}
    for row in queries:
        signature = _query_signature(row["query"])
        if not signature:
            raise StudyError(f"query contains no searchable text: {row['case_id']}")
        if signature in observed:
            raise StudyError(
                f"duplicate normalized query in {row['case_id']} and {observed[signature]}"
            )
        observed[signature] = row["case_id"]


def _load_snapshot(path: Path) -> tuple[Any, bytes]:
    raw = _read_limited(path, MAX_SOURCE_BYTES)
    try:
        payload = json.loads(raw)
        parse_osm_elements(payload)
    except ValueError as exc:
        raise StudyError("invalid OSM source snapshot") from exc
    return payload, raw


def prepare_osm_study(
    *,
    source_path: str | Path,
    catalog_path: str | Path,
    queries_path: str | Path,
    output_dir: str | Path,
    collected_at: str,
    selection_protocol: str,
    query_protocol: str,
    max_pairs: int = 20_000,
    allow_synthetic_fixture: bool = False,
) -> dict[str, Any]:
    """Publish an immutable-by-convention, checksum-verified small-catalog study.

    A real study requires a non-fixture OSM snapshot and the exact catalog
    derived from it. This is a reproducibility check, not proof that source
    metadata or the researchers' collection protocol is truthful.
    """
    try:
        stamp = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise StudyError("collected_at must be an ISO-8601 UTC timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise StudyError("collected_at must use UTC")
    collected_at = stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    selection_protocol = _text(selection_protocol, "selection_protocol")
    query_protocol = _text(query_protocol, "query_protocol")
    snapshot, raw_snapshot = _load_snapshot(Path(source_path))
    catalog = load_catalog(catalog_path)
    synthetic_fixture = snapshot.get("savoroute_fixture") is True
    if (synthetic_fixture or catalog.synthetic) and not allow_synthetic_fixture:
        raise StudyError("fictional datasets are not eligible for real-data studies")
    if catalog.synthetic != synthetic_fixture:
        raise StudyError("catalog and snapshot synthetic flags disagree")
    imported = import_osm_snapshot(
        snapshot, dataset_name=catalog.dataset_name, synthetic_fixture=synthetic_fixture,
    )
    expected = imported.catalog
    if catalog_fingerprint(expected) != catalog_fingerprint(catalog):
        raise StudyError("catalog does not match deterministic import of OSM snapshot")
    if not catalog.items:
        raise StudyError("study catalog contains no admitted restaurants")
    query_set = load_query_set(queries_path)
    _check_query_leakage(query_set["queries"])
    template = prepare_relevance_workbook(catalog, query_set, max_pairs=max_pairs)
    if not template["judgments"]:
        raise StudyError("study has no eligible query-item judgments")
    reviewer_a, reviewer_b = split_reviewer_sheets(catalog, template)
    items = {item.item_id: item for item in catalog.items}
    query_texts = {row["case_id"]: row["query"] for row in query_set["queries"]}
    reference = {
        "reference_version": 1,
        "records": [
            {
                "case_id": row["case_id"],
                "query": query_texts[row["case_id"]],
                "item_id": row["item_id"],
                "title": items[row["item_id"]].title,
                "description": items[row["item_id"]].description,
                "cuisines": list(items[row["item_id"]].cuisines),
                "location": items[row["item_id"]].location,
                "source_url": items[row["item_id"]].source_url,
            }
            for row in template["judgments"]
        ],
    }
    documents = {
        "source.json": raw_snapshot,
        "catalog.json": _json_bytes(catalog_to_dict(catalog)),
        "queries.json": _json_bytes(query_set),
        "review_template.json": _json_bytes(template),
        "reviewer_a.json": _json_bytes(reviewer_a),
        "reviewer_b.json": _json_bytes(reviewer_b),
        "review_reference.json": _json_bytes(reference),
    }
    for name, data in documents.items():
        size_limit = MAX_SOURCE_BYTES if name == "source.json" else MAX_JSON_BYTES
        if len(data) > size_limit:
            raise StudyError(f"frozen study file exceeds size limit: {name}")
    manifest = {
        "study_version": 1,
        "study_state": "awaiting_independent_review",
        "dataset_name": catalog.dataset_name,
        "synthetic": catalog.synthetic,
        "source": {
            "provider": "OpenStreetMap",
            "license": "ODbL-1.0",
            "attribution": "© OpenStreetMap contributors",
            "license_url": "https://www.openstreetmap.org/copyright",
            "collected_at_utc": collected_at,
            "selection_protocol": selection_protocol,
        },
        "query_protocol": query_protocol,
        "catalog_fingerprint": catalog_fingerprint(catalog),
        "items": len(catalog.items),
        "queries": len(query_set["queries"]),
        "development_queries": sum(
            row["split"] == "development" for row in query_set["queries"]
        ),
        "test_queries": sum(row["split"] == "test" for row in query_set["queries"]),
        "judgment_pairs": len(template["judgments"]),
        "review_scope": "exhaustive_filtered_catalog",
        "source_decisions": {
            category: sum(row.status == category for row in imported.decisions)
            for category in ("admitted", "review", "skipped", "already_imported")
        },
        "files": {name: _sha(content) for name, content in documents.items()},
    }
    root = Path(output_dir)
    if root.exists():
        raise StudyError("study directory already exists; snapshots cannot be overwritten")
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".savoroute-study-", dir=root.parent))
    try:
        for name, data in documents.items():
            (temporary / name).write_bytes(data)
        (temporary / "manifest.json").write_bytes(_json_bytes(manifest))
        temporary.rename(root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def verify_osm_study(directory: str | Path) -> dict[str, Any]:
    """Verify every bundle hash, provenance binding, query split, and review template."""
    root = Path(directory)
    try:
        manifest = json.loads(_read_limited(root / "manifest.json", MAX_JSON_BYTES))
    except ValueError as exc:
        raise StudyError("invalid study manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("study_version") != 1:
        raise StudyError("unsupported study manifest")
    if set(manifest.get("files", {})) != set(STUDY_FILES):
        raise StudyError("manifest file list is incomplete or unexpected")
    files = {}
    for name in STUDY_FILES:
        raw = _read_limited(root / name, MAX_SOURCE_BYTES if name == "source.json" else MAX_JSON_BYTES)
        if _sha(raw) != manifest["files"][name]:
            raise StudyError(f"study file modified: {name}")
        try:
            files[name] = json.loads(raw)
        except ValueError as exc:
            raise StudyError(f"invalid JSON in study file: {name}") from exc
    catalog = load_catalog(root / "catalog.json")
    snapshot = files["source.json"]
    synthetic_fixture = snapshot.get("savoroute_fixture") is True
    if synthetic_fixture != catalog.synthetic or manifest.get("synthetic") != catalog.synthetic:
        raise StudyError("source/catalog synthetic indicators disagree")
    imported = import_osm_snapshot(
        snapshot, dataset_name=catalog.dataset_name, synthetic_fixture=synthetic_fixture,
    )
    # Frozen study v1 catalogs predate optional geography fields. Historical
    # provenance must remain verifiable without changing any frozen file or
    # permitting mismatches in the original fields. A legacy comparison is
    # permitted only when the frozen catalog has no geography keys at all.
    source_fingerprint = catalog_fingerprint(imported.catalog)
    frozen_fingerprint = catalog_fingerprint(catalog)
    geo_keys = {"raw_address", "city", "region", "country", "city_id",
                "latitude", "longitude", "city_source"}
    legacy = all(not geo_keys.intersection(item) for item in files["catalog.json"]["items"])
    if source_fingerprint != frozen_fingerprint and legacy:
        stripped = replace(imported.catalog, items=tuple(replace(
            item, raw_address=None, city=None, region=None, country=None,
            city_id=None, latitude=None, longitude=None, city_source=None,
        ) for item in imported.catalog.items))
        source_fingerprint = catalog_fingerprint(stripped)
    if (source_fingerprint != frozen_fingerprint
            or manifest.get("catalog_fingerprint") != frozen_fingerprint):
        raise StudyError("catalog provenance does not match original OSM snapshot")
    source_decisions = {
        category: sum(row.status == category for row in imported.decisions)
        for category in ("admitted", "review", "skipped", "already_imported")
    }
    if manifest.get("source_decisions") != source_decisions:
        raise StudyError("record decision counts do not match OSM import")
    query_set = load_query_set(root / "queries.json")
    _check_query_leakage(query_set["queries"])
    frozen_template = files["review_template.json"]
    if not isinstance(frozen_template, dict) or not isinstance(
        frozen_template.get("judgments"), list
    ):
        raise StudyError("invalid review template")
    prepared = prepare_relevance_workbook(
        catalog, query_set, max_pairs=max(1, len(frozen_template["judgments"])),
    )
    if prepared != files["review_template.json"]:
        raise StudyError("review template does not match frozen catalog and queries")
    a, b = split_reviewer_sheets(catalog, prepared)
    if (a != files["reviewer_a.json"] or b != files["reviewer_b.json"]):
        raise StudyError("reviewer sheets differ from original blank templates")
    items = {item.item_id: item for item in catalog.items}
    queries_by_id = {row["case_id"]: row["query"] for row in query_set["queries"]}
    expected_reference = {
        "reference_version": 1,
        "records": [
            {
                "case_id": row["case_id"], "query": queries_by_id[row["case_id"]],
                "item_id": row["item_id"], "title": items[row["item_id"]].title,
                "description": items[row["item_id"]].description,
                "cuisines": list(items[row["item_id"]].cuisines),
                "location": items[row["item_id"]].location,
                "source_url": items[row["item_id"]].source_url,
            }
            for row in prepared["judgments"]
        ],
    }
    if files["review_reference.json"] != expected_reference:
        raise StudyError("review reference does not match frozen query/item data")
    if (manifest.get("items") != len(catalog.items)
            or manifest.get("queries") != len(query_set["queries"])
            or manifest.get("judgment_pairs") != len(prepared["judgments"])):
        raise StudyError("study manifest counts do not match source files")
    return manifest


def evaluate_reviewed_study(
    directory: str | Path,
    workbook_path: str | Path,
    *,
    split: Literal["development", "test"] = "development",
    at_k: int = 5,
    allow_test: bool = False,
) -> dict[str, Any]:
    """Evaluate two frozen lexical baselines against complete reviewed judgments.

    Test evaluation requires explicit opt-in to reduce accidental test reuse;
    software cannot verify that hyperparameters were frozen before evaluation.
    """
    if split not in ("development", "test"):
        raise StudyError("split must be development or test")
    if split == "test" and not allow_test:
        raise StudyError("test evaluation requires explicit allow_test=True")
    if type(at_k) is not int or not 1 <= at_k <= 1000:
        raise StudyError("at_k must be an integer in [1, 1000]")
    manifest = verify_osm_study(directory)
    root = Path(directory)
    catalog = load_catalog(root / "catalog.json")
    raw = _read_limited(Path(workbook_path), MAX_JSON_BYTES)
    try:
        workbook = json.loads(raw)
    except ValueError as exc:
        raise StudyError("invalid adjudicated workbook") from exc
    if (not isinstance(workbook, dict)
            or workbook.get("queries") != load_query_set(root / "queries.json")["queries"]):
        raise StudyError("reviewed workbook queries differ from the frozen study")
    dev, test, audit = finalize_relevance_workbook(catalog, workbook)
    judgments = dev if split == "development" else test
    from savoroute.evaluation.retrieval import parse_benchmark

    queries = parse_benchmark(judgments)
    outcomes = {}
    for method in ("bm25", "overlap"):
        summary = evaluate_search(catalog.items, queries, at_k=at_k, method=method)
        outcomes[method] = {
            **summary.as_dict(),
            "cases": [
                {
                    "case_id": case.case_id,
                    "retrieved_item_ids": list(case.retrieved_item_ids),
                    "recall_at_k": case.recall_at_k,
                    "reciprocal_rank_at_k": case.reciprocal_rank_at_k,
                    "ndcg_at_k": case.ndcg_at_k,
                    "correct_empty": case.correct_empty,
                }
                for case in summary.cases
            ],
        }
    return {
        "report_version": 1,
        "study_manifest_sha256": _sha(_read_limited(root / "manifest.json", MAX_JSON_BYTES)),
        "catalog_fingerprint": manifest["catalog_fingerprint"],
        "reviewed_workbook_sha256": _sha(raw),
        "annotation_audit": audit,
        "split": split,
        "at_k": at_k,
        "query_count": len(queries),
        "systems": outcomes,
        "limitations": (
            "Judgments are reviewer supplied; independent review and source accuracy "
            "cannot be authenticated by this software. No-match queries are reported "
            "separately. Do not tune parameters using held-out test outcomes."
        ),
    }


def write_study_report(report: dict[str, Any], path: str | Path) -> None:
    write_json_file(report, path)
