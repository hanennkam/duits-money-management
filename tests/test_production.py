"""Production behaviour: hidden docs, fail-fast config, and response hardening."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import REQUIRED_ENV, get_settings, missing_env
from conftest import HEADERS


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A fresh app built with ENVIRONMENT=production, then torn down again."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    reloaded = importlib.reload(main_module)
    try:
        yield TestClient(reloaded.app)
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        importlib.reload(main_module)  # leave the module as the other tests found it


def test_api_docs_are_switched_off_in_production(production: TestClient) -> None:
    assert production.get("/docs").status_code == 404
    assert production.get("/redoc").status_code == 404
    assert production.get("/openapi.json").status_code == 404


def test_the_api_itself_still_works_in_production(production: TestClient) -> None:
    assert production.get("/health").status_code == 200


def test_health_is_public_head_and_never_cached(client: TestClient) -> None:
    """UptimeRobot polls /health with HEAD and no token; a cached reply would not keep Render awake."""
    for method in (client.get, client.head):
        response = method("/health")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"

    body = client.get("/health")
    assert body.json() == {"status": "ok"}
    assert body.headers["content-type"] == "application/json"


def test_docs_stay_on_outside_production() -> None:
    assert main_module.app.docs_url == "/docs"
    assert main_module.app.openapi_url == "/openapi.json"


def test_missing_environment_variables_are_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError) as caught:
        get_settings()

    message = str(caught.value)
    for name in REQUIRED_ENV:
        assert name in message  # names only, never the values
    assert missing_env() == list(REQUIRED_ENV)


def test_a_bad_numeric_setting_fails_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "not-a-number")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError) as caught:
        get_settings()

    assert "MAX_UPLOAD_BYTES" in str(caught.value)
    assert "not-a-number" not in str(caught.value)


def test_api_responses_are_not_cacheable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.list_transactions", lambda *_args, **_kw: [])
    monkeypatch.setattr(
        "app.db.summarize",
        lambda *_args, **_kw: {"total_expense": 0, "total_income": 0, "by_category": {}},
    )

    for path in ("/transactions?month=2026-10", "/summary?month=2026-10"):
        response = client.get(path, headers=HEADERS)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"


def test_hardening_headers_are_on_every_response(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert home.headers["X-Content-Type-Options"] == "nosniff"
    assert home.headers["Referrer-Policy"] == "no-referrer"
    assert home.headers.get("Cache-Control") == "no-store"  # the page is never cached either

    unauthorised = client.get("/transactions?month=2026-10")
    assert unauthorised.status_code == 401
    assert unauthorised.headers["Cache-Control"] == "no-store"
