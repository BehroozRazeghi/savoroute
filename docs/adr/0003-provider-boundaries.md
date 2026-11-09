# ADR 0003 — Capability-specific model interfaces

**Status:** Accepted · 2026-11-09

The provider package declares separate protocols for text generation, image captioning, text embeddings, and shared text/image embeddings. Core data and retrieval modules have no dependency on a model SDK.

Provider names alone do not establish a model's supported operations. Concrete adapters will be added with tests and explicit model configuration during the ingestion and multimodal stages. No adapters are included in version `0.1.0`.
