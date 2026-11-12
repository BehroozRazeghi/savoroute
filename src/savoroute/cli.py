"""Command-line adapter: all business logic lives in the package."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from savoroute.data.catalog import CatalogError, load_catalog
from savoroute.evaluation.extraction import AnnotationError, evaluate_extraction, load_gold
from savoroute.evaluation.identity import evaluate_identity_candidates, load_identity_benchmark
from savoroute.evaluation.multimodal import evaluate_multimodal, load_multimodal_benchmark
from savoroute.evaluation.retrieval import BenchmarkError, evaluate_search, load_benchmark
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
from savoroute.retrieval.lexical import SearchFilters
from savoroute.retrieval.vector import (
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
from savoroute.services.storage import write_json_file


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            _run_ingest(args)
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
            RuntimeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
