"""Savoroute v1 read-only HTTP application factory.

No business logic is reimplemented here. Configuration and the catalog are
loaded once when creating the application, never from a client-supplied path.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from savoroute import __version__
from savoroute.api.contracts import (
    ItemListOutput,
    ItemOutput,
    MetaOutput,
    RankInput,
    RankOutput,
    RecommendationOutput,
    RecommendInput,
    SearchInput,
    SearchOutput,
)
from savoroute.data.catalog import load_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.providers.contracts import JointTextImageEmbedder
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


def create_app(
    *,
    catalog_path: str | Path | None = None,
    index_path: str | Path | None = None,
    encoder: JointTextImageEmbedder | None = None,
    api_key: str | None = None,
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
            headers=exc.headers,
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
        }

    @router.get("/items", response_model=ItemListOutput)
    def items(
        kind: Literal["restaurant", "recipe"] | None = None,
        cuisine: str | None = None,
        location: str | None = None,
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

    @router.get("/items/{item_id}", response_model=ItemOutput)
    def item(item_id: str) -> dict[str, object]:
        if not 1 <= len(item_id) <= 256:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        found = catalog.get(item_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        return _item(found)

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
    return app
