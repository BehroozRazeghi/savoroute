# Provider interfaces

`src/savoroute/providers/contracts.py` defines four capabilities: text generation, image captioning, text embedding, and joint text/image embedding. Retrieval remains independent of all four.

The text-ingestion milestone adds two concrete text generators:

| Adapter | Transport | Credential requirement | Status |
| --- | --- | --- | --- |
| `OpenAITextGenerator` | OpenAI Python SDK, Responses API | `OPENAI_API_KEY` | Implemented; mocked integration tests only |
| `OllamaTextGenerator` | HTTP `POST /api/generate` | Depends on configured server | Implemented; mocked HTTP tests only |

`ModelTextExtractor` depends only on the `TextGenerator` protocol, not either adapter. It validates model output independently of the model provider. The package also includes `LabeledTextExtractor`, a deterministic parser that does not use a text generator.

An IBM watsonx adapter is not included. It can implement `TextGenerator` after its target inference endpoint, credentials, request limits, and output semantics are established. An optional `ClipTextImageEmbedder` implements the joint text/image protocol using Sentence Transformers. It defaults to local-only model loading; callers may explicitly opt into model downloads and should pin a model revision. Stage 2b uses it for text/image index construction and query encoding. CI exercises the shared vector-index code with a deterministic test double, not pretrained CLIP weights. Dedicated image captioning and text-only embedding implementations are not included. See [local image ingestion](media-ingestion.md).

Model-backed extraction is opt-in. Source text is sent to the selected endpoint. Every live integration requires separate checks for model capability, availability, latency, service errors, costs, and provider data-handling policies. No fallback changes a local execution into a hosted request without explicit selection.

See [text ingestion](ingestion.md) for invocation and output validation.
