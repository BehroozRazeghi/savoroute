"""Savoroute v1 read-only HTTP application factory.

No business logic is reimplemented here. Configuration and the catalog are
loaded once when creating the application, never from a client-supplied path.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from savoroute import __version__
from savoroute.ai.contracts import MAX_BODY_BYTES, AIStatusOutput, InterpretInput, InterpretOutput
from savoroute.ai.images import InvalidFoodImage, normalize_image
from savoroute.ai.limits import AIGuard, RequestLimited
from savoroute.ai.provider import FoodAIProvider, ProviderUnavailable
from savoroute.api.contracts import (
    EvidenceItemOutput,
    FacetsOutput,
    ItemListOutput,
    ItemOutput,
    MetaOutput,
    NearbyOutput,
    RankInput,
    RankOutput,
    RecipeNotesItemOutput,
    RecommendationOutput,
    RecommendInput,
    ReviewedMediaListOutput,
    SearchInput,
    SearchOutput,
    SourceFactsItemOutput,
)
from savoroute.data.catalog import load_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.evidence.review import load_evidence_bundle
from savoroute.geography.nearby import NearbyIndex
from savoroute.live.contracts import LiveDiscoveryInput, LiveDiscoveryOutput, LiveStatusOutput
from savoroute.live.provider import LiveRestaurantProvider
from savoroute.live.quality import link_and_dedupe, matching_catalog, rank_web
from savoroute.live.validation import filter_displayed_leads
from savoroute.media.reviewed import load_reviewed_media
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.quality.osm_facts import load_source_facts, osm_snapshot_digest
from savoroute.quality.recipes import load_recipe_notes
from savoroute.retrieval.dense import DenseIndex, load_dense_index, validate_dense_catalog
from savoroute.retrieval.fusion import FusionWeights
from savoroute.retrieval.lexical import SearchFilters, filter_catalog
from savoroute.retrieval.vector import VectorIndex, load_vector_index, validate_catalog
from savoroute.services.discovery import DiscoveryService

_LIMITATIONS = (
    "Retrieval scores are not probabilities; catalog metadata may be incomplete or stale. "
    "Opening hours, availability, prices and allergen safety are not verified."
)


def _item(item: CatalogItem) -> dict[str, object]:
    return asdict(item)


def _bad_request(error: ValueError) -> None:
    raise HTTPException(status_code=400, detail=str(error)) from error


def _catalog_facets(catalog: Catalog, kind: Literal["restaurant", "recipe"]) -> dict[str, object]:
    """Calculate facets once per loaded catalog, not per HTTP request.

    Labels use recorded strings; case differences share one option, and no
    city is inferred from display addresses or coordinates.
    """
    counts: dict[str, Counter[str]] = {"cities": Counter(), "cuisines": Counter()}
    labels: dict[str, dict[str, str]] = {"cities": {}, "cuisines": {}}
    prices: set[int] = set()
    total = 0
    for item in catalog.items:
        if item.kind != kind:
            continue
        total += 1
        values = {
            "cities": {item.city.strip()} if item.city and item.city.strip() else set(),
            "cuisines": {value.strip() for value in item.cuisines if value.strip()},
        }
        for field, row_values in values.items():
            for value in row_values:
                key = value.casefold()
                counts[field][key] += 1
                # Stable display label independent of catalog iteration order.
                previous = labels[field].get(key)
                if previous is None or (value.casefold(), value) < (previous.casefold(), previous):
                    labels[field][key] = value
        if item.price_tier is not None:
            prices.add(item.price_tier)

    def rows(field: str) -> list[dict[str, object]]:
        return [{"value": labels[field][key], "count": count}
                for key, count in sorted(counts[field].items())]

    return {
        "kind": kind, "catalog_synthetic": catalog.synthetic, "total": total,
        "cities": rows("cities"), "cuisines": rows("cuisines"),
        "price_tiers": sorted(prices),
        "limitations": "Only recorded catalog attributes are listed. Missing fields are unknown; "
                       "facet counts are not independently verified.",
    }


def create_app(
    *,
    catalog_path: str | Path | None = None,
    index_path: str | Path | None = None,
    evidence_path: str | Path | None = None,
    osm_path: str | Path | None = None,
    reviewed_media_path: str | Path | None = None,
    source_facts_path: str | Path | None = None,
    recipe_notes_path: str | Path | None = None,
    encoder: JointTextImageEmbedder | None = None,
    api_key: str | None = None,
    consumer_dist_path: str | Path | None = None,
    ai_provider: FoodAIProvider | None = None,
    live_provider: LiveRestaurantProvider | None = None,
) -> FastAPI:
    """Create an independent app with explicit catalog/index configuration.

    Default: bundled fictional catalog and lexical-only ranking. Optional
    indices must be supplied at construction and are validated before serving.
    Clients cannot change catalog/index paths or initiate model downloads.
    """
    if api_key is not None and not api_key.strip():
        raise ValueError("api_key cannot be blank")
    if index_path is not None and catalog_path is None:
        raise ValueError("an explicit catalog_path is required when using an index")
    if encoder is not None and index_path is None:
        raise ValueError("an encoder requires an index_path")

    catalog: Catalog = load_catalog(catalog_path)
    service = DiscoveryService(catalog)
    facet_bundles = {kind: _catalog_facets(catalog, kind) for kind in ("restaurant", "recipe")}
    ai_guard = AIGuard()
    live_guard = AIGuard(requests_per_minute=3, concurrency=1)
    source_facts = load_source_facts(source_facts_path, catalog) if source_facts_path else None
    source_facts_by_item = ({entry["item_id"]: entry for entry in source_facts["records"]}
                            if source_facts is not None else {})
    recipe_notes = load_recipe_notes(recipe_notes_path, catalog) if recipe_notes_path else None
    recipe_notes_by_item = ({entry["item_id"]: entry for entry in recipe_notes["records"]}
                            if recipe_notes is not None else {})
    evidence_bundle = (load_evidence_bundle(evidence_path, catalog)
                       if evidence_path is not None else None)
    if reviewed_media_path is not None and evidence_bundle is None:
        raise ValueError("reviewed media requires an approved evidence bundle")
    media_bundle = (load_reviewed_media(reviewed_media_path, catalog, evidence_bundle)
                    if reviewed_media_path is not None else None)
    media_root = Path(reviewed_media_path).resolve() if reviewed_media_path is not None else None
    spatial = None
    if osm_path is not None:
        source = Path(osm_path)
        if not source.is_file() or source.stat().st_size > 2_000_000:
            raise ValueError("OSM geometry snapshot must be a local JSON file under 2 MB")
        try:
            snapshot = json.loads(source.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid UTF-8 OSM snapshot") from exc
        if (source_facts is not None and
                osm_snapshot_digest(snapshot) != source_facts["osm_snapshot_sha256"]):
            raise ValueError("OSM snapshot differs from source-facts provenance")
        spatial = NearbyIndex.from_snapshot(catalog, snapshot)
    catalog_dir = Path(catalog_path).resolve().parent if catalog_path is not None else None
    index: VectorIndex | DenseIndex | None = None
    backend: Literal["none", "json", "sqlite", "faiss-hnsw"] = "none"
    if index_path is not None:
        selected_path = Path(index_path)
        if selected_path.is_dir():
            index = load_dense_index(selected_path)
            backend = index.engine
            validate_dense_catalog(index, catalog, catalog_dir=catalog_dir)
        else:
            index = load_vector_index(selected_path)
            backend = "json"
            validate_catalog(index, catalog, catalog_dir=catalog_dir)
        if encoder is not None and (
            encoder.model_id != index.model_id
            or encoder.embedding_space_id != index.embedding_space_id
        ):
            raise ValueError("encoder identity differs from index identity")

    app = FastAPI(
        title="Savoroute HTTP API",
        description=(
            "Read-only catalog discovery and evidence-grounded recommendations. "
            "No live restaurant availability or safety verification."
        ),
        version=__version__,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        debug=False,
    )

    @app.exception_handler(RequestValidationError)
    def on_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo raw rejected inputs (which may contain private data).
        details = [
            {
                "field": ".".join(str(part) for part in issue["loc"]),
                "type": issue["type"],
                "message": issue["msg"],
            }
            for issue in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {
                "code": "validation_error", "message": "Invalid request", "details": details,
            }},
        )

    @app.exception_handler(HTTPException)
    def on_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        codes = {400: "bad_request", 401: "unauthorized", 404: "not_found"}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {
                "code": codes.get(exc.status_code, "http_error"),
                "message": str(exc.detail),
            }},
            headers={**(exc.headers or {}), "Cache-Control": "no-store"},
        )

    @app.get("/healthz", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "api_version": "v1"}

    header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_api_key(request: Request) -> None:
        assert api_key is not None  # added only when auth is enabled
        provided = request.headers.get("x-api-key")
        if provided is None or not compare_digest(provided.encode(), api_key.encode()):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid API key",
                headers={"WWW-Authenticate": "APIKey"},
            )

    router = APIRouter(
        prefix="/v1",
        tags=["catalog"],
        dependencies=[Security(header), Depends(require_api_key)] if api_key is not None else [],
    )

    @router.get("/meta", response_model=MetaOutput)
    def meta() -> dict[str, object]:
        return {
            "package_version": __version__,
            "dataset_name": catalog.dataset_name,
            "catalog_synthetic": catalog.synthetic,
            "catalog_items": len(catalog.items),
            "catalog_media": len(catalog.media),
            "index_backend": backend,
            "server_encoder_enabled": encoder is not None,
            "geography_enabled": spatial is not None,
            "geography_restaurants": len(spatial.positions) if spatial else 0,
            "reviewed_media_enabled": media_bundle is not None,
            "source_facts_enabled": source_facts is not None,
            "source_facts_records": len(source_facts_by_item),
            "recipe_notes_enabled": recipe_notes is not None,
            "recipe_notes_records": len(recipe_notes_by_item),
        }

    @router.get("/facets", response_model=FacetsOutput)
    def facets(kind: Literal["restaurant", "recipe"] = "restaurant") -> dict[str, object]:
        """Return cached source-recorded facets; never infer unknown fields."""
        return facet_bundles[kind]

    @router.get("/ai/status", response_model=AIStatusOutput, tags=["ai"])
    def ai_status() -> dict[str, object]:
        return {
            "enabled": ai_provider is not None,
            "input_types": ["text", "image"] if ai_provider is not None else [],
        }

    @router.post("/ai/interpret", response_model=InterpretOutput, tags=["ai"])
    async def ai_interpret(request: Request, response: Response) -> dict[str, object]:
        """Opt-in food *hypotheses*; catalog retrieval remains a separate user action.

        Parse bounded JSON from the ASGI request stream rather than asking
        FastAPI to buffer an arbitrarily large base64 payload first.
        """
        response.headers["Cache-Control"] = "no-store"
        if ai_provider is None:
            raise HTTPException(status_code=503, detail="AI interpretation is not configured")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="Expected application/json")
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > MAX_BODY_BYTES:
                    raise HTTPException(status_code=413, detail="AI request is too large")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        identity = request.client.host if request.client is not None else "unknown"
        try:
            await ai_guard.check_rate(identity)
        except RequestLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc),
                                headers={"Retry-After": "60"}) from exc
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="AI request is too large")
            data.extend(chunk)
        try:
            payload = InterpretInput.model_validate_json(bytes(data))
        except ValidationError as exc:
            # Do not disclose potentially sensitive prompt/image fragments.
            raise HTTPException(status_code=422,
                                detail="Invalid AI input or missing remote-processing consent") from exc
        try:
            image = normalize_image(payload.image_base64) if payload.image_base64 else None
        except InvalidFoodImage as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            await ai_guard.acquire()
        except RequestLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc),
                                headers={"Retry-After": "1"}) from exc
        try:
            interpretation = await ai_provider.interpret(payload.prompt, image)
        except ProviderUnavailable as exc:
            raise HTTPException(status_code=503,
                                detail="AI provider is temporarily unavailable") from exc
        finally:
            ai_guard.release()
        return {"provider": ai_provider.name, "interpretation": interpretation.model_dump(),
                "catalog_verified": False}

    @router.get("/live/status", response_model=LiveStatusOutput, tags=["live"])
    def live_status() -> dict[str, object]:
        return {"enabled": live_provider is not None}

    @router.post("/live/discover", response_model=LiveDiscoveryOutput, tags=["live"])
    async def live_discover(request: Request, response: Response) -> dict[str, object]:
        """Source-labeled web leads and independently hard-filtered catalog records.

        Live search is a separate opt-in service. Untrusted web discoveries are
        never inserted into the local catalog or used to alter ranking methods.
        """
        response.headers["Cache-Control"] = "no-store"
        if live_provider is None:
            raise HTTPException(status_code=503, detail="Live discovery is not configured")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="Expected application/json")
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > 4096:
                    raise HTTPException(status_code=413, detail="Live discovery request is too large")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        identity = request.client.host if request.client else "unknown"
        try:
            await live_guard.check_rate(identity)
        except RequestLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "60"}) from exc
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 4096:
                raise HTTPException(status_code=413, detail="Live discovery request is too large")
            data.extend(chunk)
        try:
            payload = LiveDiscoveryInput.model_validate_json(bytes(data))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Invalid location/cuisine or missing consent") from exc

        # Admission depends only on recorded cuisine and declared city membership.
        # A dish/preference query is *soft* and cannot be treated as verified menu data.
        catalog_matches = matching_catalog(catalog.items, payload)[:8]

        try:
            await live_guard.acquire()
        except RequestLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "1"}) from exc
        try:
            web_results = await live_provider.search(payload)
        except ProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail="Live web discovery is temporarily unavailable") from exc
        finally:
            live_guard.release()
        admitted_web = rank_web(filter_displayed_leads(web_results, payload), payload)
        distinct_web, linked = link_and_dedupe(catalog_matches, admitted_web)
        return {
            "provider": live_provider.name,
            "requested_cuisine": payload.cuisine,
            "requested_city": payload.city,
            "geography_scope": payload.geography_scope,
            "requested_cities": [payload.city, *payload.nearby_cities],
            "catalog_synthetic": catalog.synthetic,
            "catalog_results": [_item(item) for item in catalog_matches],
            "web_results": [entry.model_dump() for entry in distinct_web],
            "linked_sources": [entry.model_dump() for entry in linked],
        }

    @router.get("/items", response_model=ItemListOutput)
    def items(
        kind: Literal["restaurant", "recipe"] | None = None,
        cuisine: str | None = None,
        location: str | None = None,
        city: str | None = None,
        region: str | None = None,
        country: str | None = None,
        max_price_tier: Annotated[int | None, Query(ge=1, le=4)] = None,
        dietary_tags: Annotated[list[str] | None, Query(max_length=20)] = None,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, object]:
        try:
            selected = filter_catalog(
                catalog.items,
                SearchFilters(
                    kind=kind, cuisine=cuisine, location=location,
                    city=city, region=region, country=country,
                    max_price_tier=max_price_tier,
                    dietary_tags=tuple(dietary_tags or ()),
                ),
            )
        except ValueError as exc:
            _bad_request(exc)
        return {
            "total": len(selected), "offset": offset, "limit": limit,
            "items": [_item(item) for item in selected[offset:offset + limit]],
        }

    @router.get("/nearby", response_model=NearbyOutput)
    def nearby(
        latitude: Annotated[float, Query(ge=-90, le=90)],
        longitude: Annotated[float, Query(ge=-180, le=180)],
        radius_m: Annotated[int, Query(ge=25, le=20000)] = 2000,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        cuisine: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    ) -> dict[str, object]:
        if spatial is None:
            raise HTTPException(status_code=409, detail="OSM geometry is not configured")
        from savoroute.geography.nearby import GeographyError

        try:
            matches = spatial.search(latitude, longitude, radius_m=radius_m,
                                     limit=limit, cuisine=cuisine)
        except GeographyError as exc:
            _bad_request(exc)
        return {
            "catalog_synthetic": catalog.synthetic,
            "source_sha256": spatial.source_sha256,
            "geometry_restaurants": len(spatial.positions),
            "radius_m": radius_m,
            "results": [{"item": _item(row["item"]), "distance_m": row["distance_m"],
                         "geometry_basis": row["geometry_basis"],
                         "source_ref": row["source_ref"]} for row in matches],
            "limitations": "OSM nodes or bounding-box centers are approximate reference geometry; "
                           "distance is straight-line, not walking distance or proof of an entrance. "
                           "No live business or accessibility verification.",
        }

    @router.get("/items/{item_id}", response_model=ItemOutput)
    def item(item_id: str) -> dict[str, object]:
        if not 1 <= len(item_id) <= 256:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        found = catalog.get(item_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        return _item(found)

    @router.get("/items/{item_id}/evidence", response_model=EvidenceItemOutput)
    def item_evidence(item_id: str) -> dict[str, object]:
        if catalog.get(item_id) is None:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        # Public API does not expose the internal reviewer identifier or rationale.
        claims = ([] if evidence_bundle is None else [
            {**{field: value for field, value in entry.items() if field != "review"},
             "reviewed_on": entry["review"]["reviewed_on"]}
            for entry in evidence_bundle["claims"] if entry["item_id"] == item_id
        ])
        return {"item_id": item_id, "reviewed_claims": claims, "catalog_synthetic": catalog.synthetic,
                "menu_status": ("reviewed_reference" if any(claim["kind"] == "menu_url"
                    for claim in claims) else "not_recorded"),
                "limitations": "Evidence is reviewer-approved metadata, not independently verified "
                               "licensing, menu availability, dietary or food safety assurance."}

    @router.get("/items/{item_id}/source-facts", response_model=SourceFactsItemOutput)
    def item_source_facts(item_id: str) -> dict[str, object]:
        if catalog.get(item_id) is None:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        row = source_facts_by_item.get(item_id)
        return {
            "item_id": item_id,
            "observed_at": source_facts["observed_at"] if row is not None else None,
            "source_url": row["source_url"] if row is not None else None,
            "source_timestamp": row["source_timestamp"] if row is not None else None,
            "license": source_facts["license"] if row is not None else None,
            "attribution": source_facts["attribution"] if row is not None else None,
            "verification_status": ("unverified_osm_tags" if row is not None else
                                    "not_configured" if source_facts is None else "no_record"),
            "facts": row["facts"] if row is not None else [],
            "limitations": "Source-supplied OSM observations are not independently verified; "
                           "opening hours, dietary claims, accessibility, reservation, "
                           "service and website availability may be stale or incorrect. "
                           "Do not treat dietary tags as allergen safety evidence.",
        }

    @router.get("/items/{item_id}/recipe-notes", response_model=RecipeNotesItemOutput)
    def item_recipe_notes(item_id: str) -> dict[str, object]:
        if catalog.get(item_id) is None:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        row = recipe_notes_by_item.get(item_id)
        return {
            "item_id": item_id,
            "review_status": (row["review_status"] if row is not None else
                              "not_configured" if recipe_notes is None else "no_record"),
            **{key: row[key] if row is not None else None for key in (
                "source_url", "source_revision_url", "source_checked_on", "source_attribution",
                "source_license", "source_license_url", "adaptation_notice",
            )},
            "ingredients": row["ingredients"] if row is not None else [],
            "steps": row["steps"] if row is not None else [],
            "limitations": "A source-linked recipe adaptation is not independently cooked, professionally "
                           "tested, or checked for dietary/allergen suitability. Publication requires "
                           "retaining the original creator attribution, revision and CC BY-SA license.",
        }

    @router.get("/items/{item_id}/media", response_model=ReviewedMediaListOutput)
    def item_media(item_id: str) -> dict[str, object]:
        if catalog.get(item_id) is None:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        assets = ([] if media_bundle is None else [
            {key: value for key, value in entry.items() if key != "file"}
            for entry in media_bundle["assets"] if entry["item_id"] == item_id
        ])
        return {"item_id": item_id, "images": assets,
                "limitations": "License and source attribution were manually reviewed, not "
                               "independently verified. Image content may be outdated."}

    @router.get("/media/{asset_id}", include_in_schema=True)
    def local_media(asset_id: str) -> FileResponse:
        if media_bundle is None or media_root is None:
            raise HTTPException(status_code=404, detail="Reviewed local image not found")
        entry = next((entry for entry in media_bundle["assets"]
                      if entry["asset_id"] == asset_id), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="Reviewed local image not found")
        # Re-check bytes at request time; a changed file must fail closed rather
        # than silently serving content that differs from reviewed publication.
        file = media_root / entry["file"]
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(media_root):
            raise HTTPException(status_code=409, detail="Reviewed local image changed")
        if file.stat().st_size > 16 * 1024 * 1024:
            raise HTTPException(status_code=409, detail="Reviewed local image changed")
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise HTTPException(status_code=409, detail="Reviewed local image changed")
        return Response(
            content=data, media_type="image/png",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                     "Referrer-Policy": "no-referrer"},
        )

    @router.post("/search", response_model=SearchOutput)
    def search(request: SearchInput) -> dict[str, object]:
        try:
            hits = service.search(
                request.query, filters=request.filters.as_domain(),
                method=request.method, limit=request.limit,
            )
        except ValueError as exc:
            _bad_request(exc)
        return {
            "query": request.query,
            "catalog_synthetic": catalog.synthetic,
            "results": [
                {
                    "item": _item(hit.item), "score": hit.score,
                    "matched_terms": list(hit.matched_terms), "method": hit.method,
                }
                for hit in hits
            ],
            "limitations": _LIMITATIONS,
        }

    def rank_context(request: RankInput) -> tuple[FusionWeights, str]:
        if index is None and request.query_vector is not None:
            raise HTTPException(status_code=400, detail="query_vector requires an index")
        if encoder is not None and request.query_vector is not None:
            raise HTTPException(
                status_code=400, detail="query_vector is not accepted with a server encoder"
            )
        has_vector = index is not None and (
            request.query_vector is not None or encoder is not None
        )
        weights = (
            request.weights.as_domain() if request.weights is not None
            else FusionWeights() if has_vector else FusionWeights(bm25=1, text=0, image=0)
        )
        if index is None and (weights.text > 0 or weights.image > 0):
            raise HTTPException(status_code=400, detail="vector weights require an index")
        if not has_vector and (weights.text > 0 or weights.image > 0):
            raise HTTPException(
                status_code=400,
                detail="positive vector weights require query_vector or a server encoder",
            )
        mode = "hybrid" if has_vector and (weights.text > 0 or weights.image > 0) else "bm25_only"
        return weights, mode

    @router.post("/rank", response_model=RankOutput)
    def rank(request: RankInput) -> dict[str, object]:
        weights, mode = rank_context(request)
        try:
            hits = service.rank(
                request.query, index=index, encoder=encoder,
                query_vector=request.query_vector, catalog_dir=catalog_dir,
                filters=request.filters.as_domain(), weights=weights,
                rrf_k=request.rrf_k, pool_size=request.pool_size,
                limit=request.limit,
            )
        except ValueError as exc:
            _bad_request(exc)
        return {
            "query": request.query,
            "catalog_synthetic": catalog.synthetic,
            "mode": mode,
            "results": [
                {"item": _item(hit.item), "score": hit.score,
                 "evidence": [e.as_dict() for e in hit.evidence]}
                for hit in hits
            ],
            "limitations": _LIMITATIONS,
        }

    @router.post("/recommend", response_model=RecommendationOutput)
    def recommend(request: RecommendInput) -> dict[str, object]:
        weights, _mode = rank_context(request)
        try:
            result = service.recommend(
                request.query, index=index, encoder=encoder,
                query_vector=request.query_vector, catalog_dir=catalog_dir,
                filters=request.filters.as_domain(),
                preferences=request.preferences.as_domain(),
                weights=weights, rrf_k=request.rrf_k,
                pool_size=request.pool_size, limit=request.limit,
            )
        except ValueError as exc:
            _bad_request(exc)
        return result.as_dict()

    app.include_router(router)

    # Same-origin, packaged static interface. Only the existing /v1 routes
    # access catalog data; this page does not introduce another data API.
    static_dir = Path(__file__).resolve().parents[1] / "web" / "static"

    @app.get("/", include_in_schema=False)
    def web_home() -> FileResponse:
        return FileResponse(
            static_dir / "index.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data: blob:; connect-src 'self'; "
                    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
                ),
            },
        )

    @app.get("/visits-review", include_in_schema=False)
    def visit_review_page() -> FileResponse:
        # The browser reads user-selected JSON locally. This route never accepts
        # photo metadata, sends no API request, and exposes no personal history.
        return FileResponse(
            static_dir / "visits-review.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'none'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'; object-src 'none'"
                ),
            },
        )

    @app.get("/study-review", include_in_schema=False)
    def study_review_page() -> FileResponse:
        # Reviewer sheets and reference files are opened by the browser only.
        # No annotation data passes through an HTTP endpoint.
        return FileResponse(
            static_dir / "study-review.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'none'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'; object-src 'none'"
                ),
            },
        )

    app.mount("/assets", StaticFiles(directory=static_dir), name="web-assets")

    # The consumer app is an additive, separately built interface. The legacy
    # home page, reviewer tools, and read-only /v1 contracts remain unchanged.
    # Build: cd webapp && npm install && npm run build. No frontend dev server
    # or runtime Node process is needed when serving the compiled app.
    consumer_dist = (Path(consumer_dist_path).resolve() if consumer_dist_path is not None
                     else Path(__file__).resolve().parents[1] / "web" / "consumer_dist")
    consumer_ready = (consumer_dist / "index.html").is_file()

    @app.get("/app", include_in_schema=False)
    def consumer_home_redirect() -> Response:
        if consumer_ready:
            return RedirectResponse(url="/app/", status_code=307)
        return Response("Consumer app is not built. Run npm install && npm run build in webapp/.",
                        media_type="text/plain", status_code=503)

    if consumer_ready:
        class ConsumerStaticFiles(StaticFiles):
            async def get_response(self, path: str, scope: dict) -> Response:
                response = await super().get_response(path, scope)
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Content-Security-Policy"] = (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; "
                    "font-src 'self'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'; object-src 'none'"
                )
                if path in {"", ".", "index.html"}:
                    response.headers["Cache-Control"] = "no-store"
                return response

        app.mount("/app", ConsumerStaticFiles(directory=consumer_dist, html=True),
                  name="consumer-app")
    else:
        @app.get("/app/", include_in_schema=False)
        def consumer_not_built() -> Response:
            return Response("Consumer app is not built. Run npm install && npm run build in webapp/.",
                            media_type="text/plain", status_code=503)

    return app
