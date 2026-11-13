# Milestone 3 — Catalog quality, raw-source observations, and reviewer workflow

**Release:** 0.20.0, 2026-11-13. **Inputs:** the unmodified, previously saved
165-item Boston OpenStreetMap snapshot (`frozen/source.json`) and normalized
Milestone 2 catalog. **This release does not contain independent venue
verification, web scraping, real restaurant images, or a real recipe dataset.**

## Goals and enforced boundaries

1. **Measure recorded coverage:** deterministic counts and percentages per item
   type, plus a prioritized, source-linked *review queue*. Do not equate a
   populated tag with an independently verified claim.
2. **Surface existing source observations:** a separate, opt-in, catalog-digest-
   bound OSM sidecar extracts only selected tags (including city, cuisine and
   source descriptions) from the saved OSM snapshot;
   every value has an OSM field name and a source-record reference.
3. **Preserve truth and compatibility:** no changes to schema-v1 catalog item
   values, filtering, ranking, recommendation results, MCP outputs, historic
   study inputs, or the original OSM snapshot.
4. **Fail closed:** unknown fields, source identity mismatches, catalog fingerprint
   mismatches, timestamps without timezone, unsupported enum values, local URLs
   and non-HTTP links are not accepted for the published source-facts bundle.

## Reproduce the Boston audit locally

From the repository root (no network connection needed):

```bash
python -m pip install -e ".[api,dev]"
savoroute quality audit \
  --catalog data/generated/real-pilot/catalog.json \
  --osm data/generated/real-pilot/frozen/source.json \
  --report data/generated/real-pilot/quality-review-v2.json \
  --source-facts-out data/generated/real-pilot/osm-source-facts-v2.json \
  --queue-limit 165
```

Choose fresh output filenames: the command **never overwrites** existing inputs
or output artifacts. The packaged release also contains a generated reference
`quality-audit-v1.json` (first 50 actionable review records) and
`osm-source-facts-v1.json`. If using those files, replace the `v2` paths below
with `v1`. A new scan can be performed on any valid schema-v1 catalog without
an OSM snapshot by omitting both `--osm` and `--source-facts-out`.

### Serve source observations (opt-in)

```bash
savoroute web serve \
  --catalog data/generated/real-pilot/catalog.json \
  --source-facts data/generated/real-pilot/osm-source-facts-v1.json \
  --host 127.0.0.1 --port 8001
```

Visit `/` and open any restaurant with recorded OSM observations. The detail
panel identifies the raw source tag (`opening_hours`, `website`, `reservation`,
`diet:vegan` etc.), original OpenStreetMap record, snapshot date, license and
attribution, and includes a prominent non-verification warning. These facts are
**display-only**, not ingested as categorical search constraints. The source
website and menu links are only offered as user-clicked external links; they are
never fetched or embedded by SavoRoute. A source-listed opening-hours string is
**not** a real-time open/closed status. OSM dietary tags are **not** verified
allergen or ingredient safety.

`GET /v1/items/{item_id}/source-facts` returns either the unverified recorded
observations or an empty response with `verification_status` of `not_configured`
or `no_record`. `GET /v1/meta` advertises whether a sidecar is enabled. Both
routes honor the existing API-key requirement when configured.

### What the quality counts actually mean

The `by_kind.*.fields` entries report the fraction **recorded in the canonical
catalog**, not whether the value was accurate on the measurement date. In
particular:

- `description`: the generic importer text, "Restaurant entry from OpenStreetMap.",
  is treated as a **missing informative description**, not a legitimate venue
  description.
- `city`: counts only explicitly populated normalized municipalities. Unknown
  locations remain unknown; **41 Boston-pilot records still need official
  boundary reconciliation**.
- `address`: counts records with an address-like street number and alphabetic
  component; this heuristic does not verify a deliverable street address.
- `price`, `dietary_tags`, `cuisines`, `ingredients`: presence only, not current
  menu pricing, suitability, nutritional accuracy, ingredient completeness,
  or allergy clearance.
- `source_link`: original record reference only, **not a verified official
  business website**.
- `media_refs`: presence of catalog media metadata only, **not rights approval**.
- Empty recipe group: the Boston pilot contains **zero actual recipes**.
  Fictional sample recipes are intentionally kept out of product coverage
  figures and must not be passed off as genuine recipe content.

The generated quality JSON includes a prioritized subset of the review queue.
To review all entries, use `--queue-limit 165`. Every entry identifies a stable
item ID, item kind, name and missing fields. Review genuine information at
source and use the *existing* reviewed-evidence proposal/approval workflow
(`docs/reviewed-evidence.md`) where its fields apply. The queue does not
approve claims or make automatic modifications.

## Source observations: data contract and validation

`osm-source-facts-v1.json` stores the canonical catalog digest, canonical raw
snapshot SHA-256, saved Overpass `timestamp_osm_base`, ODbL-1.0 license,
contributor attribution and per-record `osm_ref`, raw element SHA-256, source
URL, element timestamp and selected `facts`: `field`, `value`, `osm_tag`.

- Stable item IDs are matched by hashing the exact OSM element identity (not
  by matching venue names or addresses). All admitted OSM restaurant records
  must occur in the saved source snapshot; mismatches block the export.
- The sidecar is loaded with the **same** catalog fingerprint that was used
  during export. The HTTP API never accepts a path supplied by a client.
- The file structure, permitted OSM field names, bounded value lengths,
  enumerations, source URLs, timestamps, record hashes and duplicates are
  checked at startup. Dangerous URLs are discarded rather than opened.
- These checks detect format violations and accidental drift. **They are not
  cryptographic authentication of the truth of OSM tags or of the original
  network response.** Secure the source snapshot and use independently checked
  third-party observations before making commercial or safety-critical claims.

## Boston results from the packaged, dated snapshot

| Measure | Recorded | Denominator | Meaning |
|---|---:|---:|---|
| Restaurant records | 165 | 165 | OSM pilot catalog |
| Recipe records | 0 | — | Real recipe catalog not available |
| Normalized city | 124 | 165 | Source-tagged, not boundary-backfilled |
| Coordinates | 165 | 165 | Saved OSM point/center |
| Address-like location | 140 | 165 | Heuristic, not address validation |
| Cuisine | 111 | 165 | OSM cuisine tag |
| Informative description | 0 | 165 | All 165 generic placeholders |
| Price tier | 0 | 165 | Completely unavailable |
| Dietary tag in canonical catalog | 0 | 165 | No inferred safety claims |
| Catalog media references | 0 | 165 | No rights-reviewed venue pictures |
| OSM website observations | 124 | 165 | Unverified, source-listed links |
| OSM cuisine-tag observations | 111 | 165 | Source-tagged classification |
| OSM city-tag observations | 124 | 165 | Source-tagged municipality |
| OSM opening-hours observations | 62 | 165 | Unverified, potentially stale |
| OSM reservation observations | 43 | 165 | Unverified source tags, not availability |
| Any supported OSM observations | 156 | 165 | At least one permitted tag |

**Source snapshot:** 2026-11-11T21:22:47Z, saved before this release. No live
business website, menu, booking provider, or Boston GIS boundary was queried
successfully from this environment. No additional real venues or recipes were
invented. A live public launch requires independent sourcing and QA.

## Explicitly deferred, with next acceptance gates

1. **Boston boundary:** retrieve the official polygon from the City of Boston
   published GIS endpoint, verify identity and geometry, review conflicts and
   border cases, publish a *new* derived catalog and re-run this audit. Never
   classify all 41 unknown records as Boston by assumption.
2. **Restaurant evidence:** collect lawful, traceable, human-reviewed official
   website/menu references and permitted images; measure accuracy and coverage
   independently. A website provided as an OSM tag is not itself verified.
3. **Real recipe sources:** obtain an appropriate rights-cleared source, with
   attribution, author/publication, ingredients, instructions and separate
   human review. The existing fictional sample is not a substitute.
4. **Relevance and agent benchmarks:** add independently judged, diverse real
   queries after improving the catalog. Do not claim model superiority from
   the unreviewed 8-query Boston study.
5. **Commercial licensing:** OSM data is ODbL. Attribution and potential
   share-alike obligations for a derived database require legal review before
   combining OSM-derived records with private proprietary venue datasets.

## Regression checks

```bash
PYTHONPATH=src python -m pytest -q
node --test tests/web/*.test.mjs
PYTHONPATH=src python -m savoroute study verify \
  --study-dir data/generated/real-pilot/frozen
PYTHONPATH=src python scripts/browser_smoke.py \
  --source-facts data/generated/real-pilot/osm-source-facts-v1.json
```

The Chromium script routes browser requests to FastAPI's TestClient in an
**offline bridge**. It tests real DOM behavior and viewport layout, not live
browser HTTP transports or real-world business facts.
