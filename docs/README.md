# Documentation

Use the [project README](../README.md) to start Savoroute. This index groups reference material by task; the [changelog](../CHANGELOG.md) records release history.

## Using Savoroute

| Task | Guide |
| --- | --- |
| Start the browser application | [Web app](web-app.md) |
| Use the versioned API | [HTTP API](http-api.md) |
| Connect a local MCP host | [MCP server](mcp-server.md) |
| Inspect data fields and validation | [Catalog contract](data-contract.md) |
| Import or update OSM records | [OSM ingestion](osm-and-extraction-evaluation.md) · [Identity and updates](entity-identity-and-updates.md) |
| Inspect reviewed menu and image references | [Reviewed evidence](reviewed-evidence.md) · [Geography and media](geography-and-reviewed-media.md) |
| Review potential visits | [Opt-in visit workflow](opt-in-visit-discovery.md) |

## Retrieval and evaluation

| Topic | Guide |
| --- | --- |
| Retrieval methods and metrics | [Evaluation](evaluation.md) · [Rank fusion](rank-fusion.md) · [Dense vectors](dense-index.md) |
| Preference reranking | [Recommendations](grounded-recommendations.md) |
| Independent relevance judgments | [Relevance workflow](relevance-workflow.md) |
| Frozen real-data study | [Real-data study](real-data-evaluation.md) · [Statistical methods](statistical-relevance-study.md) |
| Boston pilot operations | [Pilot execution protocol](studies/boston-pilot-execution.md) |

## Engineering

- [Current architecture and boundaries](architecture.md)
- [Product-quality priorities and acceptance criteria](product-quality-plan.md)
- [Architecture decision records](adr/)
- [Notebooks](../notebooks/README.md) · [Developer scripts](../scripts/README.md)

Some specialized documents describe earlier implementation stages or design alternatives. Treat their version-specific status statements as historical; the current architecture, public interfaces, and tests take precedence. No notebook, review sheet, or synthetic benchmark establishes independent real-world effectiveness.
