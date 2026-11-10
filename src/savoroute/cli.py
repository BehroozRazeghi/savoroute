"""Command-line adapter: all business logic lives in the package."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from savoroute.data.catalog import CatalogError, load_catalog
from savoroute.evaluation.retrieval import BenchmarkError, evaluate_search, load_benchmark
from savoroute.ingestion.extraction import LabeledTextExtractor, ModelTextExtractor
from savoroute.ingestion.sources import IngestionError, parse_source_batch
from savoroute.retrieval.lexical import SearchFilters
from savoroute.services.discovery import DiscoveryService
from savoroute.services.ingestion import ingest_sources, write_ingestion


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="savoroute", description="Catalog ingestion and retrieval"
    )
    commands = parser.add_subparsers(dest="command", required=True)

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            _run_ingest(args)
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
    except (CatalogError, BenchmarkError, IngestionError, ValueError, OSError,
            RuntimeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
