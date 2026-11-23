"""Consumer web-shell deployment tests, independent of the build environment."""

from pathlib import Path

from fastapi.testclient import TestClient

from savoroute.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "src/savoroute/web/consumer_dist"


def test_existing_routes_remain_unchanged():
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/v1/meta").status_code == 200
        assert client.get("/visits-review").status_code == 200
        assert client.get("/study-review").status_code == 200


def test_consumer_shell_mount_requires_a_real_build():
    with TestClient(create_app()) as client:
        if (DIST / "index.html").is_file():
            assert client.get("/app", follow_redirects=False).status_code == 307
            html = client.get("/app/")
            assert html.status_code == 200
            assert "text/html" in html.headers["content-type"]
            assert "default-src 'none'" in html.headers["content-security-policy"]
            assert html.headers["x-content-type-options"] == "nosniff"
            assert "'unsafe-inline'" not in html.headers["content-security-policy"]
        else:
            assert client.get("/app").status_code == 503
            response = client.get("/app/")
            assert response.status_code == 503
            assert "npm run build" in response.text


def test_consumer_shell_never_bypasses_api_authorization():
    with TestClient(create_app(api_key="fake-test-key")) as client:
        assert client.get("/v1/meta").status_code == 401
        assert client.get("/v1/items").status_code == 401
        assert client.get("/v1/meta", headers={"X-API-Key": "fake-test-key"}).status_code == 200
        response = client.get("/app/")
        assert response.status_code in {200, 503}
        assert "fake-test-key" not in response.text


def test_consumer_ui_source_contract_is_same_origin():
    client_code = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "'/v1/meta'" in client_code
    assert "'/v1/search'" in client_code
    assert "/v1/items?" in client_code
    assert "credentials: 'same-origin'" in client_code
    assert "redirect: 'error'" in client_code
    assert "new URLSearchParams" in client_code


def test_compiled_assets_have_same_origin_security_headers(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><title>Consumer test</title>',
                                     encoding="utf-8")
    (dist / "assets" / "main.js").write_text('console.log("client")', encoding="utf-8")
    with TestClient(create_app(consumer_dist_path=dist)) as client:
        assert client.get("/app", follow_redirects=False).status_code == 307
        page = client.get("/app/")
        assert page.status_code == 200
        assert "Consumer test" in page.text
        assert page.headers["cache-control"] == "no-store"
        assert "connect-src 'self'" in page.headers["content-security-policy"]
        assert "'unsafe-inline'" not in page.headers["content-security-policy"]
        asset = client.get("/app/assets/main.js")
        assert asset.status_code == 200
        assert "javascript" in asset.headers["content-type"]
        assert asset.headers["x-frame-options"] == "DENY"
        assert client.get("/app/assets/absent.js").status_code == 404
        assert client.get("/v1/meta").status_code == 200
