"""End-to-end tests for the shorty API.

Every test runs against an isolated SQLite file created under pytest's
``tmp_path`` and pointed at through the ``SHORTY_DB`` environment variable, so
tests never share state or touch the developer's database.
"""

import importlib
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from shorty.app import ALPHABET, app


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    """Point SHORTY_DB at a fresh temp file for the duration of one test."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("SHORTY_DB", str(path))
    return path


@pytest.fixture()
def client(db_env):
    """A TestClient whose lifespan creates the schema in the temp DB."""
    with TestClient(app) as c:
        yield c


def _create(client, url="https://example.com", code=None):
    payload = {"url": url}
    if code is not None:
        payload["custom_code"] = code
    return client.post("/links", json=payload)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_unknown_route_returns_404(client):
    assert client.get("/").status_code == 404


def test_create_generated_link_shape(client):
    resp = _create(client, url="https://example.com/a/b?x=1")
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"code", "url", "short_url"}
    assert body["url"] == "https://example.com/a/b?x=1"
    assert len(body["code"]) == 7
    assert all(ch in ALPHABET for ch in body["code"])
    assert body["short_url"] == f"http://testserver/{body['code']}"

    redirect = client.get("/" + body["code"], follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/a/b?x=1"


def test_create_custom_code_returns_exact_short_url(client):
    resp = _create(client, url="https://custom.example", code="my-link_1")
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == "my-link_1"
    assert body["short_url"] == "http://testserver/my-link_1"


def test_create_defaults_hits_to_zero_and_created_at(client):
    assert _create(client, url="https://zero.example", code="zero").status_code == 201
    stats = client.get("/links/zero").json()
    assert set(stats) == {"code", "url", "hits", "created_at"}
    assert stats["code"] == "zero"
    assert stats["url"] == "https://zero.example"
    assert stats["hits"] == 0
    assert stats["created_at"].endswith("+00:00")
    assert datetime.fromisoformat(stats["created_at"]).tzinfo is not None


@pytest.mark.parametrize("payload", [{}, {"url": None}])
def test_create_missing_url_422(client, payload):
    resp = client.post("/links", json=payload)
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "javascript:alert(1)",
        "mailto:a@b.com",
        "file:///tmp/x",
        "gopher://example.com",
        "example.com",
        "//example.com",
        "http://",
        "https://",
        "",
    ],
)
def test_create_rejects_invalid_urls(client, url):
    resp = _create(client, url=url)
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_custom_code_allows_url_safe_chars(client):
    resp = _create(client, url="https://safe.example", code="Abc-123_xyz")
    assert resp.status_code == 201
    assert resp.json()["code"] == "Abc-123_xyz"
    assert client.get("/links/Abc-123_xyz").json()["url"] == "https://safe.example"


@pytest.mark.parametrize(
    "code",
    [
        "has space",
        "a/b",
        "a?b",
        "a#b",
        "a!b",
        "a.b",
        "a%20b",
        "caf\u00e9",
        "a\tb",
        "abc\n",
        "abc\nxyz",
    ],
)
def test_custom_code_rejects_invalid_chars(client, code):
    resp = _create(client, url="https://x.example", code=code)
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_custom_code_rejects_empty_string(client):
    resp = _create(client, url="https://x.example", code="")
    assert resp.status_code == 422


def test_duplicate_custom_code_returns_409(client):
    assert _create(client, url="https://one.example", code="dup").status_code == 201
    resp = _create(client, url="https://two.example", code="dup")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "custom code already in use"


def test_duplicate_custom_code_preserves_original(client):
    assert _create(client, url="https://orig.example", code="keep").status_code == 201
    assert _create(client, url="https://new.example", code="keep").status_code == 409
    stats = client.get("/links/keep").json()
    assert stats["url"] == "https://orig.example"
    assert stats["hits"] == 0


def test_custom_code_reusable_after_delete(client):
    assert _create(client, url="https://one.example", code="reuse").status_code == 201
    assert client.delete("/links/reuse").status_code == 204
    assert _create(client, url="https://two.example", code="reuse").status_code == 201
    assert client.get("/links/reuse").json()["url"] == "https://two.example"


def test_stats_unknown_code_404(client):
    resp = client.get("/links/missing")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "code not found"


def test_redirect_returns_307_and_location(client):
    assert _create(client, url="https://dest.example/path", code="go").status_code == 201
    resp = client.get("/go", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "https://dest.example/path"


def test_redirect_increments_hits_on_each_request(client):
    assert _create(client, url="https://count.example", code="cnt").status_code == 201
    for expected in range(1, 5):
        resp = client.get("/cnt", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "https://count.example"
        assert client.get("/links/cnt").json()["hits"] == expected


def test_redirect_unknown_code_404(client):
    resp = client.get("/nope", follow_redirects=False)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "code not found"


def test_delete_returns_204_empty_body(client):
    assert _create(client, url="https://del.example", code="del").status_code == 201
    resp = client.delete("/links/del")
    assert resp.status_code == 204
    assert resp.content == b""


def test_delete_unknown_and_repeat_404(client):
    assert client.delete("/links/ghost").status_code == 404
    assert client.delete("/links/ghost").json()["detail"] == "code not found"
    assert _create(client, url="https://del2.example", code="del2").status_code == 201
    assert client.delete("/links/del2").status_code == 204
    assert client.delete("/links/del2").status_code == 404


def test_delete_then_stats_and_redirect_404(client):
    assert _create(client, url="https://gone.example", code="gone").status_code == 201
    assert client.delete("/links/gone").status_code == 204
    assert client.get("/links/gone").status_code == 404
    assert client.get("/gone", follow_redirects=False).status_code == 404


def test_list_empty_initially(client):
    resp = client.get("/links")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_reflects_creates_and_deletes(client):
    assert _create(client, url="https://a.example", code="alpha").status_code == 201
    assert _create(client, url="https://b.example", code="beta").status_code == 201
    codes = {item["code"] for item in client.get("/links").json()}
    assert codes == {"alpha", "beta"}

    assert client.delete("/links/alpha").status_code == 204
    remaining = client.get("/links").json()
    assert [item["code"] for item in remaining] == ["beta"]
    assert remaining[0]["url"] == "https://b.example"
    assert remaining[0]["hits"] == 0


def test_list_ordering_newest_first(client):
    for code in ("first", "second", "third"):
        assert _create(client, url=f"https://{code}.example", code=code).status_code == 201
        time.sleep(0.002)
    codes = [item["code"] for item in client.get("/links").json()]
    assert codes == ["third", "second", "first"]


def test_persistence_across_client_recreation(db_env):
    with TestClient(app) as c:
        assert _create(c, url="https://persist.example", code="persist").status_code == 201
        assert c.get("/persist", follow_redirects=False).status_code == 307
        assert c.get("/persist", follow_redirects=False).status_code == 307

    with TestClient(app) as c2:
        stats = c2.get("/links/persist").json()
        assert stats["url"] == "https://persist.example"
        assert stats["hits"] == 2
        assert c2.get("/persist", follow_redirects=False).status_code == 307


def test_persistence_across_app_reload(db_env):
    import shorty.app as app_module

    with TestClient(app_module.app) as c:
        assert _create(c, url="https://reload.example", code="reload").status_code == 201
        assert c.get("/reload", follow_redirects=False).status_code == 307

    reloaded = importlib.reload(app_module)
    with TestClient(reloaded.app) as c2:
        stats = c2.get("/links/reload").json()
        assert stats["url"] == "https://reload.example"
        assert stats["hits"] == 1
        assert c2.get("/reload", follow_redirects=False).status_code == 307


@pytest.mark.parametrize("code", ["health", "links", "docs", "openapi.json", "redoc", "Docs"])
def test_custom_code_rejects_reserved(client, code):
    resp = _create(client, code=code)
    assert resp.status_code == 422
    assert "reserved" in resp.text
    assert client.get("/links").json() == []
