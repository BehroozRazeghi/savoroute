# Reviewed catalog references (v0.15.0)

Savoroute accepts a **separate evidence sidecar** without modifying catalog schema v1, the source identity registry, embeddings, or ranking semantics. The goal is to make manually checked menu links, image references, cuisine claims, and descriptive notes visible with evidence rather than silently inserting them as facts. The sidecar is optional: an unconfigured API returns an empty `reviewed_claims` array. Everything is local-file based; no source URL is fetched by the commands or API.

## Design and trust boundaries

1. The curator chooses a catalog snapshot and saves candidate claims with stable catalog item IDs. The tool binds proposals to a deterministic SHA-256 digest of canonical catalog JSON. Stale catalog content is rejected.
2. `savoroute evidence prepare` validates the proposal structure, sources, dates, image license/attribution fields, and writes an **exclusive-create** review template. The generated decisions have no default approval.
3. A reviewer inspects each source independently and records an explicit `approve` or `reject`, their reviewer identifier, reason, and ISO review date. This is an **assertion of review**, not independent verification of legal rights or factual accuracy.
4. `savoroute evidence publish` requires exactly one decision per claim, validates the review against the proposal digest, blocks multiple approved menu URLs for an item, and writes a *new* immutable-by-workflow JSON bundle. It refuses to overwrite an existing file.
5. A server must opt in to `--evidence` during startup. It validates the bundle against the exact catalog content. `GET /v1/items/{item_id}/evidence` returns approved evidence only (without internal reviewer identifiers or rationales); the original `/v1/items/{item_id}`, search, ranking, recommendation, and MCP outputs remain unchanged. The web item dialog labels them **Reviewed source references** and exposes links only when clicked.

Reviewers should open references in a safe browser and confirm a source actually describes the claimed restaurant. For images, inspect the file description page, license, author, attribution, permitted use, and any non-copyright rights. `CC0-1.0`, `CC-BY-4.0` and `CC-BY-SA-4.0` are accepted *metadata identifiers*, not a determination that the image really bears that license. Attribution requirements may include a license link and change notice not represented by the current fields; do not reuse or redistribute these images until rights have been separately checked. **No image content is downloaded, embedded, proxied, or redistributed by this milestone.** Menu links do not prove current menu items, prices, hours, dietary suitability, allergen safety, or reservation availability.

This sidecar is not a signed audit log: SHA-256 binds it to the catalog and proposal/review identifiers and detects accidental mismatches, but it cannot prevent a local editor from replacing both files and hashes. Maintain originals under appropriate access control and use signed commits or external attestations for higher assurance.

## JSON contracts

A proposal JSON has exactly three top-level keys: `schema_version`, `catalog_digest`, and `claims`. Each claim contains exactly:

```json
{
  "claim_id": "menu1", "item_id": "r001", "kind": "menu_url",
  "value": "https://example.org/sample-menu",
  "source_url": "https://example.org/restaurant",
  "observed_on": "2026-11-12", "license": null, "attribution": null
}
```

Allowed `kind` values: `menu_url`, `image_url`, `cuisine`, `descriptive_note`. `menu_url`, `image_url`, and all `source_url` references must be HTTPS URLs. `image_url` additionally requires an explicit supported license ID and nonempty attribution. Image licensing is reviewed metadata, **not automatic image permission validation**. Up to 500 candidate claims are allowed per file. Identifiers must be unique.

The generated reviewer template has `schema_version`, `proposal_digest`, and a `decisions` array. Fill every row with `decision` (`approve` or `reject`), `reviewer`, `reason`, and `reviewed_on`; never change claim IDs or the proposal digest.

## Procedure

```bash
# The proposal JSON must bind to this exact catalog. For a local catalog:
python - <<'PY'
from savoroute.data.catalog import load_catalog
from savoroute.evidence.review import catalog_digest
print(catalog_digest(load_catalog('data/generated/real-pilot/catalog.json')))
PY

savoroute evidence prepare \
  --catalog data/generated/real-pilot/catalog.json \
  --proposals data/generated/enrichment/candidates.json \
  --output data/generated/enrichment/review.json

# Manually inspect and complete the review.json before continuing.
savoroute evidence publish \
  --catalog data/generated/real-pilot/catalog.json \
  --proposals data/generated/enrichment/candidates.json \
  --review data/generated/enrichment/review.json \
  --output data/generated/enrichment/approved.json

savoroute web serve \
  --catalog data/generated/real-pilot/catalog.json \
  --evidence data/generated/enrichment/approved.json \
  --host 127.0.0.1 --port 8001
```

Do not commit private review files, source material without redistribution rights, or personal location information. Files under `data/generated/` are excluded from Git by default. For public datasets, publish only source metadata that can legally and ethically be redistributed, with a clear attribution and update policy.

## Validation and limitations

Run `python -m pytest -q tests/test_evidence_review.py` plus the full suite, Ruff and JavaScript checks. A review cannot rescue an invalid or unidentified catalog record; it may only add clearly labeled, reviewer-approved references. There is no automatic menu extraction, provider crawling, copyright checking, photo-roll access, geolocation matching, or change monitoring. Future work can add first-party media staging and an opt-in photo-visit association workflow with separate consent and retention policies.

### Reproducible fictional example

`data/sample/evidence_candidates_demo.json` provides two **fictional, non-verified** proposal references for the bundled catalog. Start a test review with:

```bash
mkdir -p data/generated/enrichment
savoroute evidence prepare \
  --proposals data/sample/evidence_candidates_demo.json \
  --output data/generated/enrichment/example-review.json
```

No approvals are included by default. Do not mistake the `example.org` URLs for actual restaurant sources or redistribute the fixture as reviewed evidence. Notebook 17 shows a complete mock-review round trip without writing to the project tree.
