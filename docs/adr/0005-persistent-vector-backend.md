# ADR 0005: Persistent vectors and optional ANN search

**Status:** Accepted for milestone 3b.

**Context.** The original JSON index is portable and useful for exact regression tests, but embedding arrays make the file expensive to read and impractical to extend to larger local datasets.

**Decision.** Keep JSON as the correctness reference. Store vectors and source IDs in an immutable SQLite bundle with content hashes. Provide optional FAISS HNSW acceleration behind the same search contract. Model compatibility, catalog validation, item-level filtering and RRF remain in the Python service.

**Consequences.** SQLite gives durable, inspectable metadata and streaming writes but linear-scan exact search. HNSW offers approximate search with a recall/latency tradeoff and adds a native dependency and trusted-serialization requirement. The format is not a managed database service; updates create a new bundle. The synthetic microbenchmark measures backend mechanics, not application relevance. A real dataset and independently annotated query set are necessary before claiming ranking quality.
