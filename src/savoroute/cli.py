"""Command-line adapter: all business logic lives in the package."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from savoroute.data.catalog import CatalogError, load_catalog
from savoroute.domain.models import Catalog
from savoroute.evaluation.annotations import (
    finalize_relevance_workbook,
    load_query_set,
    load_relevance_workbook,
    merge_reviewer_sheets,
    prepare_relevance_workbook,
    split_reviewer_sheets,
)
from savoroute.evaluation.dense import benchmark_dense
from savoroute.evaluation.extraction import AnnotationError, evaluate_extraction, load_gold
from savoroute.evaluation.fusion import evaluate_fusion
from savoroute.evaluation.identity import evaluate_identity_candidates, load_identity_benchmark
from savoroute.evaluation.multimodal import evaluate_multimodal, load_multimodal_benchmark
from savoroute.evaluation.research import (
    analyze_reviewed_study,
    audit_reviewer_progress,
    prepare_analysis_plan,
)
from savoroute.evaluation.retrieval import BenchmarkError, evaluate_search, load_benchmark
from savoroute.evaluation.study import (
    evaluate_reviewed_study,
    prepare_osm_study,
    verify_osm_study,
    write_study_report,
)
from savoroute.identity.annotations import prepare_osm_annotations
from savoroute.identity.registry import (
    bootstrap_osm_registry,
    link_source,
    load_registry,
    write_registry,
)
from savoroute.ingestion.extraction import LabeledTextExtractor, ModelTextExtractor
from savoroute.ingestion.osm import (
    fetch_overpass,
    import_osm_snapshot,
    write_osm_import,
    write_overpass_snapshot,
)
from savoroute.ingestion.sources import IngestionError, parse_source_batch
from savoroute.media.ingestion import (
    MediaIngestionError,
    prepare_image_batch,
    write_image_batch,
)
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.retrieval.dense import (
    DenseIndex,
    convert_vector_index,
    dense_modalities,
    load_dense_index,
    search_dense,
    validate_dense_catalog,
)
from savoroute.retrieval.fusion import FusionWeights, search_fused
from savoroute.retrieval.lexical import SearchFilters
from savoroute.retrieval.vector import (
    VectorIndex,
    VectorIndexError,
    build_vector_index,
    load_vector_index,
    search_with_encoder,
    validate_catalog,
    write_vector_index,
)
from savoroute.services.discovery import DiscoveryService
from savoroute.services.ingestion import ingest_sources, write_ingestion
from savoroute.services.osm_sync import sync_osm_snapshot, write_osm_sync
from savoroute.services.recommendation import RecommendationPreferences, recommend_items
from savoroute.services.storage import write_json_file, write_json_group


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="savoroute", description="Catalog ingestion and retrieval"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    api = commands.add_parser("api", help="serve the optional read-only HTTP API")
    api_commands = api.add_subparsers(dest="api_command", required=True)
    api_serve = api_commands.add_parser("serve", help="start the local HTTP server")
    api_serve.add_argument("--catalog", help="explicit catalog JSON; default: fictional demo")
    api_serve.add_argument("--index", help="optional matching JSON/SQLite/FAISS index")
    api_serve.add_argument("--evidence", help="approved evidence bundle bound to the catalog")
    api_serve.add_argument("--osm", help="saved Overpass JSON for approximate nearby discovery")
    api_serve.add_argument("--reviewed-media", help="local rights-reviewed PNG bundle directory")
    api_serve.add_argument("--host", default="127.0.0.1")
    api_serve.add_argument("--port", type=int, default=8000)
    api_serve.add_argument("--api-key-env", default="SAVOROUTE_API_KEY")

    web = commands.add_parser("web", help="run the local web app over the HTTP API")
    web_commands = web.add_subparsers(dest="web_command", required=True)
    web_serve = web_commands.add_parser("serve", help="start the packaged browser interface")
    for name, flags in (
        ("catalog", {"help": "explicit catalog JSON; default: fictional demo"}),
        ("index", {"help": "optional matching vector index"}),
        ("evidence", {"help": "approved evidence bundle bound to the catalog"}),
        ("osm", {"help": "saved Overpass JSON for approximate nearby discovery"}),
        ("reviewed-media", {"help": "local rights-reviewed PNG bundle directory"}),
        ("host", {"default": "127.0.0.1"}),
        ("port", {"type": int, "default": 8000}),
        ("api-key-env", {"default": "SAVOROUTE_API_KEY"}),
    ):
        web_serve.add_argument(f"--{name}", **flags)

    evidence = commands.add_parser("evidence", help="review and publish source-backed enrichment")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    prepare_evidence = evidence_commands.add_parser("prepare", help="write blank review sheet")
    publish_evidence = evidence_commands.add_parser("publish", help="publish approved references")
    for action in (prepare_evidence, publish_evidence):
        action.add_argument("--catalog", help="catalog JSON; default: fictional sample")
        action.add_argument("--proposals", required=True, help="candidate evidence JSON")
        action.add_argument("--output", required=True, help="new output file; never overwritten")
    publish_evidence.add_argument("--review", required=True, help="completed review JSON")

    visits = commands.add_parser("visits", help="offline metadata-only visit suggestions")
    visit_commands = visits.add_subparsers(dest="visit_command", required=True)
    suggest = visit_commands.add_parser("suggest", help="cluster selected metadata; prepare review")
    suggest.add_argument("--catalog", required=True, help="canonical OSM restaurant catalog")
    suggest.add_argument("--osm", required=True, help="matching local Overpass JSON snapshot")
    suggest.add_argument("--photos", required=True, help="explicit user-selected photo metadata JSON")
    suggest.add_argument("--output", required=True, help="private unreviewed suggestions JSON")
    suggest.add_argument("--review-template", required=True, help="blank review decisions JSON")
    suggest.add_argument("--gap-minutes", type=int, default=90)
    suggest.add_argument("--span-minutes", type=int, default=180)
    suggest.add_argument("--cluster-radius-m", type=int, default=200)
    suggest.add_argument("--match-radius-m", type=int, default=125)
    suggest.add_argument("--max-candidates", type=int, default=5)
    finalize = visit_commands.add_parser("finalize", help="publish explicitly reviewed visits")
    finalize.add_argument("--catalog", required=True, help="same canonical catalog")
    finalize.add_argument("--suggestions", required=True)
    finalize.add_argument("--review", required=True, help="completed private review decisions")
    finalize.add_argument("--output", required=True, help="new minimal confirmed history JSON")

    mcp = commands.add_parser("mcp", help="serve read-only MCP tools over local stdio")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_commands.add_parser("serve", help="start the local MCP stdio server")
    mcp_serve.add_argument("--catalog", help="explicit catalog JSON; default: fictional demo")
    mcp_serve.add_argument("--index", help="optional matching JSON/SQLite/FAISS vector index")

    demo = commands.add_parser("demo", help="run two fictional catalog searches")
    demo.add_argument("--catalog", help="optional JSON catalog override")

    validate = commands.add_parser("validate", help="validate a catalog and media references")
    validate.add_argument("--catalog", help="default: bundled demo catalog")

    search = commands.add_parser("search", help="lexical search; no LLM or remote requests")
    search.add_argument("query", help="query text")
    search.add_argument("--catalog", help="default: bundled demo catalog")
    search.add_argument("--kind", choices=("restaurant", "recipe"))
    search.add_argument("--cuisine")
    search.add_argument("--location")
    search.add_argument("--diet", action="append", default=[], help="required catalog tag")
    search.add_argument("--max-price-tier", type=int, choices=(1, 2, 3, 4))
    search.add_argument("--method", choices=("bm25", "overlap"), default="bm25")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--json", action="store_true", help="machine-readable output")

    evaluate = commands.add_parser("evaluate", help="synthetic retrieval benchmark")
    evaluate.add_argument("--catalog", help="default: bundled demo catalog")
    evaluate.add_argument("--benchmark", help="default: bundled demo judgments")
    evaluate.add_argument("--method", choices=("bm25", "overlap", "both"), default="both")
    evaluate.add_argument("--at-k", type=int, default=5)
    evaluate.add_argument("--json", action="store_true")
    ingest = commands.add_parser("ingest", help="extract source records into a validated catalog")
    ingest.add_argument("--sources", required=True, help="local source-batch JSON file")
    base = ingest.add_mutually_exclusive_group()
    base.add_argument("--catalog", help="base catalog (default: packaged demo)")
    base.add_argument("--new-catalog", action="store_true",
                      help="start an empty catalog named after the input dataset")
    ingest.add_argument("--output", required=True, help="path for merged canonical catalog")
    ingest.add_argument("--provenance", required=True, help="path for field-level evidence JSON")
    ingest.add_argument("--provider", choices=("labeled", "openai", "ollama"),
                        default="labeled", help="labeled input is offline and deterministic")
    ingest.add_argument("--model", help="required when provider is openai or ollama")
    ingest.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ingest.add_argument("--overwrite", action="store_true")
    osm = commands.add_parser("osm", help="bounded OpenStreetMap data acquisition and import")
    osm_commands = osm.add_subparsers(dest="osm_command", required=True)
    fetch = osm_commands.add_parser("fetch", help="download a small Overpass JSON snapshot")
    fetch.add_argument("--bbox", nargs=4, type=float, metavar=("S", "W", "N", "E"), required=True)
    fetch.add_argument("--contact", required=True, help="email contact in User-Agent")
    fetch.add_argument("--output", required=True)
    import_cmd = osm_commands.add_parser("import", help="map local Overpass JSON into a catalog")
    import_cmd.add_argument("--input", required=True, help="local Overpass JSON snapshot")
    import_cmd.add_argument("--catalog", help="append to this canonical catalog")
    import_cmd.add_argument("--dataset", default="osm-restaurants")
    import_cmd.add_argument("--synthetic-fixture", action="store_true",
                            help="only for generated test fixtures, never actual OSM data")
    import_cmd.add_argument("--output", required=True)
    import_cmd.add_argument("--report", required=True)
    import_cmd.add_argument("--overwrite", action="store_true")
    sync = osm_commands.add_parser("sync", help="reconcile an OSM snapshot with stable source identities")
    sync.add_argument("--input", required=True, help="saved Overpass JSON snapshot")
    sync.add_argument("--catalog", required=True, help="existing version-1 catalog")
    sync.add_argument("--registry", required=True, help="source identity registry (v1)")
    sync.add_argument("--synthetic-fixture", action="store_true")
    sync.add_argument("--output", required=True, help="updated catalog (new file)")
    sync.add_argument("--registry-output", required=True, help="updated registry (new file)")
    sync.add_argument("--report", required=True, help="source sync decisions")
    sync.add_argument("--overwrite", action="store_true")

    identity = commands.add_parser("identity", help="reviewed source-to-entity bindings")
    identity_commands = identity.add_subparsers(dest="identity_command", required=True)
    bootstrap = identity_commands.add_parser("bootstrap-osm", help="initialize bindings from a v0.3.0 OSM import report")
    bootstrap.add_argument("--catalog", required=True)
    bootstrap.add_argument("--report", required=True)
    bootstrap.add_argument("--output", required=True)
    link = identity_commands.add_parser("link", help="manually associate a source ID with an existing item")
    link.add_argument("--catalog", required=True)
    link.add_argument("--registry", required=True)
    link.add_argument("--provider", required=True)
    link.add_argument("--source-ref", required=True)
    link.add_argument("--item-id", required=True)
    link.add_argument("--output", required=True)
    identity_eval = identity_commands.add_parser(
        "evaluate", help="evaluate duplicate-review candidates on labeled record pairs"
    )
    identity_eval.add_argument("--benchmark", required=True)
    identity_eval.add_argument("--json", action="store_true")
    prepare = identity_commands.add_parser(
        "prepare-osm", help="create an unlabeled manual review worksheet from saved OSM JSON"
    )
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--max-records", type=int, default=80)
    prepare.add_argument("--max-pairs", type=int, default=200)

    media = commands.add_parser("media", help="local image ingestion")
    media_commands = media.add_subparsers(dest="media_command", required=True)
    media_ingest = media_commands.add_parser(
        "ingest", help="validate and normalize a local image manifest"
    )
    media_ingest.add_argument("--manifest", required=True, help="versioned JSON image manifest")
    media_ingest.add_argument("--catalog", help="catalog without existing media; default: demo")
    media_ingest.add_argument("--output-dir", required=True, help="new self-contained output directory")
    reviewed_media = media_commands.add_parser(
        "package-reviewed", help="package local images bound to reviewed image rights claims"
    )
    reviewed_media.add_argument("--catalog", required=True)
    reviewed_media.add_argument("--evidence", required=True)
    reviewed_media.add_argument("--manifest", required=True)
    reviewed_media.add_argument("--output-dir", required=True)

    vectors = commands.add_parser("vectors", help="joint text/image vector retrieval")
    vector_commands = vectors.add_subparsers(dest="vector_command", required=True)
    vector_build = vector_commands.add_parser("build", help="embed catalog text and local media")
    vector_search = vector_commands.add_parser("search", help="search the persisted vector index")
    vector_eval = vector_commands.add_parser("evaluate", help="evaluate labeled image retrieval")
    for sub in (vector_build, vector_search, vector_eval):
        sub.add_argument("--model", default="sentence-transformers/clip-ViT-B-32")
        sub.add_argument("--revision", help="pinned model commit when reproducibility matters")
        sub.add_argument("--allow-download", action="store_true",
                         help="permit model download; disabled by default")
    vector_build.add_argument("--catalog", required=True, help="catalog with local media paths")
    vector_build.add_argument("--output", required=True, help="new vector-index JSON file")
    vector_build.add_argument("--text-only", action="store_true")
    vector_build.add_argument("--images-only", action="store_true")
    for sub in (vector_search, vector_eval):
        sub.add_argument("--index", required=True)
        sub.add_argument("--catalog", required=True)
    query = vector_search.add_mutually_exclusive_group(required=True)
    query.add_argument("--text")
    query.add_argument("--image", help="local query image")
    vector_search.add_argument("--target", choices=("text", "image", "all"), default="image")
    vector_search.add_argument("--kind", choices=("restaurant", "recipe"))
    vector_search.add_argument("--limit", type=int, default=5)
    vector_search.add_argument("--unique-items", action="store_true")
    vector_eval.add_argument("--benchmark", required=True)
    vector_eval.add_argument("--at-k", type=int, default=5)

    backend = commands.add_parser("backend", help="persistent vectors and latency benchmarks")
    backend_commands = backend.add_subparsers(dest="backend_command", required=True)
    backend_build = backend_commands.add_parser("build", help="convert a JSON index to a bundle")
    backend_build.add_argument("--index", required=True, help="v0.7/0.8 JSON vector index")
    backend_build.add_argument("--output-dir", required=True, help="new output directory")
    backend_build.add_argument("--engine", choices=("sqlite", "faiss-hnsw"), default="sqlite")
    backend_build.add_argument("--hnsw-m", type=int, default=24)
    backend_build.add_argument("--ef-construction", type=int, default=120)
    backend_build.add_argument("--ef-search", type=int, default=96)
    backend_search = backend_commands.add_parser("search", help="query a persistent vector bundle")
    backend_search.add_argument("--bundle", required=True)
    backend_search.add_argument("--vector", required=True, help="JSON array of query coordinates")
    backend_search.add_argument("--catalog", help="optional catalog validation and kind filter")
    backend_search.add_argument("--target", choices=("text", "image", "all"), default="all")
    backend_search.add_argument("--kind", choices=("restaurant", "recipe"))
    backend_search.add_argument("--limit", type=int, default=5)
    backend_search.add_argument("--unique-items", action="store_true")
    backend_benchmark = backend_commands.add_parser(
        "benchmark", help="synthetic recall and machine-specific latency"
    )
    backend_benchmark.add_argument("--engine", choices=("sqlite", "faiss-hnsw"), default="sqlite")
    backend_benchmark.add_argument("--records", type=int, default=1000)
    backend_benchmark.add_argument("--dimension", type=int, default=32)
    backend_benchmark.add_argument("--queries", type=int, default=20)
    backend_benchmark.add_argument("--at-k", type=int, default=10)
    backend_benchmark.add_argument("--seed", type=int, default=7)

    rank = commands.add_parser("rank", help="item-level BM25 and vector rank fusion")
    rank_commands = rank.add_subparsers(dest="rank_command", required=True)
    rank_search = rank_commands.add_parser("search", help="rank canonical catalog items")
    rank_eval = rank_commands.add_parser("evaluate", help="evaluate item-level fused rankings")
    for sub in (rank_search, rank_eval):
        sub.add_argument("--catalog", help="catalog JSON; required with --index")
        sub.add_argument("--index", help="optional JSON vector index or dense bundle directory")
        sub.add_argument("--model", default="sentence-transformers/clip-ViT-B-32")
        sub.add_argument("--revision", help="model revision used to build the index")
        sub.add_argument("--allow-download", action="store_true")
        sub.add_argument("--pool-size", type=int, default=50)
        sub.add_argument("--rrf-k", type=int, default=60)
        sub.add_argument("--bm25-weight", type=float, default=1.0)
        sub.add_argument("--text-weight", type=float, default=1.0)
        sub.add_argument("--image-weight", type=float, default=1.0)
        sub.add_argument("--json", action="store_true")
    rank_search.add_argument("query")
    rank_search.add_argument("--kind", choices=("restaurant", "recipe"))
    rank_search.add_argument("--cuisine")
    rank_search.add_argument("--location")
    rank_search.add_argument("--diet", action="append", default=[])
    rank_search.add_argument("--max-price-tier", type=int, choices=(1, 2, 3, 4))
    rank_search.add_argument("--limit", type=int, default=5)
    rank_eval.add_argument("--benchmark", default="data/sample/relevance_benchmark.json")
    rank_eval.add_argument("--at-k", type=int, default=5)

    judgments = commands.add_parser("judgments", help="prepare and finalize reviewed relevance labels")
    judgment_commands = judgments.add_subparsers(dest="judgment_command", required=True)
    judgment_prepare = judgment_commands.add_parser(
        "prepare", help="build an exhaustive unlabeled query-item worksheet"
    )
    judgment_prepare.add_argument("--catalog", required=True)
    judgment_prepare.add_argument("--queries", required=True, help="version-1 query set JSON")
    judgment_prepare.add_argument("--output", required=True)
    judgment_prepare.add_argument("--max-pairs", type=int, default=20000)
    judgment_finalize = judgment_commands.add_parser(
        "finalize", help="validate two-reviewer judgments and export frozen benchmarks"
    )
    judgment_finalize.add_argument("--catalog", required=True)
    judgment_finalize.add_argument("--workbook", required=True)
    judgment_finalize.add_argument("--output-dir", required=True)

    judgment_split = judgment_commands.add_parser(
        "split", help="create two independent blank reviewer files"
    )
    judgment_split.add_argument("--catalog", required=True)
    judgment_split.add_argument("--workbook", required=True)
    judgment_split.add_argument("--output-dir", required=True)
    judgment_merge = judgment_commands.add_parser(
        "merge", help="combine reviewer sheets into an adjudication workbook"
    )
    judgment_merge.add_argument("--catalog", required=True)
    judgment_merge.add_argument("--workbook", required=True)
    judgment_merge.add_argument("--reviewer-a", required=True)
    judgment_merge.add_argument("--reviewer-b", required=True)
    judgment_merge.add_argument("--output", required=True)

    study = commands.add_parser("study", help="freeze and evaluate OSM relevance studies")
    study_commands = study.add_subparsers(dest="study_command", required=True)
    study_prepare = study_commands.add_parser(
        "prepare-osm", help="freeze source, catalog, queries, and blinded review sheets"
    )
    study_prepare.add_argument("--source", required=True, help="saved OSM snapshot JSON")
    study_prepare.add_argument("--catalog", required=True, help="matching OSM-only catalog")
    study_prepare.add_argument("--queries", required=True, help="researcher-written query set")
    study_prepare.add_argument("--output-dir", required=True)
    study_prepare.add_argument("--collected-at", required=True, help="source acquisition time (UTC)")
    study_prepare.add_argument("--selection-protocol", required=True)
    study_prepare.add_argument("--query-protocol", required=True)
    study_prepare.add_argument("--max-pairs", type=int, default=20000)
    study_prepare.add_argument(
        "--synthetic-fixture", action="store_true", help="offline tutorial only"
    )
    study_verify = study_commands.add_parser("verify", help="verify all frozen study files")
    study_verify.add_argument("--study-dir", required=True)
    study_eval = study_commands.add_parser("evaluate", help="evaluate completed reviewed judgments")
    study_eval.add_argument("--study-dir", required=True)
    study_eval.add_argument("--workbook", required=True, help="merged and adjudicated workbook")
    study_eval.add_argument("--split", choices=("development", "test"), default="development")
    study_eval.add_argument("--allow-test", action="store_true")
    study_eval.add_argument("--at-k", type=int, default=5)
    study_eval.add_argument("--output", help="optional JSON report output, no overwrite")
    study_audit = study_commands.add_parser(
        "audit", help="check independent reviewer-sheet coverage without disclosing labels"
    )
    study_audit.add_argument("--study-dir", required=True)
    study_audit.add_argument("--reviewer-a", required=True)
    study_audit.add_argument("--reviewer-b", required=True)
    study_audit.add_argument("--output", help="optional audit JSON, no overwrite")
    study_plan = study_commands.add_parser(
        "plan", help="freeze an analysis configuration before evaluating held-out test data"
    )
    study_plan.add_argument("--study-dir", required=True)
    study_plan.add_argument("--output", required=True)
    study_plan.add_argument("--at-k", type=int, default=5)
    study_plan.add_argument(
        "--primary-metric", choices=(
            "ndcg_at_k", "recall_at_k", "reciprocal_rank_at_k", "correct_empty",
        ), default="ndcg_at_k",
    )
    study_plan.add_argument("--resamples", type=int, default=2000)
    study_plan.add_argument("--seed", type=int, default=2026)
    study_analyze = study_commands.add_parser(
        "analyze", help="paired query bootstrap and diagnostics on adjudicated judgments"
    )
    study_analyze.add_argument("--study-dir", required=True)
    study_analyze.add_argument("--workbook", required=True)
    study_analyze.add_argument("--plan", required=True)
    study_analyze.add_argument("--split", choices=("development", "test"),
                               default="development")
    study_analyze.add_argument("--allow-test", action="store_true")
    study_analyze.add_argument("--output", help="optional report JSON, no overwrite")

    recommendation = commands.add_parser("recommend", help="catalog-grounded recommendations")
    recommendation.add_argument("query")
    recommendation.add_argument("--catalog", help="catalog JSON; required with --index")
    recommendation.add_argument("--index", help="optional JSON vector index or dense bundle")
    recommendation.add_argument("--kind", choices=("restaurant", "recipe"))
    recommendation.add_argument("--cuisine")
    recommendation.add_argument("--location")
    recommendation.add_argument("--diet", action="append", default=[])
    recommendation.add_argument("--max-price-tier", type=int, choices=(1, 2, 3, 4))
    recommendation.add_argument("--prefer-cuisine", action="append", default=[])
    recommendation.add_argument("--prefer-diet", action="append", default=[])
    recommendation.add_argument("--exclude-item", action="append", default=[])
    recommendation.add_argument("--preference-strength", type=float, default=0.25)
    recommendation.add_argument("--model", default="sentence-transformers/clip-ViT-B-32")
    recommendation.add_argument("--revision")
    recommendation.add_argument("--allow-download", action="store_true")
    recommendation.add_argument("--pool-size", type=int, default=50)
    recommendation.add_argument("--rrf-k", type=int, default=60)
    recommendation.add_argument("--bm25-weight", type=float, default=1.0)
    recommendation.add_argument("--text-weight", type=float, default=1.0)
    recommendation.add_argument("--image-weight", type=float, default=1.0)
    recommendation.add_argument("--limit", type=int, default=5)
    recommendation.add_argument("--json", action="store_true")

    extraction_eval = commands.add_parser("evaluate-extraction", help="compare field extraction with gold annotations")
    extraction_eval.add_argument("--gold", required=True)
    extraction_eval.add_argument("--predictions", required=True, help="schema-v1 ingestion provenance JSON")
    extraction_eval.add_argument("--json", action="store_true")
    return parser


def _run_ingest(args: argparse.Namespace) -> None:
    batch = parse_source_batch(json.loads(Path(args.sources).read_text(encoding="utf-8")))
    if args.new_catalog:
        from savoroute.domain.models import Catalog
        catalog = Catalog(1, batch.dataset_name, batch.synthetic, ())
    else:
        catalog = load_catalog(args.catalog)
    if args.provider == "labeled":
        if args.model:
            raise IngestionError("--model is only supported for model providers")
        extractor = LabeledTextExtractor()
    else:
        if not args.model:
            raise IngestionError(f"--model is required for {args.provider}")
        if args.provider == "openai":
            from savoroute.providers.text import OpenAITextGenerator
            generator = OpenAITextGenerator(args.model)
        else:
            from savoroute.providers.text import OllamaTextGenerator
            generator = OllamaTextGenerator(args.model, base_url=args.ollama_url)
        extractor = ModelTextExtractor(generator)
    result = ingest_sources(batch, extractor, base_catalog=catalog)
    write_ingestion(result, catalog_path=args.output, provenance_path=args.provenance,
                    overwrite=args.overwrite)
    print(f"Ingested {len(result.records)} sources; catalog contains "
          f"{len(result.catalog.items)} items.")
    print(f"Catalog: {args.output}\nEvidence: {args.provenance}")


def _format_metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _rank_context(
    args: argparse.Namespace, catalog: Catalog, weights: FusionWeights,
) -> tuple[VectorIndex | DenseIndex | None, JointTextImageEmbedder | None, Path | None]:
    if args.index and not args.catalog:
        raise ValueError("--catalog is required with --index")
    index = (load_dense_index(args.index) if Path(args.index).is_dir()
             else load_vector_index(args.index)) if args.index else None
    directory = Path(args.catalog).resolve().parent if args.index else None
    encoder = None
    if index is not None:
        if isinstance(index, DenseIndex):
            validate_dense_catalog(index, catalog, catalog_dir=directory)
            available = dense_modalities(index)
        else:
            validate_catalog(index, catalog, catalog_dir=directory)
            available = {r.modality for r in index.records}
        needed = ((weights.text > 0 and "text" in available)
                  or (weights.image > 0 and "image" in available))
        if needed:
            from savoroute.providers.clip import ClipTextImageEmbedder

            encoder = ClipTextImageEmbedder(
                args.model, revision=args.revision, local_files_only=not args.allow_download,
            )
    return index, encoder, directory


def _run_rank(args: argparse.Namespace) -> None:
    catalog = load_catalog(args.catalog)
    weights = FusionWeights(args.bm25_weight, args.text_weight, args.image_weight)
    index, encoder, directory = _rank_context(args, catalog, weights)
    if args.rank_command == "search":
        filters = SearchFilters(
            kind=args.kind, cuisine=args.cuisine, location=args.location,
            max_price_tier=args.max_price_tier, dietary_tags=tuple(args.diet),
        )
        hits = search_fused(
            catalog, args.query, index=index, encoder=encoder, catalog_dir=directory,
            filters=filters, weights=weights, rrf_k=args.rrf_k,
            pool_size=args.pool_size, limit=args.limit,
        )
        if args.json:
            print(json.dumps([hit.as_dict() for hit in hits], indent=2))
        elif not hits:
            print("No matches.")
        else:
            for rank, hit in enumerate(hits, start=1):
                sources = ", ".join(row.source for row in hit.evidence)
                print(f"{rank}. {hit.item.title} [{hit.item.kind}] "
                      f"id={hit.item.item_id} rrf={hit.score:.6f} sources={sources}")
        return
    cases = load_benchmark(args.benchmark)
    summary = evaluate_fusion(
        catalog, cases, index=index, encoder=encoder, catalog_dir=directory,
        weights=weights, rrf_k=args.rrf_k, pool_size=args.pool_size, at_k=args.at_k,
    )
    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        print(f"RRF @ {summary.k}: Recall={_format_metric(summary.recall_at_k)} "
              f"MRR={_format_metric(summary.mrr_at_k)} "
              f"nDCG={_format_metric(summary.ndcg_at_k)} "
              f"Correct-empty={_format_metric(summary.correct_empty_rate)} "
              f"(positive={summary.positive_queries}, empty={summary.empty_queries})")
        print("Metrics apply only to supplied judgments; vector scores have no "
              "calibrated rejection threshold.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "visits":
            from savoroute.visits.workflow import (
                build_review_template,
                finalize_visits,
                load_visit_json,
                suggest_visits,
            )

            catalog = load_catalog(args.catalog)
            if args.visit_command == "suggest":
                suggestions = suggest_visits(
                    catalog, load_visit_json(args.osm), load_visit_json(args.photos),
                    gap_minutes=args.gap_minutes, span_minutes=args.span_minutes,
                    cluster_radius_m=args.cluster_radius_m,
                    match_radius_m=args.match_radius_m, max_candidates=args.max_candidates,
                )
                review = build_review_template(suggestions)
                write_json_group(((args.output, suggestions), (args.review_template, review)))
                print(f"Prepared {len(suggestions['clusters'])} unreviewed visit clusters; "
                      f"review every decision in {args.review_template}")
            else:
                history = finalize_visits(
                    catalog, load_visit_json(args.suggestions),
                    load_visit_json(args.review),
                )
                write_json_file(history, args.output)
                print(f"Exported {len(history['confirmed_visits'])} user-confirmed visits "
                      f"({history['rejected_count']} rejected): {args.output}")
            return 0
        if args.command == "evidence":
            from savoroute.evidence.review import prepare_review, publish_evidence

            catalog = load_catalog(args.catalog)
            if args.evidence_command == "prepare":
                count = prepare_review(catalog, args.proposals, args.output)
                print(f"Prepared {count} decisions: {args.output}")
            else:
                bundle = publish_evidence(catalog, args.proposals, args.review, args.output)
                print(f"Published {len(bundle['claims'])} reviewed references: {args.output}")
            return 0
        if args.command == "mcp":
            from savoroute.mcp.server import serve_stdio

            serve_stdio(catalog=args.catalog, index=args.index)
            return 0
        if args.command in {"api", "web"}:
            from savoroute.api.server import serve

            serve(catalog=args.catalog, index=args.index, evidence=args.evidence,
                  osm=args.osm, reviewed_media=args.reviewed_media,
                  host=args.host, port=args.port, api_key_env=args.api_key_env)
            return 0
        if args.command == "ingest":
            _run_ingest(args)
            return 0
        if args.command == "rank":
            _run_rank(args)
            return 0
        if args.command == "study":
            if args.study_command == "prepare-osm":
                manifest = prepare_osm_study(
                    source_path=args.source, catalog_path=args.catalog,
                    queries_path=args.queries, output_dir=args.output_dir,
                    collected_at=args.collected_at,
                    selection_protocol=args.selection_protocol,
                    query_protocol=args.query_protocol,
                    max_pairs=args.max_pairs, allow_synthetic_fixture=args.synthetic_fixture,
                )
                print(f"Prepared {manifest['judgment_pairs']} unlabeled pairs: {args.output_dir}")
            elif args.study_command == "verify":
                manifest = verify_osm_study(args.study_dir)
                print(f"Verified {manifest['items']} items and {manifest['queries']} queries")
            elif args.study_command == "audit":
                audit = audit_reviewer_progress(
                    args.study_dir, args.reviewer_a, args.reviewer_b,
                )
                if args.output:
                    write_study_report(audit, args.output)
                print(json.dumps(audit, ensure_ascii=False, indent=2))
            elif args.study_command == "plan":
                plan = prepare_analysis_plan(
                    args.study_dir, args.output, at_k=args.at_k,
                    primary_metric=args.primary_metric,
                    resamples=args.resamples, seed=args.seed,
                )
                print(f"Prepared checksum-bound analysis plan: {args.output}")
                print(f"Primary metric: {plan['primary_metric']}@{plan['at_k']}")
            elif args.study_command == "analyze":
                report = analyze_reviewed_study(
                    args.study_dir, args.workbook, args.plan,
                    split=args.split, allow_test=args.allow_test,
                )
                if args.output:
                    write_study_report(report, args.output)
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                report = evaluate_reviewed_study(
                    args.study_dir, args.workbook, split=args.split,
                    at_k=args.at_k, allow_test=args.allow_test,
                )
                if args.output:
                    write_study_report(report, args.output)
                print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "judgments":
            catalog = load_catalog(args.catalog)
            if args.judgment_command == "prepare":
                worksheet = prepare_relevance_workbook(
                    catalog, load_query_set(args.queries), max_pairs=args.max_pairs,
                )
                write_json_file(worksheet, args.output)
                print(f"Prepared {len(worksheet['judgments'])} unlabeled pairs: {args.output}")
            elif args.judgment_command == "split":
                reviewer_a, reviewer_b = split_reviewer_sheets(
                    catalog, load_relevance_workbook(args.workbook),
                )
                root = Path(args.output_dir)
                write_json_group(((root / "reviewer_a.json", reviewer_a),
                                  (root / "reviewer_b.json", reviewer_b)))
                print(f"Prepared independent review sheets: {root}")
            elif args.judgment_command == "merge":
                merged = merge_reviewer_sheets(
                    catalog, load_relevance_workbook(args.workbook),
                    load_relevance_workbook(args.reviewer_a),
                    load_relevance_workbook(args.reviewer_b),
                )
                write_json_file(merged, args.output)
                disagreements = sum(row["final_label"] is None for row in merged["judgments"])
                print(f"Merged review sheets; adjudication required for {disagreements} pairs")
            else:
                dev, test, audit = finalize_relevance_workbook(
                    catalog, load_relevance_workbook(args.workbook),
                )
                root = Path(args.output_dir)
                write_json_group(((root / "development.json", dev),
                                  (root / "test.json", test),
                                  (root / "audit.json", audit)))
                print(f"Exported complete judgments for {audit['query_count']} queries: {root}")
            return 0
        if args.command == "recommend":
            if args.index and not args.catalog:
                raise ValueError("--catalog is required with --index")
            catalog = load_catalog(args.catalog)
            weights = FusionWeights(args.bm25_weight, args.text_weight, args.image_weight)
            index, encoder, directory = _rank_context(args, catalog, weights)
            filters = SearchFilters(
                kind=args.kind, cuisine=args.cuisine, location=args.location,
                max_price_tier=args.max_price_tier, dietary_tags=tuple(args.diet),
            )
            prefs = RecommendationPreferences(
                cuisines=tuple(args.prefer_cuisine), dietary_tags=tuple(args.prefer_diet),
                excluded_item_ids=tuple(args.exclude_item),
                preference_strength=args.preference_strength,
            )
            response = recommend_items(
                catalog, args.query, filters=filters, preferences=prefs,
                index=index, encoder=encoder, catalog_dir=directory, weights=weights,
                rrf_k=args.rrf_k, pool_size=args.pool_size, limit=args.limit,
            )
            if args.json:
                print(json.dumps(response.as_dict(), indent=2))
            elif not response.results:
                print(f"No recommendations ({response.status}).")
            else:
                for i, result in enumerate(response.results, start=1):
                    print(f"{i}. {result.item.title} ({result.item.item_id}) "
                          f"score={result.score:.6f} source={result.item.source}")
                print(response.as_dict()["limitations"])
            return 0
        if args.command == "backend":
            if args.backend_command == "build":
                bundle = convert_vector_index(
                    load_vector_index(args.index), args.output_dir,
                    engine=args.engine, hnsw_m=args.hnsw_m,
                    ef_construction=args.ef_construction, ef_search=args.ef_search,
                )
                print(f"Indexed {bundle.count} records ({bundle.dimension} dimensions) "
                      f"with {bundle.engine}: {bundle.root}")
                return 0
            if args.backend_command == "benchmark":
                result = benchmark_dense(
                    backend=args.engine, records=args.records,
                    dimension=args.dimension, queries=args.queries,
                    k=args.at_k, seed=args.seed,
                )
                print(json.dumps(result.as_dict(), indent=2))
                return 0
            bundle = load_dense_index(args.bundle)
            catalog = load_catalog(args.catalog) if args.catalog else None
            if catalog is not None:
                validate_dense_catalog(
                    bundle, catalog, catalog_dir=Path(args.catalog).resolve().parent
                )
            vector = json.loads(args.vector)
            hits = search_dense(
                bundle, vector, target=args.target, k=args.limit, catalog=catalog,
                kind=args.kind, unique_items=args.unique_items,
            )
            print(json.dumps([hit.as_dict() for hit in hits], indent=2))
            return 0
        if args.command == "vectors":
            from savoroute.providers.clip import ClipTextImageEmbedder

            if args.vector_command == "build" and args.text_only and args.images_only:
                raise VectorIndexError("--text-only and --images-only are mutually exclusive")
            catalog = load_catalog(args.catalog)
            if args.vector_command != "build":
                index = load_vector_index(args.index)
                validate_catalog(index, catalog, catalog_dir=Path(args.catalog).resolve().parent)
            encoder = ClipTextImageEmbedder(
                args.model, revision=args.revision, local_files_only=not args.allow_download,
            )
            if args.vector_command == "build":
                index = build_vector_index(
                    catalog, Path(args.catalog).resolve().parent, encoder,
                    include_text=not args.images_only, include_images=not args.text_only,
                )
                write_vector_index(index, args.output)
                print(f"Indexed {len(index.records)} vectors ({index.dimension} dimensions) "
                      f"at {args.output}")
                return 0
            if args.vector_command == "search":
                hits = search_with_encoder(
                    index, encoder, text=args.text,
                    image=Path(args.image) if args.image else None,
                    target=args.target, k=args.limit, catalog=catalog,
                    kind=args.kind, unique_items=args.unique_items,
                )
                print(json.dumps([hit.as_dict() for hit in hits], indent=2))
                return 0
            result = evaluate_multimodal(
                index, encoder, load_multimodal_benchmark(args.benchmark), k=args.at_k,
            )
            print(json.dumps(result.as_dict(), indent=2))
            return 0
        if args.command == "media":
            catalog = load_catalog(args.catalog)
            if args.media_command == "package-reviewed":
                from savoroute.media.reviewed import package_reviewed_media

                bundle = package_reviewed_media(
                    catalog, args.evidence, args.manifest, args.output_dir
                )
                print(f"Packaged {len(bundle['assets'])} approved local images: "
                      f"{Path(args.output_dir) / 'manifest.json'}")
                return 0
            batch = prepare_image_batch(args.manifest, catalog)
            destination = write_image_batch(batch, args.output_dir)
            print(f"Imported {len(batch.images)} images; catalog media={len(batch.catalog.media)}")
            print(f"Catalog: {destination / 'catalog.json'}")
            print(f"Provenance: {destination / 'provenance.json'}")
            return 0
        if args.command == "identity":
            if args.identity_command == "evaluate":
                result = evaluate_identity_candidates(load_identity_benchmark(args.benchmark))
                if args.json:
                    print(json.dumps(result.as_dict(), indent=2))
                else:
                    def show(value: float | None) -> str:
                        return "N/A" if value is None else f"{value:.3f}"
                    print(f"Pairs={result.pairs} TP={result.true_positive} "
                          f"FP={result.false_positive} FN={result.false_negative} "
                          f"TN={result.true_negative}")
                    print(f"Precision={show(result.precision)} Recall={show(result.recall)} "
                          f"F1={show(result.f1)} Review rate={show(result.review_rate)}")
                    print("Synthetic labels; not a real-world accuracy estimate." if result.synthetic
                          else "Metrics apply only to annotated pairs in this benchmark.")
                return 0
            if args.identity_command == "prepare-osm":
                source = json.loads(Path(args.input).read_text(encoding="utf-8"))
                worksheet = prepare_osm_annotations(
                    source, max_records=args.max_records, max_pairs=args.max_pairs,
                )
                write_json_file(worksheet, args.output)
                print(f"Prepared {len(worksheet['pairs'])} unlabeled pairs: {args.output}")
                return 0
            catalog = load_catalog(args.catalog)
            if args.identity_command == "bootstrap-osm":
                report = json.loads(Path(args.report).read_text(encoding="utf-8"))
                registry = bootstrap_osm_registry(catalog, report)
            else:
                registry = load_registry(args.registry, catalog)
                registry = link_source(registry, catalog, provider=args.provider,
                                       source_ref=args.source_ref, item_id=args.item_id)
            write_registry(registry, args.output)
            print(f"Saved {len(registry.bindings)} source bindings: {args.output}")
            return 0
        if args.command == "osm":
            if args.osm_command == "sync":
                payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
                catalog = load_catalog(args.catalog)
                registry = load_registry(args.registry, catalog)
                result = sync_osm_snapshot(
                    payload, base_catalog=catalog, registry=registry,
                    synthetic_fixture=args.synthetic_fixture,
                )
                write_osm_sync(result, catalog_path=args.output,
                               registry_path=args.registry_output, report_path=args.report,
                               overwrite=args.overwrite)
                counts = Counter(decision.status for decision in result.decisions)
                print(f"OSM sync: {dict(sorted(counts.items()))}; "
                      f"catalog items={len(result.catalog.items)}")
                print(f"Catalog: {args.output}\nRegistry: {args.registry_output}\nReport: {args.report}")
                return 0
            if args.osm_command == "fetch":
                payload = fetch_overpass(tuple(args.bbox), contact=args.contact)
                write_overpass_snapshot(payload, args.output)
                print(f"Saved {len(payload['elements'])} OSM elements: {args.output}")
                return 0
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
            base = load_catalog(args.catalog) if args.catalog else None
            result = import_osm_snapshot(
                payload, base_catalog=base, dataset_name=args.dataset,
                synthetic_fixture=args.synthetic_fixture,
            )
            write_osm_import(result, catalog_path=args.output, report_path=args.report,
                             overwrite=args.overwrite)
            statuses = Counter(row.status for row in result.decisions)
            print(f"OSM import: {dict(sorted(statuses.items()))}; "
                  f"catalog items={len(result.catalog.items)}")
            print(f"Catalog: {args.output}\nReport: {args.report}")
            return 0
        if args.command == "evaluate-extraction":
            gold = load_gold(args.gold)
            predictions = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
            summary = evaluate_extraction(gold, predictions)
            if args.json:
                print(json.dumps(summary.as_dict(), indent=2))
            else:
                f1 = summary.micro.f1
                value = f"{f1:.3f}" if f1 is not None else "N/A"
                print(f"Gold records={summary.gold_records}; predicted={summary.predicted_records}; "
                      f"exact records={summary.exact_records}; micro F1={value}")
                for field, score in summary.fields.items():
                    print(f"{field}: TP={score.true_positive} FP={score.false_positive} "
                          f"FN={score.false_negative}")
            return 0
        catalog = load_catalog(args.catalog)
        service = DiscoveryService(catalog)
        if args.command == "validate":
            counts = dict(sorted(Counter(item.kind for item in catalog.items).items()))
            print(f"Valid catalog: dataset={catalog.dataset_name} synthetic={catalog.synthetic} "
                  f"items={len(catalog.items)} media={len(catalog.media)} kinds={counts}")
            return 0
        if args.command == "demo":
            print("Demo catalog: fictional records (offline).\n")
            for query in ("spicy noodles", "chickpea salad"):
                print(f"Query: {query}")
                for hit in service.search(query, limit=3):
                    print(f"  {hit.item.item_id}: {hit.item.title} ({hit.score:.3f})")
            return 0
        if args.command == "search":
            filters = SearchFilters(
                kind=args.kind, cuisine=args.cuisine, location=args.location,
                max_price_tier=args.max_price_tier, dietary_tags=tuple(args.diet),
            )
            hits = service.search(args.query, filters=filters,
                                  method=args.method, limit=args.limit)
            if args.json:
                print(json.dumps([
                    {"item_id": hit.item.item_id, "title": hit.item.title,
                     "kind": hit.item.kind, "score": round(hit.score, 6),
                     "matched_terms": list(hit.matched_terms),
                     "method": hit.method, "source": hit.item.source,
                     "source_url": hit.item.source_url}
                    for hit in hits
                ], indent=2))
            elif not hits:
                print("No matches.")
            else:
                for rank, hit in enumerate(hits, start=1):
                    print(f"{rank}. {hit.item.title} [{hit.item.kind}] "
                          f"id={hit.item.item_id} score={hit.score:.3f} "
                          f"source={hit.item.source}")
            return 0
        judgments = load_benchmark(args.benchmark)
        methods = ("bm25", "overlap") if args.method == "both" else (args.method,)
        summaries = [evaluate_search(catalog.items, judgments, at_k=args.at_k,
                                     method=method) for method in methods]
        if args.json:
            print(json.dumps([summary.as_dict() for summary in summaries], indent=2))
        else:
            print("Synthetic retrieval benchmark; not representative of real search traffic.")
            for summary in summaries:
                print(f"{summary.method} @ {summary.at_k}: "
                      f"Recall={_format_metric(summary.mean_recall_at_k)} "
                      f"MRR={_format_metric(summary.mrr_at_k)} "
                      f"nDCG={_format_metric(summary.mean_ndcg_at_k)} "
                      f"No-match={_format_metric(summary.correct_empty_rate)} "
                      f"(positive={summary.positive_queries}, "
                      f"empty={summary.empty_queries})")
        return 0
    except (CatalogError, BenchmarkError, IngestionError, MediaIngestionError,
            AnnotationError, VectorIndexError, ValueError, OSError,
            RuntimeError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
