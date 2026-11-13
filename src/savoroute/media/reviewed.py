"""Rights-reviewed local image packaging, with no remote fetching.

Explicit reviewer-approved *references* are paired with selected local bytes.
Rights are recorded human assertions, not independent legal verification.
Outputs are immutable per bundle and never modify the canonical catalog.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from savoroute.domain.models import Catalog
from savoroute.evidence.review import catalog_digest, load_evidence_bundle
from savoroute.media.ingestion import _image_bytes

_MAX_MANIFEST = 128_000
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_MAX_ASSETS = 32
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CLAIM = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_ASSET = re.compile(r"img_[0-9a-f]{24}\Z")


class ReviewedMediaError(ValueError):
    """Unapproved rights, unsafe file, stale binding or invalid media bundle."""


def _bounded_json(path: Path, maximum: int) -> Any:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum:
        raise ReviewedMediaError("manifest missing, symlinked, or exceeds size limit")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReviewedMediaError("manifest must be UTF-8 JSON") from exc


def _canonical_hash(data: Any) -> str:
    value = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _relative(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 256 or not value:
        raise ReviewedMediaError("image path must be a short relative POSIX path")
    pure = PurePosixPath(value)
    if (pure.is_absolute() or ".." in pure.parts or "." in pure.parts
            or "\\" in value or ":" in value or value.startswith("~")):
        raise ReviewedMediaError("image path must be confined to manifest directory")
    return value


def _allowed_source(root: Path, relative: str) -> Path:
    source = root / relative
    if source.is_symlink() or not source.exists():
        raise ReviewedMediaError("local image not found or symlinked")
    resolved = source.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ReviewedMediaError("local image must remain within manifest directory")
    return resolved


def package_reviewed_media(
    catalog: Catalog, evidence_path: str | Path, manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Atomically create a content-verified PNG bundle from approved local files.

    Manifest: {schema_version:1, catalog_digest, assets:[{claim_id,path,sha256}]}.
    Paths are relative to the manifest, hashes describe the original local bytes.
    """
    evidence = load_evidence_bundle(evidence_path, catalog)
    path = Path(manifest_path)
    sources = _bounded_json(path, _MAX_MANIFEST)
    if (not isinstance(sources, dict) or set(sources) !=
            {"schema_version", "catalog_digest", "assets"}
            or type(sources["schema_version"]) is not int or sources["schema_version"] != 1
            or sources["catalog_digest"] != catalog_digest(catalog)):
        raise ReviewedMediaError("source manifest schema or catalog digest differs")
    entries = sources["assets"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_ASSETS:
        raise ReviewedMediaError("source manifest requires 1..32 images")
    approved = {row["claim_id"]: row for row in evidence["claims"] if row["kind"] == "image_url"}
    output_assets = []
    payloads: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    content_hashes: set[str] = set()
    total = 0
    root = path.resolve().parent
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"claim_id", "path", "sha256"}:
            raise ReviewedMediaError("asset entry must include claim_id, path, sha256")
        claim_id, expected_sha = entry["claim_id"], entry["sha256"]
        if (not isinstance(claim_id, str) or not _CLAIM.fullmatch(claim_id)
                or claim_id in seen or claim_id not in approved):
            raise ReviewedMediaError("asset must reference a unique approved image claim")
        if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
            raise ReviewedMediaError("expected image SHA256 must be lowercase hex")
        seen.add(claim_id)
        source = _allowed_source(root, _relative(entry["path"]))
        if source.stat().st_size > 15 * 1024 * 1024:
            raise ReviewedMediaError("input image exceeds 15 MiB")
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ReviewedMediaError("input SHA256 differs from reviewed manifest")
        try:
            normalized, width, height, _fmt = _image_bytes(source)
        except (ValueError, OSError) as exc:
            raise ReviewedMediaError("image is not a supported, safely decodable still") from exc
        normalized_sha = hashlib.sha256(normalized).hexdigest()
        if normalized_sha in content_hashes:
            raise ReviewedMediaError("duplicate normalized image content")
        content_hashes.add(normalized_sha)
        total += len(normalized)
        if total > _MAX_OUTPUT_BYTES:
            raise ReviewedMediaError("normalized bundle exceeds 64 MiB")
        claim = approved[claim_id]
        identifier = "img_" + hashlib.sha256((claim_id + normalized_sha).encode()).hexdigest()[:24]
        filename = f"assets/{identifier}.png"
        payloads.append((filename, normalized))
        output_assets.append({
            "asset_id": identifier, "claim_id": claim_id, "item_id": claim["item_id"],
            "input_sha256": expected_sha,
            "modifications": "EXIF orientation applied; RGB PNG conversion; resized as needed; metadata removed",
            "file": filename, "sha256": normalized_sha, "width": width, "height": height,
            "license": claim["license"], "attribution": claim["attribution"],
            "source_url": claim["source_url"], "image_reference_url": claim["value"],
            "observed_on": claim["observed_on"], "reviewed_on": claim["review"]["reviewed_on"],
        })
    bundle = {"schema_version": 1, "catalog_digest": catalog_digest(catalog),
              "evidence_digest": _canonical_hash(evidence), "assets": output_assets}
    dest = Path(output_dir).resolve()
    if dest.exists():
        raise ReviewedMediaError("output directory already exists; refusing to overwrite")
    if not dest.parent.is_dir():
        raise ReviewedMediaError("output parent directory must already exist")
    temp = Path(tempfile.mkdtemp(prefix=".savoroute-media-", dir=dest.parent))
    try:
        (temp / "assets").mkdir()
        for name, data in payloads:
            (temp / name).write_bytes(data)
        (temp / "manifest.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        temp.rename(dest)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return bundle


def load_reviewed_media(
    directory: str | Path, catalog: Catalog, evidence: dict[str, Any]
) -> dict[str, Any]:
    """Re-verify every local image against its approved, immutable review evidence."""
    root = Path(directory).resolve(strict=True)
    bundle = _bounded_json(root / "manifest.json", _MAX_MANIFEST)
    if (not isinstance(bundle, dict) or set(bundle) !=
            {"schema_version", "catalog_digest", "evidence_digest", "assets"}
            or type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1
            or bundle["catalog_digest"] != catalog_digest(catalog)
            or bundle["evidence_digest"] != _canonical_hash(evidence)):
        raise ReviewedMediaError("media bundle is stale or does not match approved evidence")
    approved = {claim["claim_id"]: claim for claim in evidence["claims"]
                if claim["kind"] == "image_url"}
    assets = bundle["assets"]
    if not isinstance(assets, list) or not 1 <= len(assets) <= _MAX_ASSETS:
        raise ReviewedMediaError("invalid media bundle asset count")
    seen: set[str] = set()
    for entry in assets:
        if not isinstance(entry, dict) or set(entry) != {
            "asset_id", "claim_id", "item_id", "file", "sha256", "width", "height",
            "input_sha256", "modifications",
            "license", "attribution", "source_url", "image_reference_url",
            "observed_on", "reviewed_on",
        }:
            raise ReviewedMediaError("invalid media bundle asset metadata")
        asset_id, claim_id = entry["asset_id"], entry["claim_id"]
        if (not isinstance(asset_id, str) or not _ASSET.fullmatch(asset_id)
                or asset_id in seen or claim_id not in approved):
            raise ReviewedMediaError("unexpected asset identity or approval")
        seen.add(asset_id)
        claim = approved[claim_id]
        if any(entry[field] != value for field, value in {
            "item_id": claim["item_id"], "license": claim["license"],
            "attribution": claim["attribution"], "source_url": claim["source_url"],
            "image_reference_url": claim["value"], "observed_on": claim["observed_on"],
            "reviewed_on": claim["review"]["reviewed_on"],
        }.items()):
            raise ReviewedMediaError("published metadata diverges from approved image claim")
        if (not isinstance(entry["input_sha256"], str) or not _SHA.fullmatch(entry["input_sha256"])
                or entry["modifications"] != "EXIF orientation applied; RGB PNG conversion; resized as needed; metadata removed"):
            raise ReviewedMediaError("invalid input provenance or image modification declaration")
        if (entry["file"] != f"assets/{asset_id}.png"
                or not isinstance(entry["sha256"], str) or not _SHA.fullmatch(entry["sha256"])):
            raise ReviewedMediaError("invalid asset path or image digest")
        if (type(entry["width"]) is not int or type(entry["height"]) is not int
                or not 1 <= entry["width"] <= 1280 or not 1 <= entry["height"] <= 1280):
            raise ReviewedMediaError("invalid normalized image dimensions")
        file = root / entry["file"]
        if file.is_symlink() or not file.is_file() or file.stat().st_size > _MAX_OUTPUT_BYTES:
            raise ReviewedMediaError("media file is absent, symlinked or too large")
        data = file.read_bytes()
        if (not data.startswith(b"\x89PNG\r\n\x1a\n")
                or hashlib.sha256(data).hexdigest() != entry["sha256"]):
            raise ReviewedMediaError("normalized media file failed integrity check")
    return bundle
