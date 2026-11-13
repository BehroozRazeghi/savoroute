# Contributing

SavoRoute is a developer-preview research application. Core catalog, retrieval, and recommendation behavior belongs in `src/savoroute/`; the web app, API, CLI, and local MCP bridge must reuse these services rather than add inconsistent ranking rules.

## Before opening a pull request

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
python -m pytest -q
python -m ruff check src tests scripts
node --input-type=module --check < src/savoroute/web/static/app.js
node --test tests/web/*.test.mjs
```

CI also executes every notebook from its first cell on Python 3.11–3.13. When changing a notebook, execute it from the repository root and remove saved private data or unintended outputs.

Use a focused branch and pull request. Explain behavior changes, tests run, and any optional checks that could not be executed. Do not merge while required CI checks are failing or pending. Keep the default demo runnable without network access, credentials, or downloaded models.

## Data and evidence policy

- Never commit credentials, user photos, user visit history, private review files, or `data/generated/`.
- Use separate, catalog-digest-bound sidecars for review claims and imported source observations. Unknown values are not negative facts.
- Provide exact source identity, observation date, appropriate licenses, and review status when proposing real-world content. Review status does not independently verify factual accuracy or rights.
- Do not represent saved OSM hours, prices, dietary tags, or source-provided images as current or independently verified.
- Add regression tests for source validity, deterministic behavior, unauthorized access and incompatible catalogs when applicable.

See [release checklist](docs/release-checklist.md), [source provenance](docs/data-quality-and-source-facts.md), and [roadmap](docs/roadmap.md).
