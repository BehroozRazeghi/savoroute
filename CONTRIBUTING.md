# Contributing

SavoRoute is an experimental developer-preview application. The Python package under `src/savoroute/` defines catalog, retrieval, recommendation, and evaluation behavior. The CLI, FastAPI service, local browser, notebooks, and read-only stdio MCP tools must use shared implementations rather than introduce divergent rules.

## Before opening a pull request

Use a focused branch. Describe the behavioral change, source and data implications, tests executed, and tests that could not run. Preserve API and catalog compatibility unless a documented versioned migration is necessary.

Install the development dependencies and run:

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
python -m pytest -q
python -m ruff check src tests scripts
python -m pip check
node --input-type=module --check < src/savoroute/web/static/app.js
node --input-type=module --check < src/savoroute/web/static/visits-review.js
node --input-type=module --check < src/savoroute/web/static/study-review.js
node --check src/savoroute/web/static/api.mjs
node --test tests/web/*.test.mjs
```

The JavaScript checks require Node.js. CI runs Python tests and notebook execution on Python 3.11–3.13. Execute modified notebooks from the repository root, remove unnecessary outputs, and do not commit private input data. Do not merge while required CI checks are failing or pending.

## Data, privacy, and evidence

- Never commit credentials, personal visit history, photos, reviewer decisions, downloaded model weights, or `data/generated/` outputs.
- Preserve original source identity, observation time, permitted uses, and review status. A source observation is not independently verified current business information.
- Bind reviewed claims and source-observation sidecars to the matching catalog digest. Unknown values must not be presented as negative facts or assumed to meet hard constraints.
- Never present OSM opening hours, dietary tags, source images, prices, or external menu links as current or safety-verified without additional evidence.
- Add regression tests for deterministic behavior, failure cases, unauthorized access, catalog/index mismatch, and geographic boundaries when relevant.
- Keep the default fictional demo runnable without external network access, credentials, or a model download.

See the [release checklist](docs/release-checklist.md), [source quality guide](docs/data-quality-and-source-facts.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md).
