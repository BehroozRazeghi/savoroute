# Grounded recommendations

`DiscoveryService.recommend()` combines existing item-level rank fusion with metadata-backed preference reranking. The CLI exposes the same code through `savoroute recommend`. No LLM is needed to generate recommendations or explanations.

## Ranking and decision policy

1. Validate query parameters, preference weights, catalog identities, and the optional vector index.
2. Apply existing hard filters to catalog records **before retrieval**. Unknown fields do not satisfy required filters; `vegan-options` is not equivalent to `vegan`.
3. Generate a bounded candidate ranking through BM25 and optionally text/image vectors with weighted reciprocal rank fusion. Only catalog-backed item IDs are eligible.
4. Remove explicitly excluded item IDs. For retrieved candidates, compute a soft preference multiplier using only literal catalog cuisine and dietary-tag matches:

   \[\mathrm{score}(i) = \mathrm{RRF}(i)\left(1+\lambda\frac{m(i)}{|P|}\right),\]

   where `P` is the set of requested soft-preference values, `m(i)` counts matches recorded in the catalog, and `0 <= lambda <= 1`. When `P` is empty, the multiplier is one. These scores are ranking utilities, **not** calibrated probabilities.
5. Sort by adjusted score, then original RRF score, then stable item ID. Preserve retrieval-source ranks and source record IDs for auditability.
6. Return source name/URL and literal catalog attributes, including recorded dietary tags and ingredients. No unsupported claims about restaurant operating hours, menu availability, ratings, health benefits, allergens, or prices are generated.

The service distinguishes `no_eligible_items`, `no_retrieval_matches`, and `ok`. `eligible_items` refers to metadata-filtered, nonexcluded catalog records; `no_retrieval_matches` does not imply that no suitable item exists outside the catalog.

## Usage

```bash
savoroute recommend "spicy tofu" --kind recipe --diet vegan \
  --prefer-cuisine Japanese --limit 3 --json

# Existing compatible CLIP vector index, optional:
savoroute recommend "mushroom pasta" \
  --catalog data/generated/m2b/media/catalog.json \
  --index data/generated/m2b/sqlite-bundle \
  --kind recipe --json
```

Restaurant dietary options, incomplete ingredient lists, and cross-contamination practices are **not** allergen-safety evidence. The service does not support allergen-safe recommendations. Do not interpret its recorded tags as verified dietary certifications. It does not provide reservations, live hours, real-time inventory, or pricing.

## Verification boundary

Offline tests cover item grounding, ranking evidence, hard filters, empty results, exclusions, stable decisions, CLI serialization, and synthetic annotations. They do not establish recommendation utility or correctness on real users or venues. Real-world relevance must be evaluated with the separate reviewed judgment workflow; user studies and safety reviews are future work.
