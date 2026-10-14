"""The X-API-Key dependency: 401 without a matching key, pass-through with one."""

from typing import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.auth import FAILURE_LIMIT, require_api_key
from app.config import Settings, get_settings

API_KEY = "test-api-key"

# One client IP per test, so the throttle buckets cannot leak between tests.
FORWARDED = {"X-Forwarded-For": "203.0.113.7"}

SETTINGS = Settings(
    api_key=API_KEY,
    supabase_url="https://example.supabase.co",
    supabase_service_key="service-role-key",
    anthropic_api_key="sk-ant-test",
)


def build_client() -> TestClient:
    """Minimal app so the test exercises the dependency, not the database."""
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: SETTINGS

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_missing_header_is_401() -> None:
    assert build_client().get("/protected").status_code == 401


def test_wrong_key_is_401() -> None:
    response = build_client().get("/protected", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_matching_key_is_allowed() -> None:
    response = build_client().get("/protected", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.fixture(autouse=True)
def empty_throttle() -> Iterator[None]:
    """Rate-limit counting is process state: start and end every test with it empty."""
    auth._failures.clear()
    yield
    auth._failures.clear()


def fail_once(client: TestClient, headers: dict[str, str]) -> int:
    return client.get("/protected", headers={**headers, "X-API-Key": "wrong-key"}).status_code


def test_failed_attempts_are_throttled_after_the_limit() -> None:
    client = build_client()

    assert [fail_once(client, FORWARDED) for _ in range(FAILURE_LIMIT)] == [401] * FAILURE_LIMIT

    throttled = client.get("/protected", headers={**FORWARDED, "X-API-Key": "wrong-key"})
    assert throttled.status_code == 429
    assert throttled.headers["Retry-After"] == "60"
    assert "Too many failed API key attempts" in throttled.json()["detail"]
    # even the right key is refused while the IP is blocked
    assert client.get("/protected", headers={**FORWARDED, "X-API-Key": API_KEY}).status_code == 429


def test_a_request_with_no_key_counts_as_a_failure() -> None:
    client = build_client()

    for _ in range(FAILURE_LIMIT):
        assert client.get("/protected", headers=FORWARDED).status_code == 401
    assert client.get("/protected", headers=FORWARDED).status_code == 429


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


def test_a_good_key_clears_the_failure_count() -> None:
    client = build_client()

    for _ in range(FAILURE_LIMIT - 1):
        fail_once(client, FORWARDED)
    assert auth.recent_failures("203.0.113.7") == FAILURE_LIMIT - 1

    assert client.get("/protected", headers={**FORWARDED, "X-API-Key": API_KEY}).status_code == 200
    assert auth.recent_failures("203.0.113.7") == 0


def test_key_comparison_tolerates_non_ascii() -> None:
    """A non-ASCII header must be rejected, not turned into a 500 by compare_digest."""
    assert auth.key_matches("caf\u00e9-key", "caf\u00e9-key") is True
    assert auth.key_matches("caf\u00e9-key", API_KEY) is False
    assert auth.key_matches(None, API_KEY) is False
    assert auth.key_matches("", API_KEY) is False
