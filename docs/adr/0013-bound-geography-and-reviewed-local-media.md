# ADR 0013: Operator-bound geography and review-bound local image publication

**Status:** Accepted for v0.17.0.

**Context:** Catalog schema v1 stores human-readable locations but not verified geographic coordinates. The OSM importer and private visit workflow already read saved source geometry. Evidence v0.15.0 records reviewer-approved remote image references but never grants automatic redistribution rights.

**Decision:** Share one stable-identity OSM geometry binding across visit suggestions and nearest-restaurant discovery. Bind geography only when the server operator supplies a local OSM snapshot. Report approximate straight-line distances and source geometry type, not routing or place-location certainty. Add local image publication only after reviewed image-reference claims and explicit selected-file SHA256 declarations. Preserve all provenance and image-modification metadata. Only serve normalized content whose evidence and catalog digests match. Expose absence of a reviewed menu reference as `not_recorded`, never as `no_menu`.

**Alternatives not taken:** Modify canonical catalog schema or retrieval score; geocode addresses on demand; automatically fetch photo URLs; cache third-party restaurant imagery; treat OSM ODbL as an image license; expose a user-input filesystem path through HTTP; request browser GPS automatically.

**Consequences:** No network fetch is required, and security and privacy boundaries remain legible. Operators must provide exact compatible snapshots, manually review actual rights, and maintain immutable bundles. Location accuracy, image license validity, menu freshness, and restaurant relevance remain unverified in the public product.
