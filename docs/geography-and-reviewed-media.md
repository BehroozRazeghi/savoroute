# Approximate nearby search and reviewed local media (v0.17.0)

This milestone adds two **opt-in, read-only** capabilities without changing canonical catalog schema v1, retrieval scores, RRF, MCP tools, or the frozen relevance study. The web interface uses the existing FastAPI process. Neither feature performs network acquisition or downloads third-party images.

## 1. Geographic discovery

Savoroute binds the **same saved Overpass snapshot** used to import the OSM catalog. The binding uses stable `osm:type/id`-derived catalog IDs, the original restaurant name, and (for real data) the exact OSM source URL. Unadmitted duplicate candidates are excluded. Node positions and Overpass `center` for ways/relations are both accepted; the latter is a bounding-box center, **not an entrance or independently surveyed point**.

```bash
savoroute web serve \
  --catalog data/generated/real-pilot/catalog.json \
  --osm /absolute/path/to/the-original-overpass-snapshot.json \
  --host 127.0.0.1 --port 8001
```

The `--osm` argument is a saved local **Overpass JSON**, not the catalog or import report. Keep it with the original acquisition record. Both `savoroute api serve` and `savoroute web serve` accept this option. Without it, nearby search returns HTTP 409 with a clear explanation; ordinary catalog search remains available.

```bash
curl -sS 'http://127.0.0.1:8001/v1/nearby?latitude=42.35&longitude=-71.07&radius_m=1000&limit=10' \
  | python -m json.tool
```

`GET /v1/nearby` accepts explicit latitude/longitude (finite, bounded), radius 25–20,000 meters, result limit 1–50, and optional exact catalog cuisine. It uses deterministic Haversine straight-line distances, sorted by distance then item ID. The response carries the OSM snapshot SHA256, total bound restaurant geometries, geometry basis (`node` or `bbox_center`), and uncertainty language. **It is not walking distance, a route, live opening information, an availability claim, or a validated establishment-entrance location.**

The web app requests coordinates only after a user submits the form. It does not use browser geolocation permissions. For geo-enabled servers, Uvicorn access logging is disabled so coordinate-bearing request URLs are not written in ordinary access logs. Other network intermediaries may still record queries; keep the server bound to loopback unless you have an independently reviewed deployment design.

## 2. Images: manual rights review first, packaging second

An approved `image_url` evidence claim is **not** a declaration that Savoroute has verified ownership or copyright status. The operator must separately establish that the **local image bytes** correspond to the approved source and that the stated open license and attribution are correct. A SHA256 checks *local bytes against a local manifest*; it cannot prove internet-source identity or permission. The OpenStreetMap data license does **not** grant rights to restaurant photographs.

Supported reviewed evidence license identifiers remain `CC0-1.0`, `CC-BY-4.0`, and `CC-BY-SA-4.0` as in v0.15.0. CC BY variants require attribution and identification of changes; verify the exact terms and compatibility independently before redistribution. The bundle records **input** and normalized **output** SHA256, attribution, license, source URL, observation/review dates, and explicit processing changes.

**Step A — Existing evidence review:** create proposals, review each claim, and publish a catalog-bound approved bundle using the v0.15.0 `savoroute evidence` workflow. Review every image claim and establish that you may redistribute/modify the exact image. No approval occurs automatically.

**Step B — Select the local image file:** create a JSON manifest adjacent to the local file. Example (replace these placeholders with real, reviewed values):

```json
{
  "schema_version": 1,
  "catalog_digest": "<64-character catalog digest>",
  "assets": [{
    "claim_id": "<approved image_url claim ID>",
    "path": "local-image.jpg",
    "sha256": "<64-character SHA256 of that local file>"
  }]
}
```

The path is **relative to the manifest directory**. Absolute paths, path traversal, escaping symlinks, missing files, oversized/animated images, bad hashes, unapproved claims, duplicate images, and oversized batches are rejected. No HTTP requests occur.

**Step C — Publish a new immutable local bundle:**

```bash
savoroute media package-reviewed \
  --catalog data/generated/real-pilot/catalog.json \
  --evidence data/generated/enrichment/approved.json \
  --manifest /path/to/local-images.json \
  --output-dir data/generated/enrichment/reviewed-media
```

Processing uses Pillow's bounded decode and EXIF transpose, normalizes RGB PNG (max 1280×1280), removes original metadata, and writes a content-hashed manifest. The output directory must **not exist**. The system does not overwrite prior publications.

**Step D — Read-only delivery:**

```bash
savoroute web serve \
  --catalog data/generated/real-pilot/catalog.json \
  --evidence data/generated/enrichment/approved.json \
  --reviewed-media data/generated/enrichment/reviewed-media \
  --osm /path/to/saved-overpass.json \
  --host 127.0.0.1 --port 8001
```

The startup loader checks the catalog digest, the complete approved evidence digest, every media entry's review metadata, local file hashes, and fixed asset IDs/paths. `GET /v1/items/{item_id}/media` returns public attribution metadata **without internal reviewer identifiers or rationales**. `GET /v1/media/{asset_id}` requires the same API authentication as other `/v1` routes and checks the file hash again before returning PNG bytes. No remote image URL is embedded or fetched in the web interface.

The browser loads local images from this origin using the API-key header when one is configured. Object URLs are revoked when the detail dialog closes; image binaries are not retained in application storage.

## 3. Menu-reference status

`GET /v1/items/{item_id}/evidence` now includes `menu_status`:

- `reviewed_reference`: an approved menu **link** is on file; the linked menu's current content, date, and completeness are not verified.
- `not_recorded`: there is no approved menu link in the configured evidence bundle. This does **not** establish that the restaurant has no menu.

Menu contents are not fetched, parsed, cached, inferred, or used to change rankings. Status is displayed in the web item detail.

## 4. Verification and limitations

Use `python -m pytest -q`, `python -m ruff check src tests scripts`, `node --test tests/web/*.test.mjs`, `python -m pip check`, and a browser smoke test on an explicitly configured sample/real catalog. Notebook 19 uses only fictional data and deliberately generated local images. It cannot validate real licenses, physical coordinates, real-business matching, or recommendation effectiveness. The 1,320-pair real OSM relevance pilot remains unannotated.

Original reference documents: [OpenStreetMap attribution](https://www.openstreetmap.org/copyright), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), and [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
