"""Deterministic, source-linked recipe seed importer with separate content licensing.

Source transcription and editorial adaptation are *not* independent culinary, dietary,
allergen, or intellectual-property review. No network access or automatic publishing.
The baseline 165-item restaurant catalog and frozen research study remain untouched.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from savoroute.data.catalog import catalog_to_dict, parse_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.evidence.review import catalog_digest
from savoroute.services.storage import write_json_group

MAX_RECIPE_MANIFEST_BYTES = 512 * 1024
MAX_NOTES_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"^[a-f0-9]{64}$")
RECIPE_LICENSE = "CC-BY-SA-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
STATUS = "source_transcribed_unverified"


class RecipeCurationError(ValueError):
    """Invalid source material, incompatible catalog, or unsafe publication input."""


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _text(value: Any, name: str, limit: int = 350) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 for c in value)):
        raise RecipeCurationError(f"{name} must be plain nonempty text (max {limit} chars)")
    return value.strip()


def _urls(row: dict[str, Any]) -> tuple[str, str]:
    url = _text(row.get("source_url"), "source_url", 1024)
    permalink = _text(row.get("source_revision_url"), "source_revision_url", 1024)
    source = urlsplit(url)
    revision = urlsplit(permalink)
    if (source.scheme != "https" or source.netloc != "en.wikibooks.org"
            or source.query or source.fragment or not unquote(source.path).startswith("/wiki/Cookbook:")
            or revision.scheme != "https" or revision.netloc != "en.wikibooks.org"
            or revision.path != "/w/index.php" or revision.fragment):
        raise RecipeCurationError("recipe source must be a Wikibooks Cookbook page and immutable oldid permalink")
    query = parse_qs(revision.query)
    title = unquote(source.path).removeprefix("/wiki/")
    if (set(query) != {"title", "oldid"} or query["title"] != [title]
            or len(query["oldid"]) != 1 or not re.fullmatch(r"[1-9][0-9]{0,12}", query["oldid"][0])):
        raise RecipeCurationError("recipe revision URL must identify the same page and an immutable oldid")
    return url, permalink


def _check_manifest(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "collection", "recipes"}:
        raise RecipeCurationError("recipe manifest schema must have schema_version, collection and recipes")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise RecipeCurationError("unsupported recipe manifest schema")
    _text(value["collection"], "collection", 120)
    rows = value["recipes"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise RecipeCurationError("manifest must contain 1..100 recipe records")
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for index, row in enumerate(rows):
        ctx = f"recipes[{index}]"
        if not isinstance(row, dict) or set(row) != {
            "title", "description", "source_url", "source_revision_url", "source_checked_on",
            "source_license", "source_attribution", "adaptation_notice",
            "ingredients", "steps", "cuisines",
        }:
            raise RecipeCurationError(f"{ctx}: unexpected or missing fields")
        title = _text(row["title"], f"{ctx}.title", 120)
        _text(row["description"], f"{ctx}.description", 500)
        _text(row["source_attribution"], f"{ctx}.source_attribution", 150)
        _text(row["adaptation_notice"], f"{ctx}.adaptation_notice", 350)
        if row["source_license"] != RECIPE_LICENSE:
            raise RecipeCurationError(f"{ctx}: only explicit CC-BY-SA-4.0 supported")
        try:
            day = date.fromisoformat(row["source_checked_on"])
            if day > date.today():
                raise ValueError("future date")
        except (ValueError, TypeError) as exc:
            raise RecipeCurationError(f"{ctx}: source_checked_on must be a past ISO date") from exc
        source_url, _ = _urls(row)
        if source_url in seen_urls or title.casefold() in seen_titles:
            raise RecipeCurationError(f"{ctx}: duplicate recipe source or title")
        seen_urls.add(source_url)
        seen_titles.add(title.casefold())
        for field, lower, upper, cap in (("ingredients", 2, 45, 160), ("steps", 2, 20, 450),
                                           ("cuisines", 0, 5, 60)):
            values = row[field]
            if not isinstance(values, list) or not lower <= len(values) <= upper:
                raise RecipeCurationError(f"{ctx}: {field} must contain {lower}..{upper} strings")
            for j, entry in enumerate(values):
                _text(entry, f"{ctx}.{field}[{j}]", cap)
            if len({x.casefold().strip() for x in values}) != len(values):
                raise RecipeCurationError(f"{ctx}: duplicate {field} entry")
    return rows


def read_recipe_manifest(path: str | Path) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_RECIPE_MANIFEST_BYTES:
        raise RecipeCurationError("recipe manifest must be local and under 512 KiB")
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RecipeCurationError("invalid recipe manifest JSON") from exc
    _check_manifest(value)
    return value


def recipe_id(source_url: str) -> str:
    return "r_" + hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:20]


def prepare_recipe_catalog(base: Catalog, manifest: dict[str, Any]) -> tuple[Catalog, dict[str, Any], dict[str, Any]]:
    """Build an additive catalog and transparent sidecar, never rewriting OSM records."""
    if base.synthetic:
        raise RecipeCurationError("cannot mix source-linked recipes into a fictional catalog")
    rows = _check_manifest(manifest)
    existing_ids = {item.item_id for item in base.items}
    existing_urls = {item.source_url for item in base.items if item.source_url}
    existing_titles = {(item.kind, item.title.casefold()) for item in base.items}
    new_items = []
    notes = []
    for row in rows:
        url, permalink = _urls(row)
        ident = recipe_id(url)
        if ident in existing_ids or url in existing_urls or ("recipe", row["title"].casefold()) in existing_titles:
            raise RecipeCurationError("catalog already contains a matching recipe identity or title")
        existing_ids.add(ident)
        existing_urls.add(url)
        existing_titles.add(("recipe", row["title"].casefold()))
        # A recipe's ingredients are indexed as written; no inferred allergens/dietary labels.
        new_items.append(CatalogItem(
            item_id=ident, kind="recipe", title=row["title"],
            description=row["description"], cuisines=tuple(row["cuisines"]),
            dietary_tags=(), source="Wikibooks contributors", source_url=url,
            ingredients=tuple(row["ingredients"]),
        ))
        notes.append({
            "item_id": ident, "source_url": url, "source_revision_url": permalink,
            "source_checked_on": row["source_checked_on"], "source_attribution": row["source_attribution"],
            "source_license": RECIPE_LICENSE, "source_license_url": LICENSE_URL,
            "adaptation_notice": row["adaptation_notice"], "review_status": STATUS,
            "ingredients": list(row["ingredients"]), "steps": list(row["steps"]),
        })
    merged = parse_catalog(catalog_to_dict(replace(base,
        dataset_name=f"{base.dataset_name} + {manifest['collection']}",
        items=base.items + tuple(new_items))))
    sidecar = {
        "schema_version": 1, "catalog_digest": catalog_digest(merged),
        "manifest_sha256": _sha(manifest), "verification_status": STATUS,
        "records": sorted(notes, key=lambda row: row["item_id"]),
    }
    report = {
        "schema_version": 1, "baseline_catalog_digest": catalog_digest(base),
        "merged_catalog_digest": catalog_digest(merged), "manifest_sha256": sidecar["manifest_sha256"],
        "baseline_restaurants": sum(x.kind == "restaurant" for x in base.items),
        "baseline_recipes": sum(x.kind == "recipe" for x in base.items),
        "added_source_linked_recipes": len(new_items),
        "result_restaurants": sum(x.kind == "restaurant" for x in merged.items),
        "result_recipes": sum(x.kind == "recipe" for x in merged.items),
        "recipe_item_ids": sorted(row["item_id"] for row in notes),
        "review_status": STATUS,
        "photo_count_added": 0,
        "limitations": "Source-linked adaptations are not independently cooked, diet/allergen verified, or image licensed. CC BY-SA attribution, source revision and adaptation notices must be preserved. No restaurant evidence was enriched.",
    }
    return merged, sidecar, report


def load_recipe_notes(path: str | Path, catalog: Catalog) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_NOTES_BYTES:
        raise RecipeCurationError("recipe notes missing or too large")
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RecipeCurationError("invalid recipe notes JSON") from exc
    if (not isinstance(value, dict) or set(value) != {
            "schema_version", "catalog_digest", "manifest_sha256", "verification_status", "records"}
            or value["schema_version"] != 1 or type(value["schema_version"]) is not int
            or value["catalog_digest"] != catalog_digest(catalog)
            or value["verification_status"] != STATUS or not isinstance(value["manifest_sha256"], str)
            or not SHA.fullmatch(value["manifest_sha256"])):
        raise RecipeCurationError("recipe notes schema, status or catalog digest mismatch")
    rows = value["records"]
    if not isinstance(rows, list) or len(rows) > 100:
        raise RecipeCurationError("recipe note list is invalid")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "item_id", "source_url", "source_revision_url", "source_checked_on", "source_attribution",
            "source_license", "source_license_url", "adaptation_notice", "review_status",
            "ingredients", "steps",
        }:
            raise RecipeCurationError("invalid recipe note fields")
        ident = row["item_id"]
        item = catalog.get(ident) if isinstance(ident, str) else None
        if (item is None or item.kind != "recipe" or item.source != "Wikibooks contributors"
                or ident in seen or ident != recipe_id(row["source_url"])
                or item.source_url != row["source_url"] or row["source_license"] != RECIPE_LICENSE
                or row["source_license_url"] != LICENSE_URL or row["review_status"] != STATUS
                or list(item.ingredients) != row["ingredients"]):
            raise RecipeCurationError("recipe notes mismatch catalog or rights metadata")
        seen.add(ident)
        # Reuse strict input validation on every record, not just build-time input.
        sample = {key: row[key] for key in (
            "source_url", "source_revision_url", "source_checked_on", "source_attribution",
            "adaptation_notice", "ingredients", "steps", "source_license",
        )}
        sample.update({"title": item.title, "description": item.description,
                       "cuisines": list(item.cuisines)})
        _check_manifest({"schema_version": 1, "collection": "validated", "recipes": [sample]})
    return value


def export_recipe_catalog(base: Catalog, manifest: dict[str, Any], *,
                          catalog_path: str | Path, notes_path: str | Path,
                          report_path: str | Path, manifest_path: str | Path | None = None) -> dict[str, Any]:
    docs = (catalog_path, notes_path, report_path)
    sources = (manifest_path,) if manifest_path is not None else ()
    if len({Path(p).resolve() for p in docs + sources}) != len(docs) + len(sources):
        raise RecipeCurationError("output paths must be distinct from inputs")
    merged, notes, report = prepare_recipe_catalog(base, manifest)
    write_json_group(((catalog_path, catalog_to_dict(merged)),
                      (notes_path, notes), (report_path, report)))
    return report
