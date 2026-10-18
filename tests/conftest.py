"""Shared test fixtures: a test signing key, Bearer tokens for one user, and a client with the database mocked out.

Tokens are real ES256 JWTs signed by a key this file generates. The app verifies them with the public half,
which the autouse fixture hands to it in place of the project's JWKS. Nothing here touches the network.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings, get_settings
from app.main import app

SETTINGS = Settings(
    api_key="test-api-key",
    supabase_url="https://example.supabase.co",
    supabase_service_key="service-role-key",
    supabase_publishable_key="pk_test_dummy",
    anthropic_api_key="sk-ant-test",
)
ISSUER = f"{SETTINGS.supabase_url}/auth/v1"
KID = "test-signing-key"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
TEST_USER = "5b1f2e8a-0c3d-4e5f-8a9b-1c2d3e4f5a6b"


def token_for(
    user_id: str = TEST_USER,
    *,
    aud: str = "authenticated",
    expires_in: int = 3600,
    key: Any = SIGNING_KEY,
    iss: str = ISSUER,
    extra: dict[str, Any] | None = None,
) -> str:
    """A Supabase-shaped access token for `user_id`, signed by `key`."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": user_id,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
    }
    claims.update(extra or {})
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": KID})


HEADERS = {"Authorization": f"Bearer {token_for()}"}

# repr() of a credential shows <redacted>. The hooks a failing pytest run uses — locals with -l, assertion
# rewriting, saferepr — all go through repr(); str() and format() are left alone, so a Secret still works
# as a header, a query parameter and a password.
REDACTED_VALUE = "<redacted>"
SECRET_MARKS = ("key", "secret", "password", "token", "authorization")


class Secret(str):
    """A credential that repr()s as <redacted> wherever it travels.

    Wrapping the VALUE, not the dict: pytest's dict-comparison rendering does not call a dict subclass's
    __repr__ — it walks the items and reprs each value separately, which is how a redacting *dict* still
    leaked on 2026-10-19 (measured in the probe of tests/test_secret_redaction.py). A str subclass covers a
    dict, a headers mapping and anything else it is poured into; equals, hash and slicing are the real
    value, so nothing that uses it as a credential changes.
    """

    def __repr__(self) -> str:
        return REDACTED_VALUE


def redact_secrets(values: dict[str, str]) -> dict[str, str]:
    """A copy of `values` with every credential-shaped value wrapped as a `Secret`.

    Shape decides: a key whose name says key, secret, password, token or authorization holds one.
    """
    return {
        key: Secret(value) if any(mark in key.lower() for mark in SECRET_MARKS) else value
        for key, value in values.items()
    }


@pytest.fixture(autouse=True)
def test_signing_keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The app verifies against the test key, and failed-attempt counts start empty for every test."""
    monkeypatch.setattr("app.auth.signing_key_for", lambda _token, _url: SIGNING_KEY.public_key())
    auth._failures.clear()
    yield
    auth._failures.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """App with a known configuration. The database is monkeypatched per test."""
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
