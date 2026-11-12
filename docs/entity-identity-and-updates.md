# Source identity and catalog updates

Savoroute maintains two distinct identifiers:

- `item_id` identifies a catalog item and remains stable across updates.
- `(provider, source_ref)` identifies a record in an external dataset. A single item can have multiple reviewed source bindings.

The source registry is stored separately from catalog schema v1. Existing search APIs, `item_id` values, and media references remain unchanged. IDs initially assigned by the v0.3.0 OSM importer remain source-derived; introducing the registry does not rekey those items.

## Sync rules

An OSM source key can update an existing item when the binding is unambiguous, the catalog item is OSM-owned, and its fields match the last recorded source-managed digest. Updated fields come from the latest supplied snapshot. A repeated snapshot yields `unchanged` decisions and identical catalog/registry content. OSM import reports (schema v2) carry the element's version, UTC timestamp, and content hash; the source registry (schema v2) retains them across updates. Older report and registry schema v1 files remain readable.

Records with incomplete source fields, conflicting identity candidates, or out-of-band catalog edits receive `review` decisions without changing the catalog. New source keys with no review candidates are admitted. Name and address normalization, plus a 75 m coordinate check for already bound records, generate review candidates; they do not establish identity automatically.

A bounded snapshot is not a complete register. Absence from a later snapshot never deletes a catalog item. When a binding has a known OSM version, an older incoming version, a missing version, or different content at the same version is sent for review. Increasing versions must also have increasing UTC timestamps. Registries imported from v1 contain no version baseline; their first versioned synchronization establishes one. Legacy unversioned inputs remain supported for compatibility, but cannot offer rollback protection. Bounded snapshots still cannot establish deletion.

## CLI workflow (synthetic fixtures)

The existing v0.3.0 importer produces the initial catalog and report:

```bash
savoroute osm import \
  --input data/sample/osm_overpass_fixture.json \
  --synthetic-fixture \
  --output data/generated/osm-initial.json \
  --report data/generated/osm-initial-report.json
```

Bootstrap a registry from **that exact** catalog/report pair. The report's catalog digest is checked before source bindings are admitted:

```bash
savoroute identity bootstrap-osm \
  --catalog data/generated/osm-initial.json \
  --report data/generated/osm-initial-report.json \
  --output data/generated/osm-registry.json
```

Apply the second snapshot and write three new files:

```bash
savoroute osm sync \
  --input data/sample/osm_overpass_update_fixture.json \
  --catalog data/generated/osm-initial.json \
  --registry data/generated/osm-registry.json \
  --synthetic-fixture \
  --output data/generated/osm-updated.json \
  --registry-output data/generated/osm-updated-registry.json \
  --report data/generated/osm-sync-report.json
```

The supplied update fixture produces one changed item, one review candidate, and one new item. Its fictional data must not be represented as a real OSM listing.

## Reviewed source links

To record a manually reviewed association with a separate provider:

```bash
savoroute identity link \
  --catalog data/generated/osm-updated.json \
  --registry data/generated/osm-updated-registry.json \
  --provider localguide --source-ref sample-business-17 \
  --item-id <catalog-item-id> \
  --output data/generated/osm-reviewed-registry.json
```

Replace `<catalog-item-id>` with the ID from the catalog. This command changes **only** the registry; it neither modifies catalog fields nor proves that the reviewed association is correct. Existing links cannot be reassigned through this command. Multiple OSM keys bound to the same item disable automatic OSM field updates until conflicts are resolved.

## Output and provenance

The sync report records source keys, admitted/updated/unchanged/review/skipped decisions, candidate item IDs, the input snapshot hash, the output catalog hash, and dataset attribution. The registry stores a source hash, the last source-managed item hash, and coordinates when available.

Each output file is written through an atomic rename. Writing catalog, registry, and report together is **not a transactional commit**: a storage failure after one rename may leave a partial set. The commands reject existing output paths by default. Keep input snapshots and use fresh output paths for each run; the registry and catalog should be advanced together.

## Scope and outstanding validation

This milestone provides deterministic source identity bookkeeping and manual association. It is not a probabilistic cross-provider entity resolver. The duplicate-candidate rule may miss businesses with name variations or incomplete address data and may propose unrelated businesses with matching names. The [candidate evaluation harness](identity-benchmark.md) measures pairwise precision, recall, and review rate on annotated inputs. Its committed fixture is fictional; no independently annotated real-world performance has been measured.

Before using the system on production data: add independently annotated match/nonmatch pairs, version-aware updates, a durable transactional store, and a procedure for resolving review decisions and recording reviewers. See [roadmap](roadmap.md).
