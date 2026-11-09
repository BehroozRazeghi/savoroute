# Notebooks

The notebooks provide a linear introduction to the installed package:

| File | Subject |
| --- | --- |
| `00_quickstart.ipynb` | Catalog objects and search output |
| `01_catalog_and_provenance.ipynb` | Schema constraints and media foreign keys |
| `02_lexical_retrieval.ipynb` | BM25, weighted overlap, and filters |
| `03_retrieval_evaluation.ipynb` | Query judgments, metrics, and retrieval failures |

```bash
python -m pip install -e ".[dev,notebooks]"
jupyter lab
```

The examples use bundled fictional data. No model download, remote service or API key is involved. Each notebook imports the production functions used by the library and CLI; algorithms are not maintained separately in notebook cells.
