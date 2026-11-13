# Geographic normalization (Milestone 1)

SavoRoute catalog schema v1 now accepts optional, source-grounded geographic fields in addition to the existing `location` display string. **Old catalog JSON remains valid.** City searches match a recorded city, not a substring of a street address. No network geocoding is performed.

## Fields and semantics

| Field | Meaning | Example | Origin |
| --- | --- | --- | --- |
| `location` | Existing display field, unchanged | `374 Commonwealth Avenue, Boston` | OSM `addr:full` or composed address, otherwise coordinates |
| `raw_address` | Source-recorded address, when present | `374 Commonwealth Avenue, Boston` | OSM address tags |
| `city` | Recorded municipality name | `Boston` | `addr:city`, or independently reviewed polygon |
| `region` | Recorded state/region | `MA` | `addr:state`, or independently reviewed polygon |
| `country` | Recorded country | `US` | `addr:country`, or independently reviewed polygon |
| `city_id` | Resolved jurisdiction key | `us-ma-boston` | Only an independently reviewed polygon at this milestone |
| `latitude`, `longitude` | WGS84 point, as a pair | `42.3485735`, `-71.0891003` | OSM node or way/relation center |
| `city_source` | City attribution basis | `osm:addr:city`, `boundary:<SHA256>` | Explicit source tag or approved polygon checksum |

A source tag like `addr:state=Masachusetts` is preserved as supplied rather than silently corrected. The absence of `addr:country` is recorded as `null`, not guessed from the snapshot's collection location. If `addr:city` is absent, a street address or an OSM collection bounding box does **not** establish the city.

For compatibility, the existing `location` filter accepts an exact saved display location **or** an exact `city` value (ignoring Unicode normalization, casing, and surrounding/duplicate whitespace). This is not substring matching, and `location=Boston` no longer requires `location == 'Boston'` when a separate city is present. New explicit `city`, `region`, and `country` filters require those specific fields; unknown values fail closed. Bare city names are not globally unambiguous: combine city with recorded region/country where possible. The browser's “City or exact location” field uses the compatible `location` filter.

## Reproducible Boston pilot migration

The uploaded real-world pilot contains 165 OSM records, of which **124 have `addr:city=Boston` and 41 have no city tag**. The normalized catalog in this delivery is `data/generated/real-pilot/catalog.json`; its migration evidence is `data/generated/real-pilot/geography-normalization-report.json`. The original frozen benchmark under `data/generated/real-pilot/frozen/` is left unchanged.

To generate a new copy without overwriting:

```bash
python -m pip install -e '.[api,dev]'
savoroute geo normalize \
  --catalog data/generated/real-pilot/frozen/catalog.json \
  --osm data/generated/real-pilot/frozen/source.json \
  --output /tmp/savoroute-boston-normalized.json \
  --report /tmp/savoroute-boston-geo-report.json

savoroute search 'Italian' \
  --catalog data/generated/real-pilot/catalog.json --city Boston
savoroute web serve --catalog data/generated/real-pilot/catalog.json --port 8001
```

The CLI writes new files and refuses to overwrite existing outputs. You can run it from a checked-out project that contains these pilot files; `data/generated/` is intentionally ignored by Git and may be absent from fresh clones. For a fresh clone, re-import/recollect your OSM snapshot or supply your saved copy.

The existing historical `import-report.json` records the **pre-normalization** import catalog checksum and must not be misrepresented as the normalized catalog's checksum. Use the normalization report for the new catalog fingerprint and source-snapshot lineage. A catalog change may invalidate a previously built vector index or registry digest. Rebuild matching indexes and create compatible source bindings after migration; do not bypass their integrity checks.

## Optional independently reviewed administrative boundary

Where OSM does not supply a city, the `geo normalize` command can use an **offline, operator-reviewed GeoJSON city polygon** in WGS84 longitude/latitude coordinates. Holes and multipolygons are supported. The file must contain exactly one Polygon or MultiPolygon geometry, alone or wrapped in a GeoJSON Feature or FeatureCollection with one feature.

For Boston, a suitable authoritative source to obtain and review is the [City of Boston Boundary GIS layer](https://gisportal.boston.gov/ArcGIS/rest/services/CityServices/COBBoundary/MapServer/0). Export the feature as GeoJSON with `outSR=4326`; inspect the data and its reuse terms before supplying it. **No municipality polygon is bundled with this milestone.**

```bash
savoroute geo normalize \
  --catalog data/generated/real-pilot/catalog.json \
  --osm data/generated/real-pilot/source.json \
  --boundary /path/to/reviewed-boston-boundary.geojson \
  --boundary-city Boston --boundary-region MA --boundary-country US \
  --boundary-city-id us-ma-boston \
  --boundary-source-url 'https://gisportal.boston.gov/ArcGIS/rest/services/CityServices/COBBoundary/MapServer/0' \
  --output /tmp/savoroute-boston-verified-boundary.json \
  --report /tmp/savoroute-boston-boundary-report.json
```

A source `addr:city` that disagrees with the supplied boundary is **not overwritten**: the record remains source-tagged and a `boundary_conflicts` entry appears in the report. For entries without `addr:city`, a nonambiguous point inside the approved boundary may supply `city`, `region`, `country`, `city_id`, and a `boundary:<sha256>` source marker. Outside points remain unknown. The operator is responsible for verifying the polygon identity, its validity date and its coordinates; arbitrary GeoJSON labeled “Boston” is not independent verification.

## API and CLI examples

```bash
curl 'http://127.0.0.1:8001/v1/items?city=Boston&limit=5'
curl 'http://127.0.0.1:8001/v1/items?location=Boston&limit=5' # legacy alias
curl 'http://127.0.0.1:8001/v1/items?city=Boston&region=MA&limit=5'
curl -H 'Content-Type: application/json' \
  -d '{"query":"Italian","filters":{"city":"Boston"}}' \
  http://127.0.0.1:8001/v1/search
```

The new fields are additive to existing read-only `/v1` item, search, rank, and recommendation results. Existing `location` clients still work. Missing region/country tags continue to fail region/country hard constraints.

## Verification and limitations

Run the offline regression suites:

```bash
PYTHONPATH=src python -m pytest -q \
  --ignore=tests/test_mcp_bridge.py --ignore=tests/test_mcp_protocol.py
node --test tests/web/*.test.mjs
PYTHONPATH=src python -m savoroute study verify \
  --study-dir data/generated/real-pilot/frozen
```

This milestone does **not** verify restaurant opening status, address correctness, road-side entrances, menus, dietary safety, map directions or current price. It does not implement a global geocoder, radius search over the canonical catalog, an official municipal boundary service, or a production geography database. The 41 pilot items lacking `addr:city` remain unclassified until a reviewed boundary or other reliable source establishes their municipality.

## Milestone 2 follow-up

An explicit [City of Boston authoritative boundary download and backfill workflow](boston-boundary-workflow.md) is implemented with offline validation tests. The release environment could access source metadata but could not fetch the polygon. The 41 unknown-city records in this distributed pilot consequently remain unknown.
