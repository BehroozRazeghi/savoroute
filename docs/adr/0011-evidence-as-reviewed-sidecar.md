# ADR 0011: Reviewed enrichment is separate from canonical identity and retrieval

**Decision.** Add a catalog-digest-bound reviewer sidecar rather than changing the v1 catalog schema or silently enriching structured items. HTTP serves only approved evidence as a distinct optional resource. The browser can display evidence references; it never auto-loads external images or scrapes menus.

**Motivation.** Imported OpenStreetMap catalog records are sparse; a menu URL or food image may help users, but lack of provenance and uncertain rights would weaken Savoroute's trust boundary. Palate's user-confirmation workflow and local-first handling of photos provide useful design inspiration, but its visit matching, bundled Michelin dataset, native scanning and third-party provider connections are not copied and have different privacy/redistribution requirements (https://github.com/jonluca/palate).

**Alternatives rejected.** Directly mutating OSM cuisines from third-party claims; using restaurant images without a recorded rights basis; allowing clients to choose arbitrary local evidence files; automatically following remote URLs while handling requests; declaring a reviewed claim equivalent to a verified restaurant fact.

**Costs.** The sidecar cannot affect recommendation ranking and is not a signed audit. It requires manual review, source updates and eventual expiration rules. These are intentional constraints of the current milestone.
