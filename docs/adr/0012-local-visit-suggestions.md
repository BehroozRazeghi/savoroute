# ADR 0012 — Local metadata-only suggestions before visit confirmation

**Status:** Accepted for v0.16.0.

## Decision

Implement a deterministic Python pipeline using an explicitly selected, bounded JSON export of timestamps and GPS coordinates. Match locations only to OSM source identities already admitted to Savoroute's canonical catalog. Generate an immutable-by-convention suggestion bundle plus a separately edited review sheet, followed by a minimal confirmed-history artifact only after complete explicit review.

Include a review page served as a **static, browser-local file editor**. It uses the user's file picker, does not call `/v1`, does not transmit files to the server, uses text nodes for untrusted data, and has a restrictive `connect-src 'none'` Content Security Policy. Python remains authoritative for validation and finalization. No new HTTP or MCP mutation endpoint is introduced.

## Why

Inferred venue visits are often wrong for adjacent restaurants, non-food photos, imprecise GPS, and temporally overlapping trips. A nearest-neighbor result is evidence of proximity only. Automatic recording would conflate inferred location with user-confirmed history. Restaurant metadata is source-derived and may not be current. Metadata can reveal private movement patterns even when images remain on-device.

## Rejected alternatives

- **Camera-roll scanning:** requires broad permission and creates unnecessary privacy risk for this milestone.
- **Hosted upload / server-side review database:** creates a more sensitive storage and authorization surface before it is needed.
- **Automatic visit confirmation or confidence thresholds:** unsupported by independently annotated visit labels.
- **Fuzzy name-only matching:** bypasses existing source identities and can merge neighboring establishments.
- **Embedding photo appearance:** unnecessary to demonstrate the metadata clustering and explicit review contract.

## Consequences

Users must deliberately export metadata and review every visit. JSON and browser review artifacts remain local, untracked, and potentially sensitive. Temporal/spatial parameters are documented defaults, not a tuned visit-detection model. Browser decisions may be saved incomplete and reloaded later; Python finalization fails closed until they are complete and bound to the original catalog/proposals.

The canonical catalog, its reviewable evidence sidecars, API `/v1`, MCP tools, and the separate real-world relevance evaluation study remain unchanged. Visit-detection quality requires separately consented, annotated evaluation before any performance claim.
