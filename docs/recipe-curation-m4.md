# Milestone 4 — Source-linked recipe pilot and restaurant evidence boundaries

## Scope and release status

This release **adds three transcribed/adapted real-source recipes** to a separately generated local catalog, without changing any of the **165 OSM restaurant records**. The three recipes are **not independently cooked, verified for dietary/allergen safety, reviewed for food safety, or approved as production editorial content**. Their descriptions and preparation instructions are short editorial adaptations of the specific Wikibooks revisions. There are no reviewed original recipe photos, real restaurant menus, verified prices, or new factual venue descriptions.

The tracked seed manifest is `data/curated/wikibooks-recipes-pilot-v1.json`. Each entry records the source page, revision permalink (`oldid`), date consulted, source attribution, adaptation notice, ingredients, steps, and explicit reuse license. All source URLs must be HTTPS `en.wikibooks.org/wiki/Cookbook:*` pages and revision IDs must identify the same page. This constraint is a defensive validation rule, **not** independent source authentication or a grant of rights for arbitrary content.

**Content-rights boundary:** Wikibooks Cookbook contributors publish the source text under **Creative Commons Attribution–ShareAlike 4.0 (CC BY-SA 4.0)**; the adapted recipe text distributed in this pilot is accordingly treated as CC BY-SA 4.0, separate from SavoRoute's software license. Keep the contributor attribution, source/revision URL, adaptation notice, and CC license link (https://creativecommons.org/licenses/by-sa/4.0/) when redistributing these recipes. Review the upstream history for individual-attribution requirements and confirm that the revision and any borrowed source portions are covered by the indicated license before commercial publication. **No Wikibooks imagery is included or licensed by this manifest.** The importer does not retrieve source content over the network and cannot prove the declared attribution, license or transcription correctness; a human content review is still required.

## Reproduce the combined local catalog

From the project root with `pip install -e '.[api,dev]'`:

```bash
savoroute quality recipes-build \
  --catalog data/generated/real-pilot/catalog.json \
  --manifest data/curated/wikibooks-recipes-pilot-v1.json \
  --output data/generated/real-pilot/catalog-with-recipes-local.json \
  --notes-out data/generated/real-pilot/recipe-notes-local.json \
  --report data/generated/real-pilot/recipe-build-report-local.json
```

This validates each record and writes three **new, non-overwriting** files. The base catalog has 165 restaurants and no authentic recipes; the merged catalog has 165 unchanged restaurants and three recipe entries. Recipe IDs are deterministic hashes of their canonical source URLs. Preparation and rights fields live in a **catalog-digest-bound notes sidecar**, not in restaurant data. The producer refuses outputs that overwrite the manifest or base catalog, duplicated recipe identities, arbitrary hosts, invalid revision links, or incompatible/fake source catalogs.

Run a new OSM snapshot audit against the *combined* catalog. The existing `osm-source-facts-v1.json` from Milestone 3 is deliberately bound to the **restaurant-only** catalog and **must not be reused** with the 168-item catalog:

```bash
savoroute quality audit \
  --catalog data/generated/real-pilot/catalog-with-recipes-local.json \
  --osm data/generated/real-pilot/frozen/source.json \
  --report data/generated/real-pilot/quality-with-recipes-local.json \
  --source-facts-out data/generated/real-pilot/osm-facts-with-recipes-local.json \
  --queue-limit 168

savoroute web serve \
  --catalog data/generated/real-pilot/catalog-with-recipes-local.json \
  --source-facts data/generated/real-pilot/osm-facts-with-recipes-local.json \
  --recipe-notes data/generated/real-pilot/recipe-notes-local.json \
  --host 127.0.0.1 --port 8001
```

The `--queue-limit 168` option reproduces the **full** included review queue; the CLI defaults to a shorter 50-record queue when that flag is omitted. The report is an audit priority list, not 168 independently confirmed errors.

You can also start immediately with the **already generated**, matching `catalog-with-recipes-v1.json`, `osm-facts-with-recipes-v1.json`, and `recipe-notes-v1.json` provided inside the cumulative ZIP. `GET /v1/items/{item_id}/recipe-notes` returns source, revision, attribution, ingredients and steps for included recipes only. It is read-only and inherits the configured API key gate. The UI displays the `source_transcribed_unverified` review status and source attribution; it uses DOM text APIs rather than unsanitized HTML. Restaurant-only filters, local MCP and frozen benchmark data are not changed.

## Boston geographic backfill (remains uncompleted)

The 165 restaurant records include 124 source-tagged `addr:city=Boston` and **41 with no verified municipality tag**. Milestone 4 creates a deterministic, catalog-identity-bound list for **manual geographic review**, `data/generated/real-pilot/boston-unresolved-review-v1.json`, using:

```bash
PYTHONPATH=src python scripts/export_unresolved_boston.py \
  --catalog data/generated/real-pilot/catalog.json \
  --output /tmp/boston-unresolved-review.json
```

Neither this export nor the recipe importer assigns a city. The official City of Boston GIS polygon service was consulted but its GeoJSON **could not be downloaded inside this build environment** (network DNS failure). To attempt the official audit on a machine with connectivity, follow `docs/boston-boundary-workflow.md` and run `python scripts/resolve_boston_geography.py`. Inspect the source checksum, source-tag conflicts, coordinate accuracy and boundary-edge records before switching the active catalog. A geometric boundary for Boston alone cannot assign a precise *alternative town name* to a point outside Boston; the MassGIS 351-municipality layer is more appropriate for multi-town assignments. Avoid calling the entire query bounding box “Boston”.

## Restaurant provenance and publication gate

The Boston pilot has **zero reviewed venue descriptions, zero confirmed price tiers, zero approved photographs**, and **zero confirmed current menus**. Saved OSM website/opening-hours/diet tags are historically dated **observations**, not proof of current venue data, menu, allergy safety, seating, hours or reservation availability. For accurate commercial content, a responsible curator should:

1. Confirm that each listing corresponds to a currently operating venue and resolve duplicate identifiers using original OSM identity and a dated canonical business source.
2. Collect a **record-specific source** for each proposed name, location, menu URL, hours, price or dietary claim; preserve the exact observation timestamp, license/contract terms and reviewer identity.
3. Review image ownership/permission, likeness and commercial redistribution terms before publishing any photograph. Do **not** hotlink or scrape protected third-party listing photographs by default.
4. Use existing `savoroute evidence prepare` and `savoroute evidence publish` review-and-publication commands as the appropriate gate for operator-reviewed reference claims; consult `docs/reviewed-evidence.md` and `docs/media-ingestion.md` for rights-reviewed local media. Review is an operational decision, not a cryptographic proof of underlying claims.
5. Add expiry/freshness policies per claim type and invalidate or annotate stale statements. Never silently infer an allergen-free or vegan menu from a cuisine label or a restaurant category.

The pilot deliberately **does not** bulk scrape menus, create AI-generated business descriptions, or attach unlicensed photographs. This keeps the product honest, but means it is **not yet a consumer-ready real-world recommendation product**.

## Testing and limitations

Run `python -m pytest -q`, `node --test tests/web/*.test.mjs`, `PYTHONPATH=src python -m savoroute study verify --study-dir data/generated/real-pilot/frozen`, and `PYTHONPATH=src python scripts/browser_smoke.py --catalog data/generated/real-pilot/catalog-with-recipes-v1.json --source-facts data/generated/real-pilot/osm-facts-with-recipes-v1.json --recipe-notes data/generated/real-pilot/recipe-notes-v1.json` (requires Playwright + Chromium). The browser checks exercise actual DOM interactions at desktop and mobile widths; they do not constitute public-deployment performance or accessibility certification.

The three recipe records are *seed examples* to test the real data pipeline, not a meaningful recommendation benchmark. An independent editorial panel, more source diversity, image rights, reliable restaurant menus and a real human-judged benchmark remain future work.
