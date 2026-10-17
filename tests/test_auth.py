"""Who is calling: Supabase Bearer tokens, the optional legacy key, and the failed-attempt throttle.

The dependency is exercised through a minimal app, so these tests cover auth and not the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.auth import FAILURE_LIMIT, current_user
from app.config import Settings, get_settings
from conftest import ISSUER, KID, SETTINGS, SIGNING_KEY, TEST_USER, token_for

LEGACY_USER = "9c3e4a1b-2d5f-4a6e-8b7c-0d1e2f3a4b5c"
LEGACY_SETTINGS = Settings(
    **{**SETTINGS.model_dump(), "allow_legacy_api_key": True, "legacy_user_id": UUID(LEGACY_USER)}
)
FORWARDED = {"X-Forwarded-For": "203.0.113.7"}
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def build_client(settings: Settings = SETTINGS) -> TestClient:
    """Minimal app that returns whichever user the dependency resolved."""
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/whoami")
    async def whoami(user_id: auth.CurrentUser) -> dict[str, str]:
        return {"user_id": str(user_id)}

    return TestClient(app)


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_no_credentials_is_401() -> None:
    assert build_client().get("/whoami").status_code == 401


def test_a_valid_token_resolves_to_its_sub() -> None:
    response = build_client().get("/whoami", headers=bearer(token_for(TEST_USER)))
    assert response.status_code == 200
    assert response.json() == {"user_id": TEST_USER}


def test_an_expired_token_is_401() -> None:
    expired = token_for(TEST_USER, expires_in=-120)
    assert build_client().get("/whoami", headers=bearer(expired)).status_code == 401


def test_a_token_that_expired_inside_the_leeway_is_still_accepted() -> None:
    """A clock a few seconds off must not reject a fresh token (30s leeway)."""
    just_expired = token_for(TEST_USER, expires_in=-5)
    assert build_client().get("/whoami", headers=bearer(just_expired)).status_code == 200


def test_a_token_for_another_audience_is_401() -> None:
    assert build_client().get("/whoami", headers=bearer(token_for(TEST_USER, aud="anon"))).status_code == 401


def test_a_token_from_another_issuer_is_401() -> None:
    wrong_iss = token_for(TEST_USER, iss="https://elsewhere.invalid/auth/v1")
    assert build_client().get("/whoami", headers=bearer(wrong_iss)).status_code == 401


def test_a_token_signed_by_another_key_is_401() -> None:
    forged = token_for(TEST_USER, key=OTHER_KEY)
    assert build_client().get("/whoami", headers=bearer(forged)).status_code == 401


def test_an_hs256_token_keyed_with_the_public_key_is_401() -> None:
    """The classic algorithm-confusion attack: the public key is public, so it must not verify as an HMAC secret.

    PyJWT refuses to sign with a public key, so the token is built by hand, the way an attacker would.
    """
    public_pem = SIGNING_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    claims = {"sub": TEST_USER, "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 600}
    payload = b64(json.dumps(claims).encode())
    signature = b64(hmac.new(public_pem, header + b"." + payload, hashlib.sha256).digest())
    forged = b".".join([header, payload, signature]).decode()

    assert build_client().get("/whoami", headers=bearer(forged)).status_code == 401


def test_an_unsigned_token_is_401() -> None:
    claims = {"sub": TEST_USER, "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 600}
    unsigned = jwt.encode(claims, None, algorithm="none")
    assert build_client().get("/whoami", headers=bearer(unsigned)).status_code == 401


def test_a_token_without_a_sub_is_401() -> None:
    claims = {"aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 600, "iat": int(time.time())}
    no_sub = jwt.encode(claims, SIGNING_KEY, algorithm="ES256", headers={"kid": KID})
    assert build_client().get("/whoami", headers=bearer(no_sub)).status_code == 401


def test_a_sub_that_is_not_a_user_id_is_401() -> None:
    assert build_client().get("/whoami", headers=bearer(token_for("not-a-uuid"))).status_code == 401


def test_a_token_with_an_unknown_kid_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_matching_key(_token: str, _url: str) -> None:
        raise jwt.PyJWKClientError("Unable to find a signing key that matches")

    monkeypatch.setattr("app.auth.signing_key_for", no_matching_key)
    assert build_client().get("/whoami", headers=bearer(token_for(TEST_USER))).status_code == 401


def test_the_sign_in_keys_being_unreachable_is_503_not_401(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(_token: str, _url: str) -> None:
        raise jwt.PyJWKClientConnectionError("cannot reach the keys")

    monkeypatch.setattr("app.auth.signing_key_for", unreachable)
    assert build_client().get("/whoami", headers=bearer(token_for(TEST_USER))).status_code == 503


def test_the_user_comes_from_the_token_not_from_the_query_or_body() -> None:
    client = build_client()
    response = client.get(f"/whoami?user_id={LEGACY_USER}", headers=bearer(token_for(TEST_USER)))
    assert response.json() == {"user_id": TEST_USER}


def test_the_legacy_key_is_refused_by_default() -> None:
    response = build_client().get("/whoami", headers={"X-API-Key": SETTINGS.api_key})
    assert response.status_code == 401


def test_the_legacy_key_acts_as_the_legacy_user_when_enabled() -> None:
    response = build_client(LEGACY_SETTINGS).get("/whoami", headers={"X-API-Key": SETTINGS.api_key})
    assert response.status_code == 200
    assert response.json() == {"user_id": LEGACY_USER}


def test_a_wrong_legacy_key_is_401_even_when_enabled() -> None:
    assert build_client(LEGACY_SETTINGS).get("/whoami", headers={"X-API-Key": "wrong"}).status_code == 401


@pytest.fixture(autouse=True)
def empty_throttle() -> None:
    auth._failures.clear()


def fail_once(client: TestClient, forwarded: dict[str, str]) -> int:
    return client.get("/whoami", headers={**forwarded, "Authorization": "Bearer not-a-token"}).status_code


def test_failed_attempts_are_throttled_after_the_limit() -> None:
    client = build_client()

    assert [fail_once(client, FORWARDED) for _ in range(FAILURE_LIMIT)] == [401] * FAILURE_LIMIT

    throttled = client.get("/whoami", headers={**FORWARDED, "Authorization": "Bearer not-a-token"})
    assert throttled.status_code == 429
    assert throttled.headers["Retry-After"] == "60"
    # even a good token is refused while the IP is blocked
    good = {**FORWARDED, "Authorization": f"Bearer {token_for(TEST_USER)}"}
    assert client.get("/whoami", headers=good).status_code == 429


def test_a_request_with_no_credentials_counts_as_a_failure() -> None:
    client = build_client()

    for _ in range(FAILURE_LIMIT):
        assert client.get("/whoami", headers=FORWARDED).status_code == 401
    assert client.get("/whoami", headers=FORWARDED).status_code == 429


def test_the_throttle_is_per_client_ip() -> None:
    client = build_client()

    for _ in range(FAILURE_LIMIT):
        fail_once(client, FORWARDED)

    assert fail_once(client, FORWARDED) == 429
    assert fail_once(client, {"X-Forwarded-For": "198.51.100.9"}) == 401  # other IP unaffected


def test_only_the_first_forwarded_hop_counts() -> None:
    client = build_client()

    for _ in range(FAILURE_LIMIT):
        fail_once(client, {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})

    # same client, different proxy chain -> still the same bucket
    assert fail_once(client, {"X-Forwarded-For": "203.0.113.7, 10.0.0.2"}) == 429
    # a genuinely different first hop is not blocked
    assert fail_once(client, {"X-Forwarded-For": "198.51.100.9, 10.0.0.1"}) == 401


def test_a_good_token_clears_the_failure_count() -> None:
    client = build_client()

    for _ in range(FAILURE_LIMIT - 1):
        fail_once(client, FORWARDED)
    assert auth.recent_failures("203.0.113.7") == FAILURE_LIMIT - 1

    good = {**FORWARDED, "Authorization": f"Bearer {token_for(TEST_USER)}"}
    assert client.get("/whoami", headers=good).status_code == 200
    assert auth.recent_failures("203.0.113.7") == 0


def test_key_comparison_tolerates_non_ascii() -> None:
    """A non-ASCII header must be rejected, not turned into a 500 by compare_digest."""
    assert auth.key_matches("caf\u00e9-key", "caf\u00e9-key") is True
    assert auth.key_matches("caf\u00e9-key", SETTINGS.api_key) is False
    assert auth.key_matches(None, SETTINGS.api_key) is False
    assert auth.key_matches("", SETTINGS.api_key) is False


def test_legacy_mode_without_a_legacy_user_id_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    required = {
        "API_KEY": "k",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_KEY": "s",
        "ANTHROPIC_API_KEY": "a",
    }
    for name, value in required.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ALLOW_LEGACY_API_KEY", "true")
    monkeypatch.delenv("LEGACY_USER_ID", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="LEGACY_USER_ID"):
            get_settings()
    finally:
        get_settings.cache_clear()
