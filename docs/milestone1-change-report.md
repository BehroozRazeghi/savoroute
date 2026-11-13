# SavoRoute Milestone 1 — Implementation and Verification Report

**Date:** November 13, 2026
**Input:** uploaded `savoroute(6).zip` (SavoRoute 0.18.0)
**Scope:** geographic location normalization and the Boston city-filter defect
**Delivered:** modified project source/archive, source patch, migrated live Boston pilot catalog, reproducible normalization report, and regression tests.

## 1. Outcome

**Implemented and locally verified.** Legacy `location="Boston"` no longer performs exact comparison against the entire address alone: it now matches either the exact recorded municipality (`city`) or the exact original display `location`. Case, Unicode normalization, and repeated whitespace are normalized, but substrings and guesses are not permitted. New explicit `city`, `region`, and `country` filters are available in the Python domain, CLI, and REST API. The browser's city/location input continues using the backward-compatible `location` API field. Zero results still correctly mean that no recorded data satisfies all requested hard constraints.

## 2. Actual Boston pilot comparison

| Metric | Uploaded catalog | Delivered catalog |
| --- | ---: | ---: |
| Restaurant records | 165 | 165 |
| `location=Boston` eligible records | **0** | **124** |
| `city=Boston` eligible records | **0** | **124** |
| `city=Cambridge` eligible records | — | 0 |
| `city=Boston` plus `region=MA` | — | 122 |
| `city=Boston` plus `country=US` | — | 0 (country not in source records) |
| Saved latitude/longitude pairs | 0 | **165** |
| OSM records with explicit `addr:city=Boston` | 124 | 124 retained |
| Restaurants without verified municipality | 165 | **41** |
| Existing item IDs changed | — | **0** |
| Existing displayed locations changed | — | **0** |

The 41 records without `addr:city` remain **unknown** until validated with an independent municipal boundary. Assigning all 165 records to Boston based only on the collection area would be an unsupported inference. The optional boundary enrichment path has been implemented and tested with synthetic polygons, but a real reviewed Boston boundary is **not included**. Do not report 165/165 city-classified.

Geography provenance for the migrated pilot is recorded in `data/generated/real-pilot/geography-normalization-report.json`:

- Input catalog SHA-256: `00b9fe29d1e6cdabd4242edc91a56237762af379cbf3decad1b4d1325a20503d`
- Output catalog SHA-256: `da5287cf3d4d258c7473cd584565620402cd4bdffb9dfd0659c5b11dca5ece3d`
- Canonical source snapshot SHA-256: `0d3d92cb54c9b4aba7f7afe9ca6aa31139206a8f74fa684e84ab6aeb5a01febb`
- OSM-matched records: 165; recorded city from tags: 124; new boundary inferences: 0; boundary conflicts: 0.

The historical frozen study under `data/generated/real-pilot/frozen/` has not been changed. The original `import-report.json` refers to the **original** catalog hash and is preserved as historical import evidence; the separate normalization report binds the new catalog. The `data/generated/` tree is ignored by the existing `.gitignore`, so the normalized pilot is included in the **full ZIP** but not in the Git patch: copy the supplied normalized catalog if applying the patch to a separate checkout.

## 3. Modified implementation

| File | Exact change |
| --- | --- |
| `src/savoroute/domain/models.py` | Add eight optional geographic fields to immutable `CatalogItem`: `raw_address`, `city`, `region`, `country`, `city_id`, `latitude`, `longitude`, `city_source` |
| `src/savoroute/data/catalog.py` | Permit the additive v1 fields, validate finite coordinate pairs, reject geographic data for recipes, preserve the legacy JSON shape when fields are absent |
| `src/savoroute/ingestion/osm.py` | Map `addr:city`, state/country, address and source node/center coordinates; retain OSM provenance and identifiers in both synthetic and real imports |
| `src/savoroute/geography/normalization.py` (new) | Deterministic offline migration by stable OSM item ID, with optional reviewed WGS84 polygon/multipolygon and holes, checksum-bound report, no external geocoding, conflict reporting |
| `src/savoroute/retrieval/lexical.py` | Fix city filtering; add explicit city/region/country constraints; retain legacy exact display-location filtering |
| `src/savoroute/api/contracts.py` | Add geography to item/recommendation responses; add typed city/region/country filter inputs and applied-filter outputs |
| `src/savoroute/api/app.py` | Add geographic query parameters to GET `/v1/items` without changing endpoint names or HTTP version |
| `src/savoroute/services/recommendation.py` | Surface geography in recommendation items and applied constraints |
| `src/savoroute/cli.py` | Add `geo normalize`; add `--city`, `--region`, `--country` to search/rank/recommend commands |
| `src/savoroute/web/static/index.html` | Clarify the city-or-exact-address field and unknown-metadata behavior; no unrelated visual overhaul |
| `src/savoroute/identity/registry.py` | Preserve pre-milestone item digests by excluding absent new fields; new values are included in new digests |
| `src/savoroute/evaluation/study.py` | Verify legacy immutable study provenance by explicitly projecting only new optional geography from source-derived items, while still verifying original field and bundle hashes |
| `tests/test_geography_normalization.py` (new) | Add 23 tests for OSM mapping, city matching, legacy migration, missing data, polygon/hole parsing, conflict handling, schema rejection, API, CLI, historical digests and frozen study compatibility |
| `tests/web/api.test.mjs` | Add browser filter contract regression; old location query still carries the user-entered city |
| `README.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/geographic-normalization.md` (new) | Document the new schema, commands, provenance, unresolved records, and compatibility constraints |
| `data/generated/real-pilot/catalog.json` | Migrate existing pilot to structured, source-derived geography |
| `data/generated/real-pilot/geography-normalization-report.json` (new) | Immutable source/catalog checksums, field coverage, unresolved ID list and conflicts |

## 4. Test execution

**Actual commands and results (local environment):**

```text
PYTHONPATH=src python -m pytest -q
451 passed, 2 skipped
  - optional MCP v2 protocol tests skipped (MCP SDK not installed)
  - optional FAISS backend test skipped (faiss not installed)

node --test tests/web/*.test.mjs
13 passed, 0 failed

PYTHONPATH=src python -m savoroute study verify \
  --study-dir data/generated/real-pilot/frozen
Verified 165 items and 8 queries

git diff --check
passed
```

The existing `data/generated/m1c/registry-initial.json` loads against the original `catalog-initial.json` and its item digest matches, confirming backward-compatible source bindings.

**Pilot FastAPI smoke tests:**

- `GET /v1/items?location=Boston` → 200, total=124
- `GET /v1/items?city=Boston` → 200, total=124
- `GET /v1/items?city=Cambridge` → 200, total=0
- `GET /v1/items?city=Boston&region=MA` → 200, total=122
- `GET /v1/items?city=Boston&country=US` → 200, total=0 (no stored country)
- `POST /v1/search`, `/v1/rank`, `/v1/recommend` with `filters.city=Boston`, `query=Italian` → all 200 with nonempty, grounded results.

No external browser E2E or live Overpass requests were run. The reviewer did not download or independently verify the official Boston administrative boundary. The user-facing page was only adjusted for the location field; a broader redesign remains Milestone 2.

## 5. How to run the modified project

From the extracted project directory:

```bash
python -m pip install -e '.[api,dev]'
savoroute web serve --catalog data/generated/real-pilot/catalog.json --port 8001
# Open http://127.0.0.1:8001
```

Or test from the command line:

```bash
savoroute search Italian --catalog data/generated/real-pilot/catalog.json --city Boston
savoroute search Italian --catalog data/generated/real-pilot/catalog.json --location Boston
```

To regenerate a new normalized catalog from your **unmodified** frozen source and catalog:

```bash
savoroute geo normalize \
  --catalog data/generated/real-pilot/frozen/catalog.json \
  --osm data/generated/real-pilot/frozen/source.json \
  --output /tmp/boston-normalized.json \
  --report /tmp/boston-normalization-report.json
```

See `docs/geographic-normalization.md` for the optional verified boundary path, validation semantics, and API examples. The CLI refuses to overwrite existing files by default.

## 6. Outstanding work (not misrepresented as complete)

1. **41 pilot municipalities unresolved:** obtain and review an authoritative Boston municipal polygon, then perform the already-implemented polygon migration with a fresh output path. Inspect the conflict report.
2. **Country coverage absent:** `country=US` correctly returns no Boston pilot records until trustworthy country evidence is imported. Do not fill all missing countries from an unsupported assumption.
3. **Live data quality unaddressed:** pricing, dietary guarantees, menus, opening hours and business status remain missing/unknown and are separate from geographic normalization.
4. **Geo scale beyond this milestone:** production geocoding, geospatial DB, multi-city disambiguation, spatial indexing, and visual map interactions are not implemented here.
5. **Frontend UX redesign:** preserve as a separate milestone rather than bundling a risky large rewrite with the city-filter fix.

**Verdict:** The confirmed city-filter defect is repaired for records with source-supported city data; schema/API/CLI/browser compatibility is retained, historical benchmark integrity is restored, and the remaining uncertainty is clearly recorded. The project is not yet production-ready solely because this milestone passed.
