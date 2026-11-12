"""Offline evidence review with immutable catalog binding and explicit rights assertions.

The proposal manifest and review decisions are input data, not trusted instructions.
Publishing never rewrites the canonical catalog or downloads linked content.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from savoroute.data.catalog import catalog_to_dict
from savoroute.domain.models import Catalog

EvidenceKind = Literal["cuisine", "menu_url", "image_url", "descriptive_note"]
_MAX_FILE = 1_000_000
_MAX_CLAIMS = 500
_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SAFE_LICENSES = frozenset({"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0"})


class EvidenceError(ValueError):
    """Invalid or inconsistent evidence, review, or published bundle."""


def _encode(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(data: Any) -> str:
    return hashlib.sha256(_encode(data)).hexdigest()


def catalog_digest(catalog: Catalog) -> str:
    """Identity of the *content* of the catalog, independent of JSON formatting."""
    return _digest(catalog_to_dict(catalog))


def _dict(data: Any, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != keys:
        raise EvidenceError(f"{name} must contain exactly: {', '.join(sorted(keys))}")
    return data


def _str(value: Any, name: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise EvidenceError(f"{name} must be nonempty and at most {maximum} characters")
    if any(ord(c) < 32 for c in value):
        raise EvidenceError(f"{name} cannot contain control characters")
    return value.strip()


def _url(value: Any, name: str) -> str:
    raw = _str(value, name, 2048)
    parsed = urlsplit(raw)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
            or any(c.isspace() for c in raw) or parsed.hostname is None
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise EvidenceError(f"{name} must be a public HTTPS URL without credentials")
    hostname = parsed.hostname
    if hostname.endswith((".local", ".internal", ".localhost")):
        raise EvidenceError(f"{name} must not refer to a private hostname")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # Domain names cannot be verified offline; links are never fetched here.
    else:
        if not address.is_global:
            raise EvidenceError(f"{name} must not refer to a private network address")
    # URL references are displayed as links only; never fetched by Savoroute.
    return raw


def _day(value: Any, name: str) -> str:
    raw = _str(value, name, 10)
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError("noncanonical date")
    except ValueError as exc:
        raise EvidenceError(f"{name} must be an ISO date YYYY-MM-DD") from exc
    return raw


def _read_json(path: str | Path) -> Any:
    file = Path(path)
    if file.stat().st_size > _MAX_FILE:
        raise EvidenceError("evidence files cannot exceed 1 MB")
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid UTF-8 JSON evidence file") from exc


def _write_json_new(path: str | Path, data: Any) -> None:
    # Exclusive creation avoids unexpectedly replacing a reviewed artifact.
    with Path(path).open("x", encoding="utf-8") as out:
        out.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    item_id: str
    kind: EvidenceKind
    value: str
    source_url: str
    observed_on: str
    license: str | None
    attribution: str | None

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def parse_proposals(payload: Any, catalog: Catalog) -> tuple[dict[str, Any], tuple[Claim, ...]]:
    data = _dict(payload, "proposal manifest", {"schema_version", "catalog_digest", "claims"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise EvidenceError("unsupported proposal schema")
    if data["catalog_digest"] != catalog_digest(catalog):
        raise EvidenceError("proposal catalog digest differs from active catalog")
    rows = data["claims"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_CLAIMS:
        raise EvidenceError("claims must contain between 1 and 500 entries")
    claims: list[Claim] = []
    seen: set[str] = set()
    for index, candidate in enumerate(rows):
        row = _dict(candidate, f"claims[{index}]", {
            "claim_id", "item_id", "kind", "value", "source_url", "observed_on", "license",
            "attribution",
        })
        claim_id = _str(row["claim_id"], "claim_id", 64)
        if not _ID.fullmatch(claim_id) or claim_id in seen:
            raise EvidenceError("claim IDs must be unique and use lowercase identifiers")
        seen.add(claim_id)
        item_id = _str(row["item_id"], "item_id", 64)
        if catalog.get(item_id) is None:
            raise EvidenceError(f"claim references an unknown catalog item: {item_id}")
        kind = row["kind"]
        if kind not in ("cuisine", "menu_url", "image_url", "descriptive_note"):
            raise EvidenceError("unrecognized evidence kind")
        value = _str(row["value"], "claim value", 500)
        if kind in {"image_url", "menu_url"}:
            value = _url(value, "claim value")
        license_name, attribution = row["license"], row["attribution"]
        if kind == "image_url":
            if not isinstance(license_name, str) or license_name not in _SAFE_LICENSES:
                raise EvidenceError("image claim requires a supported explicit open license")
            attribution = _str(attribution, "image attribution", 300)
        elif license_name is not None or attribution is not None:
            raise EvidenceError("license and attribution fields are only for image claims")
        claims.append(Claim(
            claim_id, item_id, kind, value, _url(row["source_url"], "source_url"),
            _day(row["observed_on"], "observed_on"), license_name, attribution,
        ))
    return data, tuple(claims)


def prepare_review(catalog: Catalog, proposal_path: str | Path, output_path: str | Path) -> int:
    proposals, claims = parse_proposals(_read_json(proposal_path), catalog)
    template = {
        "schema_version": 1,
        "proposal_digest": _digest(proposals),
        "decisions": [{"claim_id": item.claim_id, "decision": None, "reviewer": None,
                       "reason": None, "reviewed_on": None} for item in claims],
    }
    _write_json_new(output_path, template)
    return len(claims)


def _decisions(review: Any, proposals: dict[str, Any], claims: tuple[Claim, ...]) -> dict[str, dict[str, str]]:
    data = _dict(review, "review", {"schema_version", "proposal_digest", "decisions"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise EvidenceError("unsupported review schema")
    if data["proposal_digest"] != _digest(proposals):
        raise EvidenceError("review does not match frozen proposal content")
    rows = data["decisions"]
    if not isinstance(rows, list) or len(rows) != len(claims):
        raise EvidenceError("review must decide every proposed claim")
    decisions: dict[str, dict[str, str]] = {}
    allowed_ids = {item.claim_id for item in claims}
    for index, candidate in enumerate(rows):
        row = _dict(candidate, f"decisions[{index}]", {
            "claim_id", "decision", "reviewer", "reason", "reviewed_on",
        })
        claim_id = row["claim_id"]
        if claim_id in decisions or claim_id not in allowed_ids:
            raise EvidenceError("review contains duplicate or unknown claim ID")
        if row["decision"] not in {"approve", "reject"}:
            raise EvidenceError("every claim requires an explicit approve or reject decision")
        reviewed_on = _day(row["reviewed_on"], "reviewed_on")
        observed_on = next(item.observed_on for item in claims if item.claim_id == claim_id)
        if reviewed_on < observed_on:
            raise EvidenceError("review date cannot precede source observation")
        decisions[claim_id] = {
            "claim_id": claim_id, "decision": row["decision"],
            "reviewer": _str(row["reviewer"], "reviewer", 120),
            "reason": _str(row["reason"], "review reason", 500),
            "reviewed_on": reviewed_on,
        }
    if set(decisions) != {claim.claim_id for claim in claims}:
        raise EvidenceError("incomplete claim decisions")
    return decisions


def publish_evidence(
    catalog: Catalog, proposal_path: str | Path, review_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    proposals, claims = parse_proposals(_read_json(proposal_path), catalog)
    review = _read_json(review_path)
    decisions = _decisions(review, proposals, claims)
    approved = []
    for claim in claims:
        decision = decisions[claim.claim_id]
        if decision["decision"] == "approve":
            approved.append({**claim.as_dict(), "review": decision})
    # Only one active menu per item is meaningful. Inconsistent evidence cannot silently win.
    for item in catalog.items:
        menus = [claim for claim in approved if claim["item_id"] == item.item_id and
                 claim["kind"] == "menu_url"]
        if len(menus) > 1:
            raise EvidenceError(f"multiple approved menus for {item.item_id}; resolve conflict")
    payload = {
        "schema_version": 1,
        "catalog_digest": catalog_digest(catalog),
        "proposal_digest": _digest(proposals),
        "review_digest": _digest(review),
        "claims": approved,
    }
    _write_json_new(output_path, payload)
    return payload


def load_evidence_bundle(path: str | Path, catalog: Catalog) -> dict[str, Any]:
    """Fail closed on stale bindings or tampered review snapshots, even at startup."""
    bundle = _dict(_read_json(path), "published evidence", {
        "schema_version", "catalog_digest", "proposal_digest", "review_digest", "claims",
    })
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        raise EvidenceError("unsupported published evidence schema")
    if bundle["catalog_digest"] != catalog_digest(catalog):
        raise EvidenceError("published evidence was built for a different catalog")
    if any(not isinstance(bundle[key], str) or not re.fullmatch(r"[0-9a-f]{64}", bundle[key])
           for key in ("proposal_digest", "review_digest")):
        raise EvidenceError("missing or invalid provenance digest")
    # Re-parse the claims under the same strict input rules. A published bundle only
    # permits approvals and still requires accountable review decisions.
    raw_claims = bundle["claims"]
    if not isinstance(raw_claims, list) or len(raw_claims) > _MAX_CLAIMS:
        raise EvidenceError("invalid published claim count")
    manifest = {"schema_version": 1, "catalog_digest": catalog_digest(catalog),
                "claims": []}
    for entry in raw_claims:
        if not isinstance(entry, dict) or set(entry) != set(Claim.__dataclass_fields__) | {"review"}:
            raise EvidenceError("invalid published claim format")
        manifest["claims"].append({key: entry[key] for key in Claim.__dataclass_fields__})
        decision = entry["review"]
        if not isinstance(decision, dict) or set(decision) != {
            "claim_id", "decision", "reviewer", "reason", "reviewed_on",
        } or decision["claim_id"] != entry["claim_id"] or decision["decision"] != "approve":
            raise EvidenceError("published claim lacks an approved review")
        _str(decision["reviewer"], "reviewer", 120)
        _str(decision["reason"], "reason", 500)
        if _day(decision["reviewed_on"], "reviewed_on") < entry["observed_on"]:
            raise EvidenceError("review date cannot precede source observation")
    if manifest["claims"]:
        parse_proposals(manifest, catalog)
    return bundle
