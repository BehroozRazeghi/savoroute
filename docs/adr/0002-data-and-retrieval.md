# ADR 0002 — Catalog IDs and lexical baselines

**Status:** Accepted · 2026-11-09

The first catalog uses a versioned JSON format and frozen Python records. Item IDs are unique within the catalog. Media records refer to those IDs explicitly; filenames and list positions have no linking semantics.

Two lexical baselines are retained: weighted token overlap and BM25 over a field-repeated document. BM25 computes document frequencies over the unfiltered catalog, then ranks the filtered candidates. This keeps term weights independent of the chosen metadata filter.

The implementation recomputes BM25 corpus statistics per query. That cost is acceptable for the 12-record fixture; a persistent index is needed before scaling. Neither baseline is semantic retrieval or calibrated relevance estimation.
