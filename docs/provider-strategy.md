# Model integration

Version `0.1.0` defines four Python protocols in `src/savoroute/providers/contracts.py`:

| Protocol | Operation | Current implementation |
| --- | --- | --- |
| `TextGenerator` | Prompt to text | Interface only |
| `VisionCaptioner` | Image to caption | Interface only |
| `TextEmbedder` | Text to vectors | Interface only |
| `JointTextImageEmbedder` | Text and images to a declared shared embedding space | Interface only |

No model SDK is installed and no protocol has an adapter in this release. The current lexical rankers require no model.

Hosted generation may be implemented through IBM watsonx, OpenAI, Anthropic, or Google; local execution is also a target. Text embeddings and joint text/image embeddings are separate capabilities. Candidate implementations include SentenceTransformers for text-only embeddings and CLIP/SigLIP-family models for joint embeddings. These are options under evaluation, not declared compatible adapters.

A concrete adapter will specify the provider, model identifier and revision, supported operations, request limits, timeout/retry behavior, error mapping, and any data transmitted externally. Embedding adapters will also report vector dimension, normalization, distance metric, and embedding-space identity. Model/provider selection will never silently change a local-only data flow into a hosted one.

Provider integration tests will be isolated from offline unit tests and require explicit credentials. `.env.example` is an unpopulated reference; `.env` is excluded from version control.
