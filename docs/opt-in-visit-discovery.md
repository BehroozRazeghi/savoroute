# Opt-in visit suggestions (v0.16.0)

This feature proposes **possible** visits from a small **user-selected metadata export**. It neither asks for camera-roll permissions nor reads photographs or EXIF files. No remote model, network request, background watcher, or public API endpoint is involved. A visit becomes part of exported history **only after explicit human review**.

## Boundaries and provenance

- Input: an explicitly selected JSON file of photo IDs, ISO-8601 timestamps **with timezone offsets**, and latitude/longitude, plus a local OSM Overpass snapshot and a matching canonical restaurant catalog.
- Input files are private and may reveal movements and routines. Keep them in `data/generated/` or another untracked private directory, with restricted filesystem permissions. Never commit, post, or send them to public services. The fictional fixture is safe to commit.
- A `user_selected: true` flag records the operator's choice; it is **not** proof of legal consent for another person's metadata. Use only metadata you are authorized to process.
- No image content, original filename, local photo path, face identity, food classification, or device ID is accepted. Any additional JSON field is rejected.
- Coordinates come from user-supplied metadata and OSM geometry. Neither is verified to represent the actual venue entrance or a visit. The suggestions file contains sensitive times, IDs, and coordinates. The finalized history omits individual photo IDs and all GPS coordinates, but retains dates and item identities.
- Only stable OSM source identities already admitted to the provided catalog are considered. Records pending entity-duplicate review and records without usable geometry are excluded. No fuzzy entity merge, Michelin dataset, or Places lookup is performed.
- Savoroute's canonical catalog and existing search/recommendation scores remain unchanged. This release adds no HTTP or MCP writes.

## Input format

```json
{
  "schema_version": 1,
  "user_selected": true,
  "photos": [
    {
      "photo_id": "opaque01",
      "taken_at": "2026-11-10T18:30:00-05:00",
      "latitude": 42.35001,
      "longitude": -71.06001
    }
  ]
}
```

Fields are strict; IDs must be opaque alphanumeric identifiers (underscores/hyphens allowed), not filenames. Timestamps must contain seconds and a UTC offset or `Z`. The manifest is capped at 1,000 records and 512 KB; this workflow never takes a directory or image-file argument. Source OSM JSON is also capped at 512 KB by the CLI. A larger real snapshot should first be narrowed to a small, correctly imported subset, not silently truncated.

## Matching algorithm

1. Convert timestamp offsets to UTC; sort by `(timestamp, photo_id)` for deterministic results.
2. Create consecutive clusters. A new photo joins the current cluster only when it is within **90 minutes** of the previous photo, within **180 minutes** of the cluster start, and within **200 meters** of **both** the first photo and the current circular-longitude centroid. These defaults are configurable within bounded limits. Threshold choices are engineering defaults **not fitted or validated** on independent visit annotations. Anchoring prevents unrestricted spatial chaining.
3. Compute the cluster centroid, with longitude wrap handling at ±180°. Match only restaurants with stable OSM identities in the **provided catalog** and positions within a **125-meter** Haversine radius. Return at most five nearby candidates, sorted by increasing distance then item ID. Distances are geometric estimates, not confidence/probability scores.
4. Keep clusters without matching restaurants in the review queue. **Never** automatically infer or confirm visits.
5. Bind the review sheet to the exact unconfirmed suggestions using SHA-256 of canonical JSON. A catalog-content fingerprint also binds the suggestions to the source catalog. These digests provide integrity between locally held files, **not** authentication against a malicious actor able to rewrite both files.
6. Require a decision, item selection where applicable, reason, and ISO review date for **every** cluster. The three decisions are `confirm` (choose a suggested restaurant), `reassign` (choose a different catalog restaurant, including when there are no candidates), and `reject` (no visit). Finalization rejects missing, contradictory, duplicate, and stale decisions.
7. Export only explicitly confirmed/reassigned visit records. The exported history contains no raw photo identifiers, latitude/longitude, or review reasons.

## Reproducible fictional demonstration

```bash
conda activate savoroute
mkdir -p data/generated/visit-demo

savoroute osm import \
  --input data/sample/osm_overpass_fixture_versioned.json \
  --synthetic-fixture --dataset visit-demo \
  --output data/generated/visit-demo/catalog.json \
  --report data/generated/visit-demo/import-report.json

savoroute visits suggest \
  --catalog data/generated/visit-demo/catalog.json \
  --osm data/sample/osm_overpass_fixture_versioned.json \
  --photos data/sample/visit_photo_metadata_fixture.json \
  --output data/generated/visit-demo/suggestions.json \
  --review-template data/generated/visit-demo/review.json
```

Expected: three **unreviewed** clusters, of two, two, and one metadata records. The first two have a nearby fictional restaurant; the last has no candidate. No visit history is created by this command.

To review them, serve the local web app (optional):

```bash
savoroute web serve --host 127.0.0.1 --port 8000
```

Open **`http://127.0.0.1:8000/visits-review`**, select **both** generated JSON files in the browser, choose confirm/reject/reassign for each suggestion, provide a rationale and review date, then download `visit-review-decisions.json`. The review page does not make API calls and its Content Security Policy blocks connections. The browser does not save review state except through your explicit download. Alternatively edit `review.json` in a text editor. Keep your output private.

Finalize (requires **all** decisions to be complete):

```bash
savoroute visits finalize \
  --catalog data/generated/visit-demo/catalog.json \
  --suggestions data/generated/visit-demo/suggestions.json \
  --review "$HOME/Downloads/visit-review-decisions.json" \
  --output data/generated/visit-demo/confirmed-visits.json
```

Output files are created once and not overwritten. If reviewing again, use new output paths or remove the previous **generated** files intentionally. Do not edit the frozen suggestion file after starting a review, or the digest verification will fail.

## Real Boston pilot

Use the 165-item catalog and its matching saved Overpass snapshot (the same local paths from the v0.11 study):

```bash
savoroute visits suggest \
  --catalog data/generated/real-pilot/catalog.json \
  --osm data/generated/real-pilot/source.json \
  --photos data/generated/private-visit-metadata.json \
  --output data/generated/private-visit-suggestions.json \
  --review-template data/generated/private-visit-review.json
```

Create the `private-visit-metadata.json` file yourself from **deliberately selected** timestamps and coordinates. It is not generated by scanning your camera roll. Never substitute the fictional fixture for real visit evidence. If the snapshot has changed since catalog import, regenerate the associated catalog/review bundle rather than silently treating coordinates as current.

## Validation and limitations

```bash
python -m pytest -q tests/test_visits.py tests/test_visits_web.py
node --input-type=module --check < src/savoroute/web/static/visits-review.js
node --test tests/web/*.test.mjs
```

This milestone is a software workflow, not a claim of real-world visit detection accuracy. No precision/recall, matching-confidence calibration, privacy-preserving geolocation guarantee, food recognition, menu verification, or visit-authenticity guarantee is established. Human decisions remain private local assertions; source coordinates may be stale or imprecise. Keep photos and full movement histories out of Git and outside untrusted servers. A future phase may support optional selected-image processing and reviewed local media packaging with explicit rights metadata, but it is not included here.
