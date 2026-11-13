# Notebooks

The notebooks follow the Savoroute implementation from data loading through retrieval, evaluation, and recommendations. Every notebook calls the installed Python package rather than maintaining a second implementation.

| Notebook | Topic |
| --- | --- |
| `00_quickstart.ipynb` | Catalog inspection and search |
| `01_catalog_and_provenance.ipynb` | Schema validation and media references |
| `02_lexical_retrieval.ipynb` | BM25, weighted overlap, and filters |
| `03_retrieval_evaluation.ipynb` | Query judgments and retrieval metrics |
| `04_structured_ingestion.ipynb` | Text extraction with quoted evidence |
| `05_osm_sources_and_evaluation.ipynb` | OSM import, duplicate review, and extraction metrics |
| `06_source_identity_and_updates.ipynb` | Source registry and controlled updates |
| `07_identity_benchmark_evaluation.ipynb` | Source versioning and entity-matching evaluation |
| `08_image_ingestion.ipynb` | Image normalization and provenance |
| `09_multimodal_vector_index.ipynb` | Joint embeddings and cross-modal retrieval |
| `10_item_level_fusion.ipynb` | BM25 and text/image rank fusion |
| `11_dense_backend_and_benchmarks.ipynb` | SQLite/FAISS retrieval and synthetic latency benchmarks |
| `12_review_and_recommend.ipynb` | Independent-review workflow and grounded recommendations |
| `13_real_data_study.ipynb` | Reproducible OSM study setup, integrity checks, and simulated review |
| `14_http_api.ipynb` | Read-only FastAPI interface, request validation, and service parity |
| `15_mcp_readonly_tools.ipynb` | Local read-only MCP tools and HTTP contract parity |
| `16_web_app.ipynb` | Packaged browser interface, API parity, and provenance-backed results |

```bash
python -m pip install -e ".[dev,notebooks]"
jupyter lab
```

The notebooks use fictional, local fixtures for CI and require no API keys or model downloads. Optional model-backed examples are described in their corresponding guides. **Notebooks 13–15 demonstrate infrastructure with synthetic inputs; they do not contain independent human judgments or a real-world performance result.**

- `17_reviewed_catalog_evidence.ipynb` — explicit proposal/review/publish workflow and HTTP parity (fictional assertions only).

- `18_opt_in_visit_discovery.ipynb` — offline selected metadata → OSM identity matching → review simulation → private confirmed history (fictional records only).

- `19_geography_and_reviewed_media.ipynb` — fictional OSM nearby discovery, local image publication bound to manually reviewed evidence, HTTP menu-status contracts.
