# IBM course material: retrieval design review

The supplied `course_project.zip` includes IBM course notebooks covering structured data, image captioning, text/image vector indexes, retrieval, score fusion, and multi-agent interfaces. It is a reference for the workflow, not a dependency or a source of production code.

| Course component | Useful technique | Savoroute design decision |
| --- | --- | --- |
| `module2/M2L1_Lab.ipynb` | Separate persistent text and image indexes; explicit encoders | Record modality, model identity, input digest, and canonical item/media IDs in a versioned local index |
| `module2/M2L2_Lab.ipynb` | Query retrieval with optional metadata filters | Exact cosine search; hard item-kind filtering; catalog fingerprint verification |
| `module2/M2L3_Lab.ipynb` | Text-to-image retrieval, image-to-image retrieval, and comparison of modality-specific ranked results | Separate record-level retrieval from later item-level rank fusion; use one shared embedding space for cross-modal cosine scores |
| `module1/M1L2_Process_Multimodal_Data_with_LLMs.ipynb` | Context-aware captions that distinguish visible evidence from claims in text | Defer captioning to its own model interface; retain item-level provenance and human review |

The text retrieval example in the course uses a MiniLM text encoder, while image retrieval uses CLIP. These embedding dimensions and geometries differ. Savoroute must not compute cosine similarities *across* those two spaces. The `JointTextImageEmbedder` interface requires text and image vectors from one shared model space. Later, separately ranked retrieval channels can be combined at the canonical item level without comparing their raw scores.

Some lab cells call Chroma's private `_collection` interface directly and convert distances using a fixed `1 - distance` convention. Those details depend on collection configuration and client implementation. Savoroute uses an explicit cosine function on normalized vectors for the initial exact index. The lab's per-result min-max normalization can also depend strongly on top-k truncation and should not be treated as a calibrated relevance score.

The first implementation stores vectors in a bounded JSON file so that schema validation, fingerprints, query results, and evaluation traces remain inspectable. This is a deliberate **small-catalog design**; an ANN backend or Chroma integration will require separately defined persistence, compatibility, filtering, and recall tests. No IBM account or service is required. No instructional notebook code or downloaded third-party dataset is redistributed.
