"""Local, label-free operations for executing a frozen Savoroute OSM pilot.

Not part of the public Savoroute CLI. The underlying study and analysis
software remains unchanged. No relevance judgments or retrieval scores are
created by this script. All outputs are new files/directories, never overwrites.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from savoroute.evaluation.research import (
    MAX_JSON_BYTES,
    _validate_plan,
    audit_reviewer_progress,
)
from savoroute.evaluation.study import StudyError, verify_osm_study
from savoroute.services.storage import json_text

MAX_REPORT_BYTES = 16 * 1024 * 1024
_ZIP_DATE = (2020, 1, 1, 0, 0, 0)  # stable archives; no FS timestamps


class PilotError(ValueError):
    """Invalid, incomplete, or unsafe study operations request."""


def _json_file(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Any, bytes]:
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise PilotError(f"missing or oversized input: {path.name}")
    raw = path.read_bytes()
    try:
        return json.loads(raw), raw
    except (UnicodeDecodeError, ValueError) as exc:
        raise PilotError(f"invalid JSON: {path.name}") from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting existing outputs, including symlinks.
    with path.open("xb") as stream:
        stream.write(data)


def _plan_hash(study_dir: Path, plan_path: Path) -> str:
    plan, raw = _json_file(plan_path)
    try:
        return _validate_plan(study_dir, plan, raw)
    except (KeyError, TypeError, StudyError) as exc:
        raise PilotError("analysis plan failed frozen-study validation") from exc


def preflight(study_dir: Path, *, plan_path: Path | None = None) -> dict[str, Any]:
    """Inspect coverage/metadata gaps; produce no synthetic relevance labels."""
    manifest = verify_osm_study(study_dir)
    catalog, _ = _json_file(study_dir / "catalog.json")
    queries, _ = _json_file(study_dir / "queries.json")
    reference, _ = _json_file(study_dir / "review_reference.json")
    _, manifest_bytes = _json_file(study_dir / "manifest.json")
    if (not isinstance(reference, dict) or not isinstance(reference.get("records"), list)
            or not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list)):
        raise PilotError("unexpected catalog or reviewer-reference representation")
    items = catalog["items"]
    records = reference["records"]
    if len(records) != manifest["judgment_pairs"]:
        raise PilotError("reviewer reference and manifest disagree on pair count")
    item_ids = {item["item_id"] for item in items}
    if len(item_ids) != len(items) or any(row["item_id"] not in item_ids for row in records):
        raise PilotError("reviewer reference contains unknown or duplicate item IDs")
    per_case = Counter(row["case_id"] for row in records)
    missing_cuisine_by_case = Counter(
        row["case_id"] for row in records if not row.get("cuisines")
    )
    missing_description_by_case = Counter(
        row["case_id"] for row in records
        if not row.get("description")
        or row["description"] == "Restaurant entry from OpenStreetMap."
    )
    overview = []
    for query in queries["queries"]:
        case_id = query["case_id"]
        overview.append({
            "case_id": case_id,
            "split": query["split"],
            "eligible_pairs": per_case[case_id],
            "without_recorded_cuisine": missing_cuisine_by_case[case_id],
            "without_specific_description": missing_description_by_case[case_id],
        })
    if sum(row["eligible_pairs"] for row in overview) != len(records):
        raise PilotError("some reference pairs have no frozen query ID")
    missing_cuisine_items = sum(not item.get("cuisines") for item in items)
    result = {
        "pilot_preflight_version": 1,
        "study_manifest_sha256": _sha(manifest_bytes),
        "catalog_fingerprint": manifest["catalog_fingerprint"],
        "synthetic": manifest["synthetic"],
        "catalog_items": manifest["items"],
        "queries": manifest["queries"],
        "judgment_pairs": manifest["judgment_pairs"],
        "per_query": overview,
        "evidence_coverage": {
            "items_without_recorded_cuisine": missing_cuisine_items,
            "items_with_recorded_cuisine": len(items) - missing_cuisine_items,
            "pairs_without_recorded_cuisine": sum(missing_cuisine_by_case.values()),
        },
        "analysis_plan_sha256": _plan_hash(study_dir, plan_path) if plan_path else None,
        "evidence_warning": (
            "Missing OSM cuisine or descriptive metadata is unknown evidence, not a "
            "negative relevance judgment. If a pair cannot be judged from defensible "
            "evidence, do not force a binary decision; stop and revise/refreeze the protocol."
        ),
        "study_status": "awaiting_independent_human_judgments",
    }
    return result


def _zip_add(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


_INSTRUCTIONS = """# Independent Savoroute relevance review — {slot}

This is a blinded, frozen-collection assessment. You are reviewing the
RELEVANCE of the frozen catalog record to the query; you are NOT reviewing
real-world food safety, restaurant status, menus, or a user's visits.

1. Open `review_reference.json` and ONLY `{slot}.json` in the Savoroute
   local reviewer page (`/study-review`). The files remain in your browser.
2. Consider the query and the *frozen* item evidence. `source.json` provides
   the captured OSM snapshot. Do not rely on current webpages silently:
   businesses and tags can change after the acquisition date.
3. Record a `true` or `false` judgment per eligible pair, with a specific,
   source-grounded note for every positive. Keep notes brief, factual, and
   free of private information. Negative labels also need a defensible basis.
4. If evidence is insufficient, LEAVE THE LABEL NULL and report the issue to
   the study coordinator. Missing OSM cuisine/menu fields are NOT evidence
   of absence. The current binary benchmark cannot validly infer unknown as
   negative; the study must be revised and re-frozen if this is systematic.
5. Do not inspect Savoroute rankings, your peer's labels, the adjudicated
   workbook, or evaluation outputs. Never ask a language model to fill labels.
6. Save/export the completed sheet and submit only your own file to the
   coordinator through an agreed secure channel; keep the original unchanged.

The supplied checksum manifest establishes file identity but cannot prove
reviewer independence or factual correctness. This is a pilot with too few
queries to support generalization claims.
"""


def package_reviewers(study_dir: Path, plan_path: Path, output_dir: Path) -> dict[str, Any]:
    """Prepare two separate, deterministic blank reviewer ZIP archives."""
    pre = preflight(study_dir, plan_path=plan_path)
    if output_dir.exists():
        raise PilotError("output directory already exists; reviewer packages are immutable")
    # Only strictly enumerated frozen files. Never include other reviewer's sheet,
    # previously filled labels, ranking results, analysis reports, or secrets.
    shared = ("source.json", "catalog.json", "queries.json", "review_reference.json")
    blobs = {name: (study_dir / name).read_bytes() for name in shared}
    archives = {}
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        for slot in ("reviewer_a", "reviewer_b"):
            path = output_dir / f"{slot}.zip"
            with path.open("xb") as stream, zipfile.ZipFile(stream, "w") as archive:
                sources = {**blobs, f"{slot}.json": (study_dir / f"{slot}.json").read_bytes()}
                for name in sorted(sources):
                    _zip_add(archive, name, sources[name])
                cover = {
                    "review_package_version": 1,
                    "reviewer_slot": slot,
                    "study_manifest_sha256": pre["study_manifest_sha256"],
                    "analysis_plan_sha256": pre["analysis_plan_sha256"],
                    "files_sha256": {
                        name: _sha(payload) for name, payload in sorted(sources.items())
                    },
                    "attention": "No other reviewer sheets or model scores are included.",
                }
                _zip_add(archive, "package-manifest.json", json_text(cover).encode())
                _zip_add(archive, "INSTRUCTIONS.md", _INSTRUCTIONS.format(slot=slot).encode())
            archives[slot] = {"filename": path.name, "sha256": _sha(path.read_bytes())}
        index = {
            "reviewer_package_index_version": 1,
            "study_manifest_sha256": pre["study_manifest_sha256"],
            "analysis_plan_sha256": pre["analysis_plan_sha256"],
            "archives": archives,
            "distribution": "Send each reviewer only their respective ZIP; no public sharing.",
        }
        _write_new(output_dir / "package-index.json", json_text(index).encode())
    except BaseException:
        # Failed packaging must not leave a partial deliverable posing as complete.
        for path in output_dir.iterdir():
            if path.is_file():
                path.unlink()
        output_dir.rmdir()
        raise
    return index


def _number(value: Any) -> str:
    if value is None:
        return "not estimable"
    if type(value) not in (int, float):
        raise PilotError("invalid numerical estimate in evaluation report")
    return f"{value:.4f}"


def summarize_analysis(report: Any) -> str:
    """Descriptive Markdown from an already computed, adjudication-gated report.

    This command never computes a new retrieval metric or unlocks a test split.
    """
    if (not isinstance(report, dict) or report.get("analysis_version") != 1
            or report.get("bootstrap", {}).get("unit") != "query"):
        raise PilotError("expected a Savoroute v0.18 query-level analysis report")
    study = report.get("study_report", {})
    split = study.get("split")
    if split not in ("development", "test"):
        raise PilotError("analysis report has no recognized study split")
    metric_info = report.get("metrics")
    if not isinstance(metric_info, dict):
        raise PilotError("analysis report has no metrics")
    lines = [
        "# Savoroute Boston pilot — descriptive evaluation summary",
        "",
        f"**Partition:** {split}",
        f"**Analysis plan SHA-256:** `{report['analysis_plan_sha256']}`",
        f"**Frozen study SHA-256:** `{study['study_manifest_sha256']}`",
        "",
        "The following results describe the *fixed admitted OSM catalog* and this",
        "small set of reviewed queries. They are **not** population-level estimates",
        "of restaurant relevance, coverage, or user preference quality.",
        "",
        "| Metric | Query stratum (n) | BM25 | Overlap | BM25 − overlap [95% CI] |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    metrics = ("ndcg_at_k", "recall_at_k", "reciprocal_rank_at_k", "correct_empty")
    for name in metrics:
        entry = metric_info.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("systems"), dict):
            raise PilotError(f"invalid or missing metric in analysis report: {name}")
        paired = entry.get("bm25_minus_overlap")
        if not isinstance(paired, dict):
            raise PilotError(f"missing paired estimate: {name}")
        ci = paired.get("ci95")
        interval = (f"[{_number(ci[0])}, {_number(ci[1])}]" if isinstance(ci, list)
                    and len(ci) == 2 else "interval not estimable")
        lines.append(
            f"| {name} | {entry['query_population']} ({entry['n_queries']}) | "
            f"{_number(entry['systems']['bm25']['estimate'])} | "
            f"{_number(entry['systems']['overlap']['estimate'])} | "
            f"{_number(paired['estimate'])} {interval} |"
        )
    lines.extend(["", "## Failure categories (diagnostic counts, not significance tests)", ""])
    for method in ("bm25", "overlap"):
        counts = report.get("failure_counts", {}).get(method)
        if not isinstance(counts, dict):
            raise PilotError(f"missing failure counts for {method}")
        lines.append(f"**{method}:** " + (", ".join(
            f"{key}={counts[key]}" for key in sorted(counts)
        ) or "no recorded failures"))
        lines.append("")
    n_queries = study.get("query_count")
    if type(n_queries) is not int or n_queries < 1:
        raise PilotError("analysis report has invalid query count")
    lines.extend([
        "## Interpretation boundaries", "",
        "- The statistical unit is the query; query–restaurant pairs are dependent.",
        "- The confidence intervals do not include assessor or OSM uncertainty.",
        f"- This partition contains {n_queries} queries; intervals can be unstable at small n.",
        "- Baselines are fixed lexical BM25 and overlap; image/vector/geographic "
        "quality was not tested.",
        "- Unknown or absent OSM fields must not be represented as verified negatives.",
        "- Never claim preregistration without an independently timestamped protocol.",
        "- This summary comes from an existing analysis JSON; it does not verify "
        "human independence.",
        "",
        "## Next research decision", "",
        "Review per-query `query_errors` in the private JSON report, classify root causes,",
        "and design a larger independent query set **before** testing model changes.",
        "Only report differences supported by independent adjudication; disclose sampling",
        "and missing-evidence limitations alongside any numbers.", "",
    ])
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frozen Savoroute relevance-pilot operations; never creates labels"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("preflight", help="verify frozen study and audit metadata coverage")
    check.add_argument("--study-dir", type=Path, required=True)
    check.add_argument("--plan", type=Path)
    check.add_argument("--output", type=Path)
    pack = sub.add_parser("package-reviewers", help="make independent blinded reviewer ZIPs")
    pack.add_argument("--study-dir", type=Path, required=True)
    pack.add_argument("--plan", type=Path, required=True)
    pack.add_argument("--output-dir", type=Path, required=True)
    audit = sub.add_parser(
        "status", help="validate partial reviewer sheets; output aggregate counts"
    )
    audit.add_argument("--study-dir", type=Path, required=True)
    audit.add_argument("--reviewer-a", type=Path, required=True)
    audit.add_argument("--reviewer-b", type=Path, required=True)
    audit.add_argument("--output", type=Path)
    summary = sub.add_parser("summarize", help="render a completed Savoroute study analysis")
    summary.add_argument("--analysis", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args.study_dir, plan_path=args.plan)
            data = json_text(result).encode()
            if args.output:
                _write_new(args.output, data)
            print(data.decode())
        elif args.command == "package-reviewers":
            print(json_text(package_reviewers(args.study_dir, args.plan, args.output_dir)))
        elif args.command == "status":
            result = audit_reviewer_progress(args.study_dir, args.reviewer_a, args.reviewer_b)
            # It only gives aggregate counts and file hashes. Do NOT send peer
            # counts or conflicts to reviewers while independent assessment runs.
            data = json_text(result).encode()
            if args.output:
                _write_new(args.output, data)
            print(data.decode())
        else:
            report, _ = _json_file(args.analysis, max_bytes=MAX_REPORT_BYTES)
            _write_new(args.output, summarize_analysis(report).encode())
            print(f"Saved descriptive report: {args.output}")
        return 0
    except (OSError, PilotError, StudyError, KeyError, TypeError, ValueError) as exc:
        print(f"Study operations error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
