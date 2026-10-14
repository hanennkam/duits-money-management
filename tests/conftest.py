"""Shared test fixtures: a known API key and a client with the database mocked out."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

SETTINGS = Settings(
    api_key="test-api-key",
    supabase_url="https://example.supabase.co",
    supabase_service_key="service-role-key",
    anthropic_api_key="sk-ant-test",
)
HEADERS = {"X-API-Key": SETTINGS.api_key}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """App with a known API key. The database is monkeypatched per test."""
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
