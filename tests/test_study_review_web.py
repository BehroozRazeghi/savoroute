"""The research labeling UI never receives or sends reviewer decisions over HTTP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from savoroute.api.app import create_app


def test_study_review_page_is_local_file_only_and_csp_locked():
    with TestClient(create_app(api_key="test-private-key")) as client:
        page = client.get("/study-review")
        assert page.status_code == 200
        assert "study-review.js" in page.text
        assert "test-private-key" not in page.text
        assert page.headers["cache-control"] == "no-store"
        csp = page.headers["content-security-policy"]
        assert "connect-src 'none'" in csp
        assert "form-action 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "'unsafe-inline'" not in csp
        for asset in ("study-review.js", "study-review.css"):
            assert client.get(f"/assets/{asset}").status_code == 200
        assert client.get("/v1/meta").status_code == 401
