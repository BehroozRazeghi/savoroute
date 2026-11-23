# Product-quality plan

**Status:** acceptance criteria originally drafted after v0.18.0, updated for v0.22.0. UI implementation and automated regression checks exist; independent consumer usability, accessibility conformance, and real-data relevance remain unverified. These criteria are not a claim that the entire plan has passed.

**Product definition:** Savoroute is a local-first restaurant discovery application and Python retrieval toolkit, with recipe support. Its principal differentiator is inspection of catalog evidence and reproducible evaluation—not live inventory or an autonomous concierge.

## 1. Documentation and product boundaries — immediate

**Deliverable:** concise README, task-oriented documentation index, current architecture, and explicit experimental status.

**Accept when:** the default fictional catalog is identified above the fold; quick-start commands work from a clean checkout; every major linked page describes an implemented interface or is explicitly historical; release history is kept in the changelog. Verify links and commands in CI or a clean local environment.

## 2. Web discovery — implemented baseline, uncompleted product validation

**User objective:** find and inspect an eligible restaurant quickly, without understanding retrieval algorithms.

**Design and verification requirements (some implemented, all subject to product validation):**

1. Put a single search input and **Restaurants / Recipes** choice at the top. Open on a usable result state, not an oversized decorative hero.
2. Show the active dataset's name and whether it is fictional before showing results. Do not use claims such as “real listings” for synthetic records.
3. Use a compact results list or grid, with progressive disclosure for advanced filters and ranking preferences. Keep **Search** and **Recommendations** semantically distinct.
4. Improve location selection with catalog-derived choices and a documented geographic contract. The current backend accepts exact source-recorded city or display address; it does not infer city identity from an address substring. The 41 Boston-pilot records lacking a verified municipality remain unknown. Review cuisine choice presentation against actual catalog values.
5. Give each result a concise title, recorded place/cuisine, source, and explicit missing-data states. Make item detail, origin link, and relevant ranking evidence accessible without exposing unexplained numerical scores as probabilities.
6. Make nearby discovery usable without manual decimal-coordinate entry as the only entry path. Preserve consent: never request device location automatically. Any new geocoding or maps require a separate provider and privacy decision.
7. Retain a separate researcher/operator area for review tools. Do not place visit-review and relevance-study operations in the primary consumer navigation.
8. Support loading, no matches, errors, filtering, keyboard operation, and mobile layouts. Never drop catalog/source disclaimers when simplifying the interface.

**Acceptance checks:** scripted keyboard and mobile browser flows, results that match HTTP v1 contracts, no JavaScript console errors during the tested paths, no horizontal overflow at 320/375/768/1280 px, accessible names and visible focus, and a documented WCAG 2.2 AA audit (without claiming certification). Have at least five prospective users attempt a defined set of tasks; record completion, failure modes, and revisions. Preserve the existing API/CLI behavior.

## 3. Evidence and catalog readiness

**Deliverable:** metadata coverage report by source and field; clear distinction between unknown, source-reported, and manually reviewed data. Review image redistribution rights independently. Do not make cuisine/menu claims based solely on empty OSM tags. Keep sample and real data visually distinct.

**Accept when:** catalog counts are reproducible, image provenance is inspectable, missingness is surfaced in API/UI, and non-verified attributes are never shown as verified.

## 4. Independent Boston pilot

**Deliverable:** run study preflight, publish a predeclared review policy, obtain independent reviewer sheets, adjudicate with source evidence, and produce an appropriately limited report.

**Accept when:** the source-evidence coverage is measured first; ambiguous pairs are not forced into binary judgments; every included binary judgment has defensible support; unresolved uncertainty is disclosed rather than forced into false labels; source and annotation hashes match; development and test were handled separately. Four queries per split cannot justify population-wide claims.

## 5. Benchmark expansion and method decisions

Recruit queries across multiple areas and intent types with documented sampling. Freeze a larger holdout before tuning. Compare current lexical baselines first; include vector/geographic methods only with compatible frozen inputs and complete relevance judgments. Report uncertainty at the query level, ablations, missing-data effects, and model/index versions.

## 6. Deployment gate — only if public hosting is intended

Define threat model, authentication/authorization, request limits, TLS and reverse-proxy configuration, secret handling, log retention, third-party data licensing, and operational monitoring. A loopback development server is not a hardened public service.

## Exclusions

Do not add generative-chat, mobile camera-roll ingestion, live booking, more agent frameworks, or a new retrieval model merely to expand the feature list. Require a user need and an evaluation plan first.
