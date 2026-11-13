# Boston municipal boundary backfill — audited workflow

## Status: authoritative layer identified, data not yet downloaded

The live Boston catalog shipped with Milestone 1 has 165 OSM records: **124** explicitly carry `addr:city=Boston`, and **41** have no city tag. All 165 have preserved OSM coordinates. The City of Boston publishes a GIS polygon titled **City of Boston Boundary**, at:

https://gisportal.boston.gov/ArcGIS/rest/services/CityServices/COBBoundary/MapServer/0

The service supports GeoJSON export. A query with `where=1=1`, `outFields=CITY`, `outSR=4326`, `returnGeometry=true`, `f=geojson` should export its city feature in WGS84. The city's GIS description explicitly advises that its layers may be corrected or modified and that users should determine suitability for their use. Massachusetts' MassGIS municipalities layer is an alternative independent comparison source (https://www.mass.gov/info-details/massgis-data-municipalities).

**Important:** The release environment could view the official service's metadata but was unable to retrieve its polygon bytes. Therefore no actual City of Boston boundary file or verified inside/outside classifications for the 41 missing OSM tags are included. Do not advertise 165 city-classified records.

## Execute on a network-enabled machine

From the extracted repository root with `pip install -e '.[api,dev]'`:

```bash
python scripts/resolve_boston_geography.py
```

This script:

1. Requests **only** the pinned City of Boston official HTTPS GIS layer, with WGS84 coordinates.
2. Rejects an empty, oversized, non-GeoJSON, wrong CRS, non-polygon, multi-feature, or non-`Boston` feature response.
3. Stores the unmodified polygon bytes in `data/generated/real-pilot/boston-boundary.geojson` and calculates their SHA-256.
4. Loads the saved catalog and the original frozen OSM snapshot, compares their source identities, and attributes a missing city **only** when the point lies within the polygon.
5. Writes a **new** `catalog-boundary-verified.json` plus a SHA-bound `geography-boundary-report.json`. The original catalog and frozen study remain unchanged; the script refuses to overwrite any output.
6. Reports source-tag conflicts and source-tagged Boston points outside the imported polygon. It does not silently rewrite their OSM city labels.

Or, with a manually downloaded City of Boston GeoJSON file:

```bash
python scripts/resolve_boston_geography.py \
  --boundary-file /path/to/official-boston.geojson \
  --output /tmp/savoroute-boston-verified.json \
  --report /tmp/savoroute-boston-verified-report.json
```

The offline file must still have exactly one GeoJSON feature with `properties.CITY=Boston`, and must pass polygon validation. **That alone cannot prove its authenticity**: an operator must verify that it was actually downloaded from the official source before treating this as independent evidence.

## Quality gates before switching the active catalog

- Inspect `boundary.source_url`, `boundary.sha256`, `source_snapshot_sha256`, `catalog_sha256`, `city_from_osm_tag`, `city_from_boundary`, `city_unknown`, `boundary_conflicts` and `source_tag_outside_boundary` in the report.
- Check all changed items' coordinates against the source polygon and inspect points near municipal boundaries, islands and coastlines; source coordinates can be approximate center points.
- Verify source-tagged points that fall outside the polygon with another authoritative source. The tag may be inaccurate, or the polygon's coastline and the source geometry may disagree.
- Do not assign cities to points outside the municipality, and do not use the input snapshot's search bounding box as a municipality boundary.
- If approved, launch with `savoroute web serve --catalog data/generated/real-pilot/catalog-boundary-verified.json --port 8001`. Rebuild any derived index or item bindings against the new catalog fingerprint. Keep the frozen study unchanged.

## Tests

`tests/test_boston_boundary.py` checks pinned WGS84 query formation, official feature name, wrong municipality rejection, coordinate validity, SHA-256 binding, malformed responses, and size limits using synthetic polygons. These tests do **not** imply that an actual Boston boundary has been fetched, independently cross-checked or applied to the live catalog.
