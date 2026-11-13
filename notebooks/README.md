# Executable notebooks

These notebooks demonstrate SavoRoute's Python APIs using local fictional or synthetic inputs. They do not constitute independent real-world relevance measurements. Execute them from the repository root after installing `.[api,mcp,dev,notebooks]`.

| Notebook | Scope |
| --- | --- |
| 00 | [`00_quickstart.ipynb`](00_quickstart.ipynb) | Catalog quickstart |
| 01 | [`01_catalog_and_provenance.ipynb`](01_catalog_and_provenance.ipynb) | Catalog validation and provenance |
| 02 | [`02_lexical_retrieval.ipynb`](02_lexical_retrieval.ipynb) | Lexical retrieval and filters |
| 03 | [`03_retrieval_evaluation.ipynb`](03_retrieval_evaluation.ipynb) | Retrieval evaluation |
| 04 | [`04_structured_ingestion.ipynb`](04_structured_ingestion.ipynb) | Structured source ingestion |
| 05 | [`05_osm_sources_and_evaluation.ipynb`](05_osm_sources_and_evaluation.ipynb) | OSM ingestion and extraction evaluation |
| 06 | [`06_source_identity_and_updates.ipynb`](06_source_identity_and_updates.ipynb) | Source identity and revisions |
| 07 | [`07_identity_benchmark_evaluation.ipynb`](07_identity_benchmark_evaluation.ipynb) | Identity benchmark |
| 08 | [`08_image_ingestion.ipynb`](08_image_ingestion.ipynb) | Local image ingestion |
| 09 | [`09_multimodal_vector_index.ipynb`](09_multimodal_vector_index.ipynb) | Multimodal vector retrieval |
| 10 | [`10_item_level_fusion.ipynb`](10_item_level_fusion.ipynb) | Item-level rank fusion |
| 11 | [`11_dense_backend_and_benchmarks.ipynb`](11_dense_backend_and_benchmarks.ipynb) | Persistent vector indexes and synthetic benchmarks |
| 12 | [`12_review_and_recommend.ipynb`](12_review_and_recommend.ipynb) | Independent relevance review and catalog-grounded recommendations |
| 13 | [`13_real_data_study.ipynb`](13_real_data_study.ipynb) | Frozen OSM study |
| 14 | [`14_http_api.ipynb`](14_http_api.ipynb) | Read-only HTTP API |
| 15 | [`15_mcp_readonly_tools.ipynb`](15_mcp_readonly_tools.ipynb) | Local read-only MCP tools |
| 16 | [`16_web_app.ipynb`](16_web_app.ipynb) | Browser application |
| 17 | [`17_reviewed_catalog_evidence.ipynb`](17_reviewed_catalog_evidence.ipynb) | Reviewed catalog evidence |
| 18 | [`18_opt_in_visit_discovery.ipynb`](18_opt_in_visit_discovery.ipynb) | Opt-in visit suggestions |
| 19 | [`19_geography_and_reviewed_media.ipynb`](19_geography_and_reviewed_media.ipynb) | Geography and reviewed media |
| 20 | [`20_reviewer_grounded_statistical_evaluation.ipynb`](20_reviewer_grounded_statistical_evaluation.ipynb) | Query-level statistical evaluation |

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
jupyter lab
```

The CI workflow executes notebooks from their first cell on Python 3.11–3.13. Model-backed inference, independent human adjudication, real-world restaurant accuracy, and production security are not established by these notebooks.
