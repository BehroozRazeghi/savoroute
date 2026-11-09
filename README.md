# Savoroute

**Food discovery and recommendation · Python · Jupyter · CLI**

Savoroute is a food-discovery project developed as an installable Python library and a sequence of executable notebooks. The notebooks explain the algorithms and data flow; the CLI uses the same library. An HTTP API and user-facing application are planned after the retrieval and recommendation services are established.

Version `0.1.0` provides an **offline retrieval baseline**, not a multimodal recommendation system. It includes a fictional catalog of six restaurants and six recipes, schema validation, metadata filtering, two lexical rankers, and an evaluation set with 16 synthetic queries. There are no model calls, image processing, vector indexes, agents, MCP services, or applications in this release.

## Installation

Python 3.11 or later is required. The demo runs without credentials, a GPU, or a database server.

```bash
python -m venv .venv
source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,notebooks]"

savoroute demo
savoroute search "spicy tofu noodles" --kind recipe
savoroute search "vegan" --kind recipe --diet vegan --json
savoroute validate
savoroute evaluate --method both --at-k 5
python -m pytest
jupyter lab
```

The CLI also accepts external catalog and benchmark files:

```bash
savoroute validate --catalog data/sample/catalog.json
savoroute search "pasta" --catalog data/sample/catalog.json --kind restaurant
savoroute evaluate --benchmark data/sample/relevance_benchmark.json --json
```

## Notebooks

| Notebook | Content |
| --- | --- |
| [00 — Quickstart](notebooks/00_quickstart.ipynb) | Load the catalog and perform a search |
| [01 — Catalog and provenance](notebooks/01_catalog_and_provenance.ipynb) | Validate records and inspect item/media references |
| [02 — Lexical retrieval](notebooks/02_lexical_retrieval.ipynb) | Compare weighted token overlap and BM25; apply metadata filters |
| [03 — Retrieval evaluation](notebooks/03_retrieval_evaluation.ipynb) | Calculate Recall@k, MRR@k, nDCG@k, and the empty-result rate |

All four notebooks run offline and import functions from `src/savoroute/`. They are examples of the library's behavior, not separate implementations. See [notebooks/README.md](notebooks/README.md).

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
│   ├── retrieval/       # tokenization, filters, overlap and BM25
│   ├── evaluation/      # query judgments and ranking metrics
│   ├── providers/       # capability interfaces; no adapters yet
│   ├── services/        # discovery use case
│   ├── resources/       # packaged synthetic fixtures
│   └── cli.py           # command-line entry point
├── notebooks/           # executable lessons
├── scripts/             # batch evaluation entry point
├── data/sample/         # readable copies of packaged fixtures
├── docs/                # architecture, data contract and roadmap
├── tests/               # offline unit and command-line tests
└── pyproject.toml
```

The catalog uses stable `item_id` identifiers for recipes and restaurants. Optional media records reference an item through `media.item_id`; the current dataset includes no images. BM25 uses corpus-wide document frequencies and a field-repetition heuristic. Neither ranker supports semantic matching; neither returns calibrated relevance probabilities. See [retrieval and evaluation](docs/evaluation.md) for formulas and limitations.

## Development

The implementation sequence is recorded in [docs/roadmap.md](docs/roadmap.md): structured ingestion, image/text embeddings, indexed retrieval, grounded recommendations, MCP and HTTP interfaces, then a responsive web application. Native mobile development remains a separate product decision. Empty application directories are not included before there is application code.

Technical notes: [architecture](docs/architecture.md) · [catalog contract](docs/data-contract.md) · [provider interfaces](docs/provider-strategy.md) · [evaluation](docs/evaluation.md) · [design history](docs/comparison.md).

The examples are fictional and contain no live listings, verified dietary information, restaurant availability, or real user data. Original course materials and external assets are not redistributed. The MIT license covers this repository's original source and documentation, not third-party content.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and contribution scope.
