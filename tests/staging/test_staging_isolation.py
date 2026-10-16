"""Multi-user isolation against the REAL staging project: real Postgres, real Storage, real Auth, real JWKS.

Run only through scripts/run_staging_tests.py, which loads .env.staging before the app is imported. The
module refuses to run against the live project. It writes test rows and receipts to staging, and removes them.

Nothing here is mocked except the Claude extraction, which is replaced with a fixed answer so the duplicate
checks can be driven by known merchants, dates and amounts. The image bytes and the dedupe keys are real.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app import auth, db
from app.config import get_settings
from app.main import app
from app.models import Extraction

REAL_SIGNING_KEY_FOR = auth.signing_key_for  # captured before the root conftest can replace it
LEGACY_0_BYTES = b"fake receipt legacy-0"
SEEDED_B_MERCHANTS = {"Kedai B 0", "Kedai B 1", "Kedai B 2", "Kedai B Sendiri"}

LIVE_PROJECT_REF = "viorpltdkpexswvofeul"
STAGING_PROJECT_REF = "tddigsmukmhkjrwiqdec"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env.staging"

pytestmark = [
    pytest.mark.staging,
    pytest.mark.skipif(os.environ.get("DUITS_STAGING_TESTS") != "1", reason="staging tests need the runner"),
]


def project_ref(url: str) -> str | None:
    match = re.match(r"^https://([a-z0-9]{20})\.supabase\.co$", url.rstrip("/"))
    return match.group(1) if match else None


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    """The staging settings, read from the file, after a refusal for the live project."""
    values = dotenv_values(ENV_FILE)
    ref = project_ref(values.get("SUPABASE_URL", ""))
    assert ref != LIVE_PROJECT_REF, "refusing: this is the live project"
    assert ref == STAGING_PROJECT_REF, "refusing: not the staging project"
    assert project_ref(os.environ.get("SUPABASE_URL", "")) == STAGING_PROJECT_REF, (
        "the app must be configured from .env.staging (use scripts/run_staging_tests.py)"
    )
    return {key: value for key, value in values.items() if value is not None}


@pytest.fixture(scope="module")
def base(env: dict[str, str]) -> str:
    return env["SUPABASE_URL"].rstrip("/")


@pytest.fixture(scope="module")
def service(env: dict[str, str]) -> dict[str, str]:
    return {"apikey": env["SUPABASE_SERVICE_KEY"], "Authorization": f"Bearer {env['SUPABASE_SERVICE_KEY']}"}


def sign_in(base: str, env: dict[str, str], email: str) -> str:
    response = httpx.post(
        f"{base}/auth/v1/token?grant_type=password",
        headers={"apikey": env["SUPABASE_SERVICE_KEY"], "Content-Type": "application/json"},
        json={"email": email, "password": env["STAGING_TEST_PASSWORD"]},
        timeout=30,
    )
    assert response.status_code == 200, f"sign-in failed with HTTP {response.status_code}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def token_a(base: str, env: dict[str, str]) -> str:
    return sign_in(base, env, "duits-staging-a@example.com")


@pytest.fixture(scope="module")
def token_b(base: str, env: dict[str, str]) -> str:
    return sign_in(base, env, "duits-staging-b@example.com")


@pytest.fixture(scope="module")
def ids(env: dict[str, str]) -> dict[str, str]:
    return {"a": env["STAGING_USER_A_ID"], "b": env["STAGING_USER_B_ID"]}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def rows_for(base: str, service: dict[str, str], query: str) -> list[dict[str, Any]]:
    response = httpx.get(f"{base}/rest/v1/transactions?{query}", headers=service, timeout=30)
    assert response.status_code == 200, response.text[:200]
    return response.json()


@pytest.fixture(scope="module")
def a_receipt_row(base: str, service: dict[str, str], ids: dict[str, str]) -> dict[str, Any]:
    """A's migrated receipt for the fake photo b"fake receipt legacy-0", found by its real image hash."""
    image_hash = hashlib.sha256(LEGACY_0_BYTES).hexdigest()
    [row] = rows_for(base, service, f"user_id=eq.{ids['a']}&image_hash=eq.{image_hash}&select=*")
    assert row["receipt_path"].startswith(f"{ids['a']}/"), "A's receipt must already be in A's folder"
    return row


LEGACY_BYTES = {n: f"fake receipt legacy-{n}".encode() for n in range(12)}


@pytest.fixture(scope="module")
def a_unshared_receipt(
    base: str, service: dict[str, str], ids: dict[str, str], b_own_row: dict[str, Any]
) -> dict[str, Any]:
    """An A receipt whose photo and dedupe key B does not also hold.

    Scanning it as B must be a plain save: any 409 there would mean B's own row matched, which is not this
    case. Depends on `b_own_row` so B's holdings are known before "unshared" is decided.
    """
    b_hashes = {(r["dedupe_hash"], r["image_hash"]) for r in rows_for(base, service, f"user_id=eq.{ids['b']}&select=dedupe_hash,image_hash")}
    for row in rows_for(base, service, f"user_id=eq.{ids['a']}&receipt_path=not.is.null&select=*&order=txn_date"):
        if (row["dedupe_hash"], row["image_hash"]) not in b_hashes:
            return row
    pytest.skip("every A receipt is also held by B; the seed must leave one unshared")


@pytest.fixture(scope="module")
def b_own_row(base: str, service: dict[str, str], ids: dict[str, str]) -> dict[str, Any]:
    """B's own receipt row, re-created if it has gone missing.

    A `down`/`up` cycle backfills **every** row to one owner, which leaves B with nothing and would make
    this suite fail for reasons that have nothing to do with isolation. The runbook's rollback path is
    exactly that cycle, so the fixture re-seeds rather than depending on data that the migration moves.
    """
    merchant = "Kedai B Sendiri"
    existing = rows_for(base, service, f"user_id=eq.{ids['b']}&merchant=eq.{quote(merchant)}&select=*")
    if existing:
        return existing[0]

    payload = b"fake receipt b-own-1"
    day = date(2026, 10, 25)
    amount = Decimal("66.60")
    image_hash = hashlib.sha256(payload).hexdigest()
    created = httpx.post(
        f"{base}/rest/v1/transactions",
        headers={**service, "Prefer": "return=representation"},
        json={
            "user_id": ids["b"],
            "txn_date": day.isoformat(),
            "amount": float(amount),
            "merchant": merchant,
            "category": "food",
            "type": "expense",
            "mode": "personal",
            "source": "receipt_scan",
            "receipt_path": f"{ids['b']}/2026/10/{image_hash[:32]}.jpg",
            "image_hash": image_hash,
            "dedupe_hash": db.dedupe_hash("receipt_scan", day, amount, merchant),
            "raw_extraction": {"needs_review": False, "extraction": {}},
        },
        timeout=30,
    )
    assert created.status_code in (200, 201), created.text[:200]
    return created.json()[0]


@pytest.fixture(scope="module")
def a_row_id(a_receipt_row: dict[str, Any]) -> str:
    return a_receipt_row["id"]


@pytest.fixture(autouse=True)
def test_signing_keys() -> Iterator[None]:
    """Overrides the root conftest's fake key fetch: these tests verify against the project's real JWKS."""
    auth._failures.clear()
    auth.signing_key_for = REAL_SIGNING_KEY_FOR
    yield
    auth.signing_key_for = REAL_SIGNING_KEY_FOR
    auth._failures.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The real app, with real settings: no dependency override."""
    yield TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_rows(base: str, service: dict[str, str], ids: dict[str, str]) -> Iterator[None]:
    """Remove the rows and receipts the tests created for B. The seeded B rows are left as they are."""
    yield
    for row in rows_for(base, service, f"user_id=eq.{ids['b']}&select=id,merchant,receipt_path"):
        if row.get("merchant") is None or row["merchant"] in SEEDED_B_MERCHANTS:
            continue
        if row.get("receipt_path"):
            httpx.delete(f"{base}/storage/v1/object/receipts/{row['receipt_path']}", headers=service, timeout=30)
        httpx.delete(f"{base}/rest/v1/transactions?id=eq.{row['id']}", headers=service, timeout=30)


# ---------------------------------------------------------------- real tokens, real JWKS

def test_both_users_tokens_verify_against_the_real_jwks(token_a: str, token_b: str, ids: dict[str, str]) -> None:
    settings = get_settings()
    assert str(auth.user_from_token(token_a, settings)) == ids["a"]
    assert str(auth.user_from_token(token_b, settings)) == ids["b"]


def test_a_forged_token_is_refused_by_the_real_jwks(client: TestClient) -> None:
    forged = jwt.encode(
        {"sub": "5b1f2e8a-0c3d-4e5f-8a9b-1c2d3e4f5a6b", "aud": "authenticated",
         "iss": f"{get_settings().supabase_url}/auth/v1", "iat": int(time.time()), "exp": int(time.time()) + 600},
        ec.generate_private_key(ec.SECP256R1()), algorithm="ES256", headers={"kid": "forged"},
    )
    assert client.get("/transactions?month=2026-10", headers=bearer(forged)).status_code == 401


def test_a_tampered_token_is_refused(client: TestClient, token_b: str, ids: dict[str, str]) -> None:
    header, payload, signature = token_b.split(".")
    claims = jwt.decode(token_b, options={"verify_signature": False})
    claims["sub"] = ids["a"]  # the owner's id, with B's signature
    import base64
    import json
    tampered_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    tampered = f"{header}.{tampered_payload}.{signature}"
    assert client.get("/transactions?month=2026-10", headers=bearer(tampered)).status_code == 401


# ---------------------------------------------------------------- the API, as each user

def test_a_lists_their_rows_and_b_lists_only_theirs(
    client: TestClient, token_a: str, token_b: str, base: str, service, ids: dict[str, str],
    b_own_row: dict[str, Any],
) -> None:
    october = "and=(txn_date.gte.2026-10-01,txn_date.lt.2026-11-01)&mode=eq.personal&select=id"
    a_expected = {r["id"] for r in rows_for(base, service, f"user_id=eq.{ids['a']}&{october}")}
    b_expected = {r["id"] for r in rows_for(base, service, f"user_id=eq.{ids['b']}&{october}")}

    a_seen = {r["id"] for r in client.get("/transactions?month=2026-10", headers=bearer(token_a)).json()}
    b_seen = {r["id"] for r in client.get("/transactions?month=2026-10", headers=bearer(token_b)).json()}

    assert a_seen == a_expected and len(a_expected) > 0
    assert b_seen == b_expected and len(b_expected) > 0
    assert a_seen.isdisjoint(b_seen)


def test_b_cannot_read_patch_or_delete_a_row(
    client: TestClient, token_b: str, base: str, service, a_row_id: str, a_receipt_row: dict[str, Any]
) -> None:
    assert client.get(f"/transactions/{a_row_id}", headers=bearer(token_b)).status_code == 404

    before = rows_for(base, service, f"id=eq.{a_row_id}&select=amount")[0]["amount"]
    assert client.patch(f"/transactions/{a_row_id}", json={"amount": 1}, headers=bearer(token_b)).status_code == 404
    assert rows_for(base, service, f"id=eq.{a_row_id}&select=amount")[0]["amount"] == before

    assert client.delete(f"/transactions/{a_row_id}", headers=bearer(token_b)).status_code == 404
    assert rows_for(base, service, f"id=eq.{a_row_id}&select=id"), "A's row must still exist"
    still = httpx.get(f"{base}/storage/v1/object/receipts/{a_receipt_row['receipt_path']}", headers=service, timeout=30)
    assert still.status_code == 200, "A's receipt object must still exist"


def test_b_cannot_get_a_signed_url_for_a_receipt(client: TestClient, token_b: str, a_row_id: str) -> None:
    assert client.get(f"/transactions/{a_row_id}/receipt-url", headers=bearer(token_b)).status_code == 404


def test_a_gets_a_working_signed_url_for_their_own_receipt(
    client: TestClient, token_a: str, a_row_id: str
) -> None:
    response = client.get(f"/transactions/{a_row_id}/receipt-url", headers=bearer(token_a))
    assert response.status_code == 200
    url = response.json()["url"]
    # The API returns an absolute URL: it joins Supabase's relative signed path to the Storage base.
    assert url.startswith("https://"), f"receipt URL must be absolute, got {url[:40]}"
    fetched = httpx.get(url, timeout=30)
    assert fetched.status_code == 200
    assert fetched.content == LEGACY_0_BYTES


# ---------------------------------------------------------------- dedupe: 409 never carries another user's row

def scan(client: TestClient, token: str, image: bytes, monkeypatch: pytest.MonkeyPatch, *, merchant: str,
         amount: str, day: date):
    monkeypatch.setattr("app.extractor.extract_from_image", lambda _image, _media: Extraction(
        txn_date=day, amount=Decimal(amount), merchant=merchant, category="food", type="expense"))
    return client.post("/transactions/scan", files={"file": ("r.jpg", image, "image/jpeg")}, headers=bearer(token))


def test_b_scanning_a_photo_a_saved_is_not_a_duplicate_and_leaks_nothing(
    client: TestClient, token_b: str, monkeypatch: pytest.MonkeyPatch, a_unshared_receipt: dict[str, Any],
    base: str, service, ids
) -> None:
    """Same photo and same dedupe key as A's receipt, which B does not hold: B gets a row of their own."""
    a_id = a_unshared_receipt["id"]
    photo = next(content for content in LEGACY_BYTES.values()
                 if hashlib.sha256(content).hexdigest() == a_unshared_receipt["image_hash"])
    response = scan(client, token_b, photo, monkeypatch, merchant=a_unshared_receipt["merchant"],
                    amount=str(a_unshared_receipt["amount"]), day=date.fromisoformat(a_unshared_receipt["txn_date"]))
    assert response.status_code == 201, response.text
    assert a_id not in response.text
    created = rows_for(base, service, f"id=eq.{response.json()['id']}&select=user_id")[0]
    assert created["user_id"] == ids["b"]
    assert client.delete(f"/transactions/{response.json()['id']}", headers=bearer(token_b)).status_code == 204


def test_a_409_for_b_carries_only_b_rows(
    client: TestClient, token_b: str, monkeypatch: pytest.MonkeyPatch, b_own_row: dict[str, Any], a_row_id: str
) -> None:
    """B re-scans B's own receipt: the duplicate answer is B's row, and A's id appears nowhere."""
    response = scan(client, token_b, b"fake receipt b-own-1", monkeypatch,
                    merchant="Kedai B Sendiri", amount="66.60", day=date(2026, 10, 25))
    assert response.status_code == 409
    assert response.json()["detail"]["transaction"]["id"] == b_own_row["id"]
    assert a_row_id not in response.text


def test_a_dedupe_key_match_in_b_s_own_rows_is_the_only_409_b_can_get(
    client: TestClient, token_b: str, monkeypatch: pytest.MonkeyPatch, b_own_row: dict[str, Any], a_row_id: str
) -> None:
    """Different photo, same merchant, amount and day as B's own row: the 409 names B's row, never A's."""
    response = scan(client, token_b, b"a photo that is not in the database", monkeypatch,
                    merchant="Kedai B Sendiri", amount="66.60", day=date(2026, 10, 25))
    assert response.status_code == 409
    assert response.json()["detail"]["transaction"]["id"] == b_own_row["id"]
    assert a_row_id not in response.text


def test_text_entries_are_stamped_with_the_caller(
    client: TestClient, token_b: str, monkeypatch: pytest.MonkeyPatch, base: str, service, ids
) -> None:
    monkeypatch.setattr("app.extractor.extract_from_text", lambda _text: Extraction(
        txn_date=date(2026, 10, 27), amount=Decimal("3.00"), merchant="Kedai Teks B", category="food", type="expense"))
    response = client.post("/transactions/text", json={"text": "kopi 3 ringgit", "user_id": ids["a"]}, headers=bearer(token_b))
    assert response.status_code == 201, response.text
    assert rows_for(base, service, f"id=eq.{response.json()['id']}&select=user_id")[0]["user_id"] == ids["b"]
    assert client.delete(f"/transactions/{response.json()['id']}", headers=bearer(token_b)).status_code == 204


def test_a_user_id_in_a_manual_body_never_writes_a(
    client: TestClient, token_b: str, base: str, service, ids
) -> None:
    before = len(rows_for(base, service, f"user_id=eq.{ids['a']}&select=id"))
    response = client.post("/transactions", json={"amount": 5, "user_id": ids["a"]}, headers=bearer(token_b))
    assert response.status_code == 422
    assert len(rows_for(base, service, f"user_id=eq.{ids['a']}&select=id")) == before


# ---------------------------------------------------------------- the database's own RLS, as the user

def test_rls_hides_a_rows_from_b_through_postgrest(base: str, env, token_a: str, token_b: str, a_row_id: str) -> None:
    key = env["SUPABASE_SERVICE_KEY"]
    as_b = httpx.get(f"{base}/rest/v1/transactions?id=eq.{a_row_id}&select=id",
                     headers={"apikey": key, "Authorization": f"Bearer {token_b}"}, timeout=30)
    as_a = httpx.get(f"{base}/rest/v1/transactions?id=eq.{a_row_id}&select=id",
                     headers={"apikey": key, "Authorization": f"Bearer {token_a}"}, timeout=30)
    assert as_b.status_code == 200 and as_b.json() == []
    assert as_a.status_code == 200 and [r["id"] for r in as_a.json()] == [a_row_id]


def test_rls_stops_b_writing_a_rows_through_postgrest(
    base: str, env, token_b: str, service, a_row_id: str
) -> None:
    key = env["SUPABASE_SERVICE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {token_b}", "Prefer": "return=representation"}
    patched = httpx.patch(f"{base}/rest/v1/transactions?id=eq.{a_row_id}", headers=headers,
                          json={"merchant": "Tukar Oleh B"}, timeout=30)
    deleted = httpx.delete(f"{base}/rest/v1/transactions?id=eq.{a_row_id}", headers=headers, timeout=30)
    assert patched.status_code in (200, 204) and patched.json() == []
    assert deleted.status_code in (200, 204) and deleted.json() == []
    assert rows_for(base, service, f"id=eq.{a_row_id}&select=merchant")[0]["merchant"] != "Tukar Oleh B"


def test_storage_rls_stops_b_reading_a_receipt(base: str, env, token_a: str, token_b: str, a_receipt_row) -> None:
    key = env["SUPABASE_SERVICE_KEY"]
    path = a_receipt_row["receipt_path"]
    as_b = httpx.get(f"{base}/storage/v1/object/receipts/{path}",
                     headers={"apikey": key, "Authorization": f"Bearer {token_b}"}, timeout=30)
    as_a = httpx.get(f"{base}/storage/v1/object/receipts/{path}",
                     headers={"apikey": key, "Authorization": f"Bearer {token_a}"}, timeout=30)
    assert as_b.status_code != 200, "B must not download A's receipt"
    assert as_a.status_code == 200
