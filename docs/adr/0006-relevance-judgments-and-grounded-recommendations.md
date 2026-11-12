# ADR 0006 — Reviewable relevance judgments and catalog-grounded recommendations

**Status:** Accepted for v0.10.0

## Decision

Relevance evaluation uses a bounded, exhaustive binary query–item worksheet bound to a frozen catalog fingerprint. Two reviewers receive separate blank files; the merge validates pair coverage and provenance, preserves both decisions, and leaves disagreements for explicit adjudication. Development and test benchmarks are exported only after all eligible pairs have valid final decisions. Annotator independence and correctness remain operational requirements, not software guarantees.

Recommendation outputs are deterministic transformations of catalog-backed retrieval results. Hard metadata constraints are enforced before retrieval; explicit exclusions and bounded soft-preference bonuses are applied afterward. Outputs retain canonical item IDs, source metadata, and per-source ranking evidence. No generative system is involved in producing factual explanations.

## Rationale

A catalog of moderate size can support exhaustive review without assuming that unjudged candidates are irrelevant. Separating reviewer files avoids sharing peer decisions during initial labeling. Persisting both independent decisions and adjudication makes label changes auditable.

Recipes and restaurant records contain incomplete and potentially stale attributes. Deterministic filtering and citation of recorded fields is more appropriate than language-model-generated menu, allergen, or availability claims. Preference bonuses operate only on retrieved candidates; retrieval scores are never presented as calibrated probabilities.

## Tradeoffs

Exhaustive review scales with queries times eligible catalog records. Larger-scale evaluation requires a separately specified pooling protocol and explicit treatment of unjudged items. Catalog metadata cannot establish dietary safety or source truth. The ranking policy is a transparent baseline rather than a learned recommender; real-user utility and independent real-data accuracy are not yet measured.
