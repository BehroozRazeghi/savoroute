# Educational source review

The original archive contains eight notebooks and four lab instruction files spanning extraction, indexing, agents, user interfaces, and MCP. The examples informed the project scope. Their code, datasets, and images are not included in this repository.

| Lab area | Engineering issue identified | Savoroute approach |
| --- | --- | --- |
| Text extraction | Example outputs are not a stable validated data contract | Explicit parser and evidence-bearing ingestion records |
| Image processing | Image ownership and item association require stable identifiers | Media-to-item references and source metadata |
| Indexing | Positional ordering is not a reliable join between assets and records | Canonical IDs, idempotent index updates |
| Multimodal retrieval | Score conventions depend on index configuration | Per-index metric definitions and ID-based fusion |
| Agent orchestration | Some examples substitute model-generated search results for actual retrieval | Search service returns catalog-backed items |
| Chat interface | Demonstration actions do not provide persisted application behavior | Shared services with tested read/write operations when introduced |
| MCP | Educational examples predate the 2026 protocol update | Implementation against a selected supported MCP version |

The original v0.1.0 offline foundation addressed schema validation, lexical retrieval, and evaluation. Subsequent milestones added extraction and OSM data processing; image processing, vector retrieval, agents, MCP, and user-facing applications are not yet implemented.
