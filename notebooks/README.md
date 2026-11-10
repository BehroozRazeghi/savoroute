# Notebooks

The notebooks provide a linear introduction to the installed package:

| File | Subject |
| --- | --- |
| `00_quickstart.ipynb` | Catalog objects and search output |
| `01_catalog_and_provenance.ipynb` | Schema constraints and media foreign keys |
| `02_lexical_retrieval.ipynb` | BM25, weighted overlap, and filters |
| `03_retrieval_evaluation.ipynb` | Query judgments, metrics, and retrieval failures |
| `04_structured_ingestion.ipynb` | Source records, quoted extraction evidence, catalog admission |
| `05_osm_sources_and_evaluation.ipynb` | OSM-format import, duplicate review, and extraction metrics |

```bash
python -m pip install -e ".[dev,notebooks]"
jupyter lab
```

The examples use bundled fictional data. Notebook execution requires no model download, remote service, or API key. Model-backed extraction is covered separately in the ingestion guide. Each notebook imports the production functions used by the library and CLI; algorithms are not maintained separately in notebook cells.

- `06_source_identity_and_updates.ipynb`: source registry, controlled updates, conflict review, and replay behavior.
