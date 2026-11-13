# Savoroute Boston relevance pilot — pre-annotation protocol template

**Status: DRAFT / NOT YET APPROVED. Do not mark approved until signed by coordinator.**

This document must be filled in by the human study coordinator. None of the
placeholders below should be interpreted as collected evidence.

## Administrative record

- Study name and unique ID: **[fill]**
- Collection path and verified manifest SHA-256: **[fill]**
- Frozen source capture timestamp and OSM attribution: **[fill]**
- Protocol signed/timestamped on (UTC): **[fill]**
- Protocol archival location (independent trusted repository, if any): **[fill]**
- Coordinator and conflict-of-interest disclosure: **[fill]**
- Reviewer A / reviewer B recruitment and independence procedure: **[fill]**
- Adjudicator role and conflict-of-interest disclosure: **[fill]**

## Research questions and estimand

**[fill exact target]**. The pilot is restricted to admitted OSM restaurant
records, frozen source evidence, and the eight frozen queries. It does not
measure full geographic coverage, actual menus, current business operation,
or user satisfaction.

## Annotation decision rule

- Positive relevance and required source evidence: **[fill]**
- Negative relevance and required source evidence: **[fill]**
- Aliases, mixed cuisines, and ambiguous-query rules: **[fill]**
- Source hierarchy and whether external archived evidence is permitted: **[fill]**
- Missing metadata / insufficient evidence procedure: **[fill]**
- If unassessable judgments remain: **STOP; do not coerce to false.**
- Reviewer instructions tested on **separate fictional practice examples**:
  **[fill date/result]**

## Data and analysis plan

- Catalog size / pairs / development queries / test queries: **[verify]**
- Primary metric for positive queries: **binary nDCG@5**
- Secondary metrics: **Recall@5**, **MRR@5**
- No-match metric: **correct-empty rate**, separately reported
- Baselines: **BM25 vs lexical overlap**, fixed v0.18 implementations
- Paired uncertainty: **query-level bootstrap**, 2,000 resamples, seed 2026
- Plan JSON SHA-256, created before judgment outcomes: **[fill]**
- Development-only diagnostics and tuning policy: **[fill]**
- Held-out test release authorization and audit record: **[fill]**
- Publication policy for anonymized qrels, license, and human notes: **[fill]**

## Change log / deviations

| Date (UTC) | Change | Reason | Phase | Impact on interpretation |
| --- | --- | --- | --- | --- |
| [fill] | [fill] | [fill] | [fill] | [fill] |

## Approval

- Coordinator signature or independently verifiable timestamp: **[fill]**
- Approver confirms no held-out test metrics inspected: **[fill]**
