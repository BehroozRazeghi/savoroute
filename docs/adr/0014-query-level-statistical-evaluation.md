# ADR 0014 — Query-level, reviewer-grounded statistical evaluation

**Status:** Accepted for the v0.18.0 software milestone

## Decision

Retain the frozen v0.11.0 study bundle, existing reviewer-sheet schema, strict adjudication rules, and lexical retrieval implementation. Add an explicit, checksum-bound analysis plan, blind-safe aggregate reviewer-progress audits, query-level paired percentile bootstrap intervals, and per-query error diagnostics. Provide a local-only reviewer UI using selected files; publish no labels or reviewer notes through a network endpoint.

## Rationale

A study with 1,320 query–item pairs but eight queries has **eight** evaluation units for query-generalization uncertainty, not 1,320. Paired query resampling preserves matched comparisons of BM25 and overlap while keeping positive versus no-match metrics separate. Complete adjudication remains a hard prerequisite; no system creates synthetic relevance judgments for real data. The existing API, MCP interface, catalog identities, ranking algorithms, and numerical baselines are unchanged.

## Alternatives rejected

- Treat unreviewed OSM fields as negative ground truth, or create labels with a language model: unsupported evidence and biased evaluation.
- Bootstrap item pairs as if independent: invalidly small intervals due to within-query dependence.
- Report average nDCG with no-match queries treated as zero: changes the estimand and misrepresents undefined metrics.
- Use test results to select the primary metric or k: test leakage.
- Add a hosted reviewer-label service: unnecessary data exposure and operational complexity for this small study.

## Constraints and consequences

With only a few queries, CIs are unstable; no statistical-significance claims are made. Checksums do not establish independent human judgment or true preregistration. The UI provides no autosave to avoid storing sensitive reviewer decisions; reviewers must download their sheet periodically. Real OSM study data and human annotations are kept out of public Git by default.
