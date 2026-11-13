"""Browser delivery and existing HTTP service parity, no running socket required."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.cli import build_parser, main
from savoroute.data.catalog import catalog_to_dict, load_catalog


def test_home_page_and_security_headers():
    with TestClient(create_app()) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "script-src 'self'" in csp
        assert "connect-src 'self'" in csp
        assert "'unsafe-inline'" not in csp
        html = response.text
        assert "Savoroute" in html
        assert 'src="/assets/app.js"' in html
        assert 'href="/assets/styles.css"' in html
        assert 'href="/assets/favicon.svg"' in html
        assert '<form id="discovery-form"' in html
        assert 'id="catalog-list"' in html
        assert 'id="dialog-content"' in html
        assert "<script>" not in html


def test_packaged_asset_content_types_and_no_external_dependency():
    with TestClient(create_app()) as client:
        for resource, mime, needle in (
            ("styles.css", "text/css", "prefers-reduced-motion"),
            ("app.js", "javascript", "requestJson"),
            ("api.mjs", "javascript", "same-origin"),
            ("favicon.svg", "image/svg+xml", "<svg"),
        ):
            response = client.get(f"/assets/{resource}")
            assert response.status_code == 200, resource
            assert mime in response.headers["content-type"]
            assert needle in response.text
        assert client.get("/assets/not-a-file.js").status_code == 404
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200


def test_frontend_uses_existing_api_with_real_server_auth_boundaries():
    with TestClient(create_app(api_key="secret-for-tests")) as client:
        assert client.get("/").status_code == 200  # public shell, not data
        assert client.get("/assets/app.js").status_code == 200
        assert "secret-for-tests" not in client.get("/").text
        assert client.get("/v1/meta").status_code == 401
        headers = {"X-API-Key": "secret-for-tests"}
        meta = client.get("/v1/meta", headers=headers).json()
        assert meta["catalog_items"] == len(load_catalog().items)
        assert meta["package_version"] == "0.17.0"
        assert client.get("/v1/items", headers=headers).status_code == 200
        result = client.post(
            "/v1/recommend",
            json={"query": "spicy tofu", "filters": {"kind": "recipe"}},
            headers=headers,
        )
        assert result.status_code == 200
        assert result.json()["results"][0]["item_id"] == "p001"


def test_real_local_catalog_can_be_served_by_web(tmp_path: Path):
    data = load_catalog()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog_to_dict(data)), encoding="utf-8")
    with TestClient(create_app(catalog_path=path)) as client:
        meta = client.get("/v1/meta").json()
        items = client.get("/v1/items", params={"kind": "restaurant", "limit": 10}).json()
        assert meta["catalog_items"] == 12
        assert items["total"] == 6
        assert len(items["items"]) == 6
        assert client.get("/").status_code == 200


def test_web_cli_uses_exact_same_configured_http_server(monkeypatch):
    arguments = build_parser().parse_args([
        "web", "serve", "--catalog", "my-catalog.json", "--port", "8123",
        "--host", "127.0.0.1",
    ])
    assert arguments.web_command == "serve"
    received = []
    monkeypatch.setattr("savoroute.api.server.serve", lambda **kwargs: received.append(kwargs))
    assert main(["web", "serve", "--catalog", "my-catalog.json", "--port", "8123"]) == 0
    assert received == [{
        "catalog": "my-catalog.json", "index": None, "evidence": None, "osm": None,
        "reviewed_media": None, "host": "127.0.0.1",
        "port": 8123, "api_key_env": "SAVOROUTE_API_KEY",
    }]
