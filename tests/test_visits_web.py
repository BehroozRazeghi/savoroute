"""The user-selected visit review page must not expose private metadata to HTTP."""

from pathlib import Path

from fastapi.testclient import TestClient

from savoroute.api.app import create_app

STATIC = Path(__file__).parent.parent / "src/savoroute/web/static"


def test_review_page_is_local_file_picker_not_a_new_api():
    with TestClient(create_app(api_key="testing-key")) as client:
        response = client.get("/visits-review")
        assert response.status_code == 200
        assert 'connect-src \'none\'' in response.headers["content-security-policy"]
        assert 'form-action \'none\'' in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert 'type="file"' in response.text
        assert 'src="/assets/visits-review.js"' in response.text
        assert '<script>' not in response.text
        assert client.post("/visits-review", json={"photos": []}).status_code == 405
        assert client.get("/assets/visits-review.js").status_code == 200
        assert client.get("/assets/visits-review.css").status_code == 200
        assert client.get("/v1/items").status_code == 401  # no API bypass


def test_review_js_has_no_network_or_persistent_storage_access():
    text = (STATIC / "visits-review.js").read_text()
    assert "fetch(" not in text
    assert "XMLHttpRequest" not in text
    assert "localStorage" not in text and "sessionStorage" not in text
    assert "navigator.geolocation" not in text
    assert "file.text()" in text
    assert "URL.createObjectURL" in text
    assert "textContent" in text
    assert "innerHTML" not in text
