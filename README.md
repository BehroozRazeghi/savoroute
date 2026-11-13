# Savoroute

**Local-first restaurant discovery with inspectable retrieval and evaluation.**

Savoroute searches a configured catalog of restaurants, ranks matching records, and shows the recorded attributes and retrieval evidence behind each result. It also supports recipes. The same Python services power a browser application, command-line tools, a read-only HTTP API, and local MCP tools.

Savoroute is an **experimental application and research toolkit**, not a live restaurant directory. The bundled catalog is fictional; real data must be imported separately.

## Run locally

Requires Python 3.11 or later. From a clone of this repository:

```bash
python -m pip install -e ".[api]"
savoroute web serve --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. The default application uses fictional restaurants and recipes. API documentation is available at **http://127.0.0.1:8000/docs**.

To serve an existing catalog instead:

```bash
savoroute web serve --catalog /path/to/catalog.json --host 127.0.0.1 --port 8000
```

The catalog is selected when the server starts. No account, GPU, model download, or external data service is required for the default demo.

## Capabilities

| Area | Available behavior |
| --- | --- |
| Discovery | Lexical catalog search, exact metadata filters, and catalog browsing |
| Ranking | BM25 and token-overlap baselines; optional text/image vector retrieval and weighted reciprocal-rank fusion |
| Recommendations | Reranking of retrieved catalog items using explicit cuisine and dietary-tag preferences |
| Data | Validated JSON catalogs, OSM snapshot import, source identity reconciliation, and source references |
| Images and menus | Local image ingestion; separately reviewed media and menu references where configured |
| Location | Approximate nearby search against an explicitly supplied, matching OSM snapshot |
| Review | Opt-in visit suggestions and independent relevance-annotation workflows |
| Evaluation | Frozen study inputs, lexical baselines, retrieval metrics, and query-level paired bootstrap intervals |
| Interfaces | Local web app, Python library, CLI, HTTP API, and read-only stdio MCP server |

Vector retrieval requires a compatible index and, for model inference, an optional embedding adapter. **It is not enabled by the default demo.** Recommendations use recorded catalog values; they are not learned from user behavior and their scores are not probabilities.

## Data and evaluation boundaries

- Catalog entries can be missing, outdated, or incorrect. Source attribution does not verify a restaurant's current status.
- Cuisine and dietary tags are recorded fields, **not** allergen or food-safety guarantees. Prices, opening hours, availability, and reservations are not verified.
- Geographic results are straight-line distances to OSM reference geometry, not travel times or verified entrances.
- Reviewed references and local image packages require operator-supplied rights information; software checks do not establish legal permission.
- The included benchmarks and notebook demonstrations use fictional data. The Boston OSM pilot has a frozen collection and evaluation workflow, but **no independently adjudicated real-world results are included**. Do not infer real-world retrieval quality from the test suite.

## Work with the library

```bash
savoroute search "spicy tofu noodles" --kind recipe
savoroute recommend "spicy tofu" --kind recipe --prefer-cuisine Japanese --json
savoroute --help
```

The API and MCP server are optional local interfaces. Their setup, limits, and security boundaries are documented separately; neither is a production deployment configuration.

## Documentation

- [Documentation index](docs/README.md) — start here for API, architecture, data and evaluation workflows
- [Architecture](docs/architecture.md) · [Web application](docs/web-app.md) · [HTTP API](docs/http-api.md) · [MCP](docs/mcp-server.md)
- [Data and fixtures](data/README.md) · [Notebooks](notebooks/README.md) · [Scripts](scripts/README.md)
- [Product-quality plan](docs/product-quality-plan.md) · [Change history](CHANGELOG.md)

## Development

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
python -m pytest -q
python -m ruff check src tests scripts
node --test tests/web/*.test.mjs
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete CI checks and contribution requirements. The original code and documentation are licensed under [MIT](LICENSE); third-party source data, models, and images retain their respective terms.
