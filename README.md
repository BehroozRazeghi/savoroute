# Savoroute

**Food discovery and recommendation · Python · Jupyter · CLI · HTTP API · MCP**

Savoroute is a food-discovery project developed as an installable Python library and a sequence of executable notebooks. The notebooks explain the algorithms and data flow; the CLI, optional versioned HTTP API, and local read-only MCP tools use the same library. A consumer web application is planned, not yet implemented.

Version `0.10.0` added a strict, two-reviewer relevance-annotation workflow with separate review sheets and deterministic, source-grounded recommendations. Workbooks are catalog-fingerprint bound and cannot be exported with missing labels or unresolved disagreements. Recommendations combine the existing retrieval sources with explicit metadata filters and inspectable source evidence. The JSON/SQLite vector backends and optional FAISS HNSW backend are unchanged. No independently reviewed real-world relevance dataset or live restaurant verification is included.

Version `0.11.0` adds a frozen OpenStreetMap evaluation-study bundle with immutable source and query snapshots, blinded review materials, integrity verification, and evaluation against a completed adjudicated workbook. No human-annotated real-world benchmark is distributed with the repository. See [real-data evaluation](docs/real-data-evaluation.md).

Version `0.12.0` adds an opt-in, read-only `/v1` HTTP API for catalog browsing,
search, item-level ranking, and evidence-backed recommendations. The server loads
an operator-chosen catalog and optional trusted index; request clients cannot
select file paths or trigger model downloads. See [HTTP API v1](docs/http-api.md).

Version `0.13.0` adds six read-only MCP tools over local stdio using the official MCP Python SDK v2. Their results and limits come from the existing versioned HTTP contracts, executed in-process without a web listener. This is intended for trusted local agent hosts, not a publicly deployed MCP service. See [MCP server](docs/mcp-server.md).

**Version `0.14.0`** adds a responsive, local-first web app over the same HTTP v1 endpoints. Search the catalog, apply filters and preferences, browse saved restaurants/recipes, inspect sources and retrieval evidence, and view grounded recommendations. The browser never fabricates records or downloads models. [Web application guide](docs/web-app.md).

```bash
python -m pip install -e ".[api]"
savoroute web serve --host 127.0.0.1 --port 8000
# Visit http://127.0.0.1:8000/ for the web app or /docs for the API.
# To use your imported OSM catalog:
savoroute web serve --catalog data/generated/real-pilot/catalog.json --port 8001
```


## Installation

Python 3.11 or later is required. The default demo and labeled ingestion run without credentials, a GPU, or a database server.

```bash
python -m venv .venv
source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,notebooks]"

savoroute demo
savoroute search "spicy tofu noodles" --kind recipe
savoroute search "vegan" --kind recipe --diet vegan --json
savoroute validate
savoroute rank search "mushroom pasta" --kind recipe --json
savoroute rank evaluate --json
savoroute rank evaluate --benchmark data/sample/relevance_challenge_v1.json --json
savoroute recommend "spicy tofu" --kind recipe --diet vegan --prefer-cuisine Japanese --json
savoroute judgments prepare --catalog data/sample/catalog.json \
  --queries data/sample/relevance_query_set_v1.json \
  --output data/generated/relevance_workbook.json
# Then `savoroute judgments split` for separate reviewer files, `merge` completed
# reviews, adjudicate disagreements, and run `judgments finalize`. See docs.
savoroute backend benchmark --engine sqlite --records 1000 --dimension 32 --queries 20
savoroute evaluate --method both --at-k 5
savoroute ingest --sources data/sample/ingestion_sources.json \
  --output data/generated/catalog.json --provenance data/generated/evidence.json
savoroute osm import --input data/sample/osm_overpass_fixture.json \
  --synthetic-fixture --output data/generated/osm_demo.json \
  --report data/generated/osm_report.json
savoroute evaluate-extraction --gold data/sample/extraction_gold.json \
  --predictions data/generated/evidence.json --json
savoroute identity evaluate --benchmark data/sample/identity_pairs_fixture.json --json
savoroute media ingest --manifest data/sample/image_manifest.json \
  --output-dir data/generated/media-demo
# Optional real CLIP run (requires: pip install -e ".[multimodal]")
# Model weights must already be cached unless --allow-download is specified.
# savoroute vectors build --catalog data/generated/media-demo/catalog.json \
#   --output data/generated/vectors.json --revision <model-commit-hash>
# savoroute vectors search --index data/generated/vectors.json \
#   --catalog data/generated/media-demo/catalog.json --text "mushroom pasta" \
#   --target image --revision <same-model-commit-hash>
python -m pytest
jupyter lab
```

The CLI also accepts external catalog and benchmark files:

```bash
savoroute validate --catalog data/sample/catalog.json
savoroute search "pasta" --catalog data/sample/catalog.json --kind restaurant
savoroute evaluate --benchmark data/sample/relevance_benchmark.json --json
```

## Optional MCP tools (local stdio)

```bash
python -m pip install -e ".[mcp]"
savoroute mcp serve  # host launches process and speaks MCP on stdin/stdout
savoroute mcp serve --catalog data/generated/real-pilot/catalog.json
```

The command stays quiet while waiting for an MCP client. See the [local MCP guide](docs/mcp-server.md) for the six tools, host configuration, security boundaries, and validation steps.

## Optional HTTP API

```bash
python -m pip install -e ".[api]"
savoroute api serve --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000/docs
```

To serve your previously collected OSM catalog, supply an explicit local path:

```bash
savoroute api serve --catalog data/generated/real-pilot/catalog.json
```

The default uses the bundled fictional catalog. For optional API-key authentication,
set `SAVOROUTE_API_KEY` before launching. Non-loopback binding requires a key, but
public deployment additionally requires TLS, request limits, rate limits and privacy
controls. This is a local development server, not a production deployment.
[HTTP contracts and examples](docs/http-api.md).

## Evaluation and recommendations

Relevance workbooks are generated without labels and split into separate reviewer files. Completed reviews are merged, disagreements adjudicated, and all eligible query–item pairs finalized before development and test benchmarks can be exported. See [relevance workflow](docs/relevance-workflow.md).

Recommendations contain only catalog items and recorded metadata; the output includes source references, retrieval ranks, and explicit limitations. No dietary safety, opening-hours, or availability claims are inferred. See [grounded recommendations](docs/grounded-recommendations.md).

## Notebooks

| Notebook | Content |
| --- | --- |
| [00 — Quickstart](notebooks/00_quickstart.ipynb) | Load the catalog and perform a search |
| [01 — Catalog and provenance](notebooks/01_catalog_and_provenance.ipynb) | Validate records and inspect item/media references |
| [02 — Lexical retrieval](notebooks/02_lexical_retrieval.ipynb) | Compare weighted token overlap and BM25; apply metadata filters |
| [03 — Retrieval evaluation](notebooks/03_retrieval_evaluation.ipynb) | Calculate Recall@k, MRR@k, nDCG@k, and the empty-result rate |
| [04 — Structured ingestion](notebooks/04_structured_ingestion.ipynb) | Validate source records, extract fields, audit literal evidence spans, and admit items |
| [05 — OSM sources and evaluation](notebooks/05_osm_sources_and_evaluation.ipynb) | Import a synthetic Overpass-format snapshot, review duplicate candidates, and compute field metrics |
| [06 — Source identity and updates](notebooks/06_source_identity_and_updates.ipynb) | Bootstrap source bindings, reconcile updates, review conflicts, and check idempotency |
| [07 — Identity candidate evaluation](notebooks/07_identity_benchmark_evaluation.ipynb) | Inspect pairwise review metrics, source-version ordering, and an unlabeled annotation worksheet |
| [08 — Image ingestion](notebooks/08_image_ingestion.ipynb) | Validate local image assets, normalize PNGs, inspect hashes, and isolate optional CLIP inference |
| [09 — Multimodal vector index](notebooks/09_multimodal_vector_index.ipynb) | Build an exact cosine index, search text/image vectors, and evaluate labeled cross-modal queries |
| [10 — Item-level rank fusion](notebooks/10_item_level_fusion.ipynb) | Combine BM25 and per-item vector rankings through RRF; evaluate item-level results |
| [11 — Persistent vectors and benchmarks](notebooks/11_dense_backend_and_benchmarks.ipynb) | Convert exact vectors to SQLite, check agreement, evaluate RRF, and measure local latency |
| [12 — Relevance review and recommendations](notebooks/12_review_and_recommend.ipynb) | Prepare exhaustive review pairs, validate synthetic mock decisions, and inspect grounded recommendations |
| [13 — Reproducible OSM studies](notebooks/13_real_data_study.ipynb) | Freeze and verify a study using a fictional OSM fixture |
| [14 — Versioned HTTP API](notebooks/14_http_api.ipynb) | Exercise the API and OpenAPI contract in process, without network calls |

All fifteen notebooks (00–14) run offline and import functions from `src/savoroute/`. They are examples of the library's behavior, not separate implementations. See [notebooks/README.md](notebooks/README.md).

## Multimodal vectors

The optional CLIP adapter encodes both text and local images into a shared vector space. The index stores normalized vectors in JSON with stable `text:<item_id>` and `image:<media_id>` IDs, model identity, content hashes, and a catalog fingerprint. An index is rejected if it is queried with an incompatible model or a modified catalog. Exact cosine search supports modality and item-kind filters; item-level max pooling is available with `--unique-items`.

The [vector indexing guide](docs/vector-index.md) documents input requirements, CLI commands, benchmarks, reproducibility constraints, and the distinctions from the IBM course exercises. Inference and retrieval quality using real model weights have not yet been measured.

## Persistent vector backends

`backend build` converts the JSON reference index into an immutable SQLite bundle. `backend search` queries the bundle by a precomputed vector; `rank search --index <bundle-directory>` reuses the same fusion service with an optional model encoder. The `.[ann]` extra enables FAISS HNSW, whose recall and latency require measurement on the target machine. Larger streaming vector sets use the Python `write_dense_index` API; the JSON conversion command remains limited by the JSON format's record cap. The local SQLite exact engine is still O(Nd). See [persistent vector retrieval](docs/dense-index.md) and [relevance annotations](docs/relevance-annotation.md).

## Item-level retrieval

`search_fused()` combines BM25, text-vector, and image-vector rankings into one list of catalog items. It uses reciprocal rank fusion rather than mixing native BM25 and cosine scores. Ranking evidence retains the input record ID, rank and native score from each source. Multiple images for the same catalog item count once within the image source. Hard metadata filters apply to all sources. The CLI exposes `savoroute rank search` and `savoroute rank evaluate` (lexical-only without an index, hybrid when an index is supplied). RRF scores are not relevance probabilities and there is no calibrated rejection threshold. See [rank fusion](docs/rank-fusion.md).

## Python API

```python
from savoroute.data.catalog import load_catalog
from savoroute.retrieval.lexical import SearchFilters, search_catalog

catalog = load_catalog()
hits = search_catalog(
    catalog.items,
    "spicy tofu noodles",
    SearchFilters(kind="recipe"),
    method="bm25",
    limit=3,
)
for hit in hits:
    print(hit.item.item_id, hit.item.title, hit.score)
```

`load_catalog()` reads a JSON resource distributed with the package and works outside the repository. `DiscoveryService` provides the search use case for CLI callers; catalog validation and benchmark evaluation are also available as library functions.

## Repository structure

```text
savoroute/
├── src/savoroute/
│   ├── domain/          # immutable catalog records
│   ├── data/            # JSON parsing, validation and resource loading
│   ├── retrieval/       # BM25, exact/ANN vector search, SQLite and RRF
│   ├── evaluation/      # retrieval and extraction metrics
│   ├── ingestion/       # text extraction, evidence checks, OSM import
│   ├── media/           # local image validation and normalized exports
│   ├── identity/        # source bindings and explicit identity links
│   ├── providers/       # interfaces; OpenAI/Ollama text and optional CLIP adapters
│   ├── services/        # discovery, ingestion and OSM reconciliation
│   ├── resources/       # packaged synthetic fixtures
│   └── cli.py           # command-line entry point
├── notebooks/           # executable lessons
├── scripts/             # batch evaluation entry point
├── data/sample/         # readable copies of packaged fixtures
├── docs/                # architecture, data contract and roadmap
├── tests/               # offline unit and command-line tests
└── pyproject.toml
```

The catalog uses stable `item_id` identifiers for recipes and restaurants. Media records refer to `media.item_id`. The bundled catalog has no images; two original illustrations are supplied separately to demonstrate image ingestion. BM25 uses corpus-wide document frequencies and a field-repetition heuristic. Neither ranker supports semantic matching; neither returns calibrated relevance probabilities. See [retrieval and evaluation](docs/evaluation.md) for formulas and limitations.

## Development

The [development roadmap](docs/roadmap.md) separates the implemented ingestion, media handling, lexical retrieval, and exact vector-index foundation from persistent indexing, implemented recommendation services, and planned MCP, HTTP, and web interfaces. Image ingestion is documented in [docs/media-ingestion.md](docs/media-ingestion.md). Text ingestion is documented in [docs/ingestion.md](docs/ingestion.md); the OSM adapter and extraction benchmark in [docs/osm-and-extraction-evaluation.md](docs/osm-and-extraction-evaluation.md). Native mobile development remains a separate product decision. Empty application directories are not included before there is application code.

Source identities are stored separately from the version-1 catalog. `osm sync` updates OSM-owned records when the source binding and previous catalog state are unambiguous; proposed cross-source matches are review-only. The implementation does not delete entries absent from a bounded snapshot. See [source identity and updates](docs/entity-identity-and-updates.md) and [identity candidate evaluation](docs/identity-benchmark.md).

Technical notes: [review and recommendation decision](docs/adr/0006-relevance-judgments-and-grounded-recommendations.md) · [text ingestion](docs/ingestion.md) · [architecture](docs/architecture.md) · [catalog contract](docs/data-contract.md) · [provider interfaces](docs/provider-strategy.md) · [evaluation](docs/evaluation.md) · [design history](docs/comparison.md).

The annotated identity fixture is synthetic; its error rates cannot be generalized to real sources. The `identity prepare-osm` command generates an unlabeled worksheet from a saved Overpass snapshot for independent manual review.

The committed sample records are fictional and contain no live listings, verified dietary information, restaurant availability, or real user data. The optional fetch command can retrieve real OSM records; it is not run by the tests. Original course materials and external assets are not redistributed. The MIT license covers this repository's original source and documentation, not third-party content.

See [CHANGELOG.md](CHANGELOG.md) for release notes and [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and contribution scope.

## Reviewed source references (v0.15.0)

External menu links, image references, cuisine evidence and source notes require explicit
manual approval before the web app can show them. The immutable-by-workflow evidence
sidecar binds to one canonical catalog digest. It does not fetch remote content,
verify copyright ownership, mutate retrieval fields, or represent dietary safety.
See [reviewed evidence workflow](docs/reviewed-evidence.md) and
[Notebook 17](notebooks/17_reviewed_catalog_evidence.ipynb).

```bash
savoroute evidence prepare --catalog catalog.json --proposals candidates.json --output review.json
# Inspect each source and complete reviewer decisions.
savoroute evidence publish --catalog catalog.json --proposals candidates.json --review review.json --output approved.json
savoroute web serve --catalog catalog.json --evidence approved.json
```


## Opt-in local visit suggestions (v0.16.0)

`visits suggest` clusters **user-selected photo metadata** (opaque ID, timezone-aware timestamp, latitude/longitude) and proposes nearby restaurants using the **existing** OSM identity bindings. It reads no photos and requests no camera-roll access. A separate review sheet is required; nothing is confirmed automatically. `visits finalize` verifies the review digest and exports reduced confirmed history without photo IDs or GPS coordinates.

The web server also serves `/visits-review`, a browser-local review page whose selected files are **not uploaded**. Source data and review decisions are sensitive—keep them out of Git. See [the operator guide](docs/opt-in-visit-discovery.md) and [ADR 0012](docs/adr/0012-local-visit-suggestions.md). The included example is entirely fictional.


### v0.17 — Nearby exploration and reviewed local images

Configure a saved matching OSM snapshot to enable approximate coordinate-aware restaurant browsing:

```bash
savoroute web serve --catalog data/generated/real-pilot/catalog.json \
  --osm /path/to/saved-overpass-snapshot.json --port 8001
```

Use `savoroute media package-reviewed` only with a completed v0.15 evidence-review bundle and local images whose redistribution/derivative rights you have separately established. Media is served read-only with source, license, attribution and modifications. A missing menu reference is reported as `not_recorded`, **not** `no menu`. Details and JSON manifest schema: [Geographic discovery and reviewed local media](docs/geography-and-reviewed-media.md).


### v0.18.0 · Reviewer-grounded retrieval study

The local-only `/study-review` page helps independent annotators review frozen query–restaurant pairs without seeing retrieval rankings or each other's judgments. `savoroute study audit` checks reviewer-sheet progress, `study plan` fixes the comparison protocol, and `study analyze` reports query-level paired bootstrap intervals and item-level error diagnostics **only after full human adjudication**. Real-world OSM relevance labels are **not bundled or generated**. See [the study methods](docs/statistical-relevance-study.md) and Notebook 20.
