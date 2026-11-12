# ADR 0007: Source-bound relevance studies

**Status:** Accepted in v0.11.0

## Context

Relevance metrics are not interpretable without a fixed corpus, query set, and judgment protocol. Earlier Savoroute benchmarks were deliberately fictional. The v0.10.0 two-reviewer workflow checks label completeness but does not bind study materials to an archived external-data source.

## Decision

For small OSM restaurant pilots, store the original Overpass JSON, its deterministically imported catalog, the independently prepared development/test queries, a blank annotation template, separate reviewer files, a reviewer-facing reference, and a manifest of SHA-256 file hashes. Reject a mismatching catalog, reused normalized queries, unreviewed workbooks, and implicit test evaluation. Preserve import decisions and OSM attribution. Evaluation reuses the existing binary metrics and two lexical reference implementations.

The study bundle is immutable by convention, not a signed archive. No software check can certify reviewer independence, source authenticity, query representativeness, or correctness of the supplied judgments. A test query split measures held-out **queries against the same catalog**, not generalization to new restaurants.

## Consequences

The method is auditable and suitable for a bounded, exhaustively judged pilot. It does not scale to unrestricted web search, assume unjudged pairs are negative, validate restaurant menus, or provide semantic/multimodal accuracy results. Those need separately documented data and evaluation protocols.
