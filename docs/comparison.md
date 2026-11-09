# Baseline design comparison

The repository consolidates two initial implementations reviewed on 2026-11-09: `culinary-discovery-agent-starter(1).zip` (28 files) and `palatepath-starter.zip` (35 files). Both provided working offline examples, but neither implemented an end-to-end multimodal system.

| Area | Culinary Discovery Agent | PalatePath | Savoroute `0.1.0` |
| --- | --- | --- | --- |
| Package structure | Mostly flat | Domain, data, provider and retrieval modules | Compact layered package |
| Catalog | Versioned JSON, 12 records | Unversioned packaged records, 6 items | Validated version-1 JSON, 12 records |
| Package data | Repository-relative file | Installed-package resource | Packaged resource and readable copy |
| Ranking | BM25 baseline | Weighted token overlap | Both methods with explicit scoring rules |
| Evaluation | Synthetic ranking cases and metrics | Described but not executed | 16-case executable benchmark |
| Notebook coverage | Two lessons | One quickstart | Four lessons sharing package code |
| Providers | No formal interfaces | Capability protocols | Four capability protocols, no adapters |
| CLI | Validation, search, evaluation | Demo and search | Demo, validation, search, evaluation |
| UI | No running application | Empty client scaffold | No empty client directories |

## Decisions retained

- Item and media IDs are explicit; neither filenames nor array order determine associations.
- Unknown catalog fields, duplicate IDs, invalid types, and dangling media references are rejected.
- BM25 statistics use the complete input catalog, while filters control eligible results.
- Fictional fixtures ship with the wheel; the CLI does not depend on the checkout directory.
- Model interfaces are defined by capability. Provider SDK dependencies will be introduced with actual implementations.
- Notebook code imports the library rather than maintaining separate retrieval or evaluation algorithms.

Features without working implementations—multimodal indexing, agent workflows, MCP, HTTP, and clients—remain in the roadmap rather than as empty packages or application directories.
