# 0004 — Local-first image ingestion

Status: Accepted (`0.6.0`)

## Context

The catalog stores media references but previously had no image-file processing or provenance workflow. Automatically downloading images would introduce usage-rights, security, and reproducibility concerns before there is an acquisition policy.

## Decision

The first media pipeline accepts only explicit local files named in a versioned manifest. It validates catalog item references, requires operator-supplied rights metadata, bounds image decoding, and writes normalized PNGs. Original-file and normalized-file SHA-256 hashes are recorded separately. Catalog media URIs are relative to the output directory. A new directory is published only after the entire batch has been prepared.

Embedding is a separate optional provider capability. The image ingestion path does not load a model or require network access.

## Consequences

The export is portable and can be exercised in offline notebooks and CI. Rights fields are declarations, not legal clearance. Image decoding is not sandboxed. The initial implementation requires a catalog without prior media; source updates, incremental image batches, persistent vector representations, and live image acquisition are separate design work.
