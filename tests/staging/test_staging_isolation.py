"""Multi-user isolation against the REAL staging project: real Postgres, real Storage, real Auth, real JWKS.

Run only through scripts/run_staging_tests.py, which loads .env.staging before the app is imported. The
module refuses to run against the live project. It writes test rows and receipts to staging, and removes them.
Each user signs in with their own STAGING_USER_A_* / STAGING_USER_B_* credentials.

Nothing here is mocked except the Claude extraction, which is replaced with a fixed answer so the duplicate
checks can be driven by known merchants, dates and amounts. The image bytes and the dedupe keys are real.

Cleanup deletes the exact ids this module created, never rows found by name. Fixture teardown cannot run
when the process is killed (SIGKILL, a crashed machine, a CI timeout), so an interrupted run can leave
residue; every delete here is idempotent and safe to repeat, and NEXT_STEPS.md holds the staging-only
recovery procedure.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

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
from conftest import redact_secrets  # noqa: E402  (tests/ is on sys.path via the root conftest)

REAL_SIGNING_KEY_FOR = auth.signing_key_for  # captured before the root conftest can replace it
LEGACY_0_BYTES = b"fake receipt legacy-0"

# B's fixture receipt is unique to this run. A fixed identity would collide with its own earlier copy,
# because `0002 down`/`up` backfills every row to one owner and leaves the previous copy behind — and
# `0002 down`'s rollback guard then refuses (correctly) when two owners share a hash. Tests read these
# rather than hardcoding values, so they cannot drift from what the fixture stores.
B_TOKEN = uuid.uuid4().hex[:8]
B_MERCHANT = f"Kedai B {B_TOKEN}"
B_DAY = date(2026, 10, 25)
B_AMOUNT = "66.60"
B_PHOTO = f"fake receipt b-own-{B_TOKEN}".encode()

# Every transaction this module creates is recorded here by id, with the receipt path the write returned,
# as soon as the response arrives. Cleanup drains these ids and never looks rows up by merchant, so a NULL
# merchant or one of B's seeded names cannot hide a test row. The registry is per-process: a hard kill
# loses it, which is why NEXT_STEPS.md documents the read-only residue check and the recovery steps.
CREATED_TRANSACTIONS: dict[str, str | None] = {}

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
    """The staging settings, read from the file, after a refusal for the live project.

    Secret-shaped values come back wrapped as `Secret`, so a traceback can never print a key from here.
    """
    values = dotenv_values(ENV_FILE)
    ref = project_ref(values.get("SUPABASE_URL", ""))
    assert ref != LIVE_PROJECT_REF, "refusing: this is the live project"
    assert ref == STAGING_PROJECT_REF, "refusing: not the staging project"
    assert project_ref(os.environ.get("SUPABASE_URL", "")) == STAGING_PROJECT_REF, (
        "the app must be configured from .env.staging (use scripts/run_staging_tests.py)"
    )
    return redact_secrets({key: value for key, value in values.items() if value is not None})


@pytest.fixture(scope="module")
def base(env: dict[str, str]) -> str:
    return env["SUPABASE_URL"].rstrip("/")


@pytest.fixture(scope="module")
def service(env: dict[str, str]) -> dict[str, str]:
    """Service-key headers, wrapped the same way: `money_rows`' assertion failure once printed these."""
    return redact_secrets(
        {"apikey": env["SUPABASE_SERVICE_KEY"], "Authorization": f"Bearer {env['SUPABASE_SERVICE_KEY']}"}
    )


def sign_in(base: str, env: dict[str, str], email_var: str, password_var: str) -> str:
    """A password grant for the account named by two environment variable NAMES, never by a value here."""
    response = httpx.post(
        f"{base}/auth/v1/token?grant_type=password",
        headers={"apikey": env["SUPABASE_SERVICE_KEY"], "Content-Type": "application/json"},
        json={"email": env[email_var], "password": env[password_var]},
        timeout=30,
    )
    assert response.status_code == 200, f"sign-in failed with HTTP {response.status_code}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def token_a(base: str, env: dict[str, str]) -> str:
    """A's own staging account; the credentials are the runner's, not a fixed address in this file."""
    return sign_in(base, env, "STAGING_USER_A_EMAIL", "STAGING_USER_A_PASSWORD")


@pytest.fixture(scope="module")
def token_b(base: str, env: dict[str, str]) -> str:
    return sign_in(base, env, "STAGING_USER_B_EMAIL", "STAGING_USER_B_PASSWORD")


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
    """B's own receipt row: the one the duplicate tests expect to be named in a 409.

    It is created, not looked up, because a `down`/`up` cycle backfills **every** row to one owner and
    leaves the previous copy behind under someone else. Its identity is unique to this run so the two can
    never share a hash. `cleanup_test_rows` removes it by id at the end of the module.
    """
    image_hash = hashlib.sha256(B_PHOTO).hexdigest()
    created = httpx.post(
        f"{base}/rest/v1/transactions",
        headers={**service, "Prefer": "return=representation"},
        json={
            "user_id": ids["b"],
            "txn_date": B_DAY.isoformat(),
            "amount": float(Decimal(B_AMOUNT)),
            "merchant": B_MERCHANT,
            "category": "food",
            "type": "expense",
            "mode": "personal",
            "source": "receipt_scan",
            "receipt_path": f"{ids['b']}/2026/10/{image_hash[:32]}.jpg",
            "image_hash": image_hash,
            "dedupe_hash": db.dedupe_hash("receipt_scan", B_DAY, Decimal(B_AMOUNT), B_MERCHANT),
            "raw_extraction": {"needs_review": False, "extraction": {}},
        },
        timeout=30,
    )
    assert created.status_code in (200, 201), created.text[:200]
    row = created.json()[0]
    CREATED_TRANSACTIONS[row["id"]] = row.get("receipt_path")
    return row


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


SUCCESSFUL_DELETE = (200, 204)


def _storage_headers(service: dict[str, str]) -> dict[str, str]:
    """Only the two credential headers: a JSON content-type makes Storage refuse an empty-bodied delete."""
    return {"apikey": service["apikey"], "Authorization": service["Authorization"]}


def delete_receipt_object(base: str, service: dict[str, str], path: str, *, owner_id: str) -> None:
    """Delete one receipt this module created, or prove it is already gone.

    A 404 is success on a repeated run. Any other unexpected answer is raised, so cleanup cannot report
    a clean module while the object is still there. The owner-folder assertion aims the service key only
    at a path this test wrote under its own user, never at another owner's object.
    """
    assert path.startswith(f"{owner_id}/"), f"refusing to delete a receipt outside {owner_id}'s folder"
    response = httpx.delete(
        f"{base}/storage/v1/object/receipts/{path}",
        headers=_storage_headers(service),
        timeout=30,
    )
    if response.status_code == 404 or (
        response.status_code == 400 and "not found" in response.text.lower()
    ):
        return
    if response.status_code not in SUCCESSFUL_DELETE:
        raise AssertionError(
            f"receipt {path} was not deleted: HTTP {response.status_code} {response.text[:200]}"
        )
    # Storage can answer success and still serve the bytes; only a 200 here means it truly remains.
    still_there = httpx.get(
        f"{base}/storage/v1/object/receipts/{path}", headers=_storage_headers(service), timeout=30
    )
    if still_there.status_code == 200:
        raise AssertionError(f"receipt {path} is still downloadable after a successful delete")


def delete_row(base: str, service: dict[str, str], table: str, row_id: str, *, owner_id: str) -> None:
    """Delete one row by id and owner. A missing row is success: cleanup must be safe to repeat."""
    response = httpx.delete(
        f"{base}/rest/v1/{table}?id=eq.{row_id}&user_id=eq.{owner_id}", headers=service, timeout=30
    )
    if response.status_code not in SUCCESSFUL_DELETE:
        raise AssertionError(
            f"{table} row {row_id} was not deleted: HTTP {response.status_code} {response.text[:200]}"
        )


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_rows(base: str, service: dict[str, str], ids: dict[str, str]) -> Iterator[None]:
    """Remove exactly the transactions and receipts this module created, by id.

    The receipt goes first. If that fails, the row is kept so the object keeps a pointer and the failure
    is raised at the end; deleting the row first would turn a failed object delete into a silent orphan.
    """
    yield
    problems: list[str] = []
    for transaction_id, known_path in list(CREATED_TRANSACTIONS.items()):
        try:
            found = rows_for(base, service, f"id=eq.{transaction_id}&select=id,user_id,receipt_path")
        except Exception as exc:  # a transport failure must not stop the other ids
            problems.append(f"transaction {transaction_id}: could not read the row ({exc})")
            found = []
        path = known_path
        if found:
            if found[0]["user_id"] != ids["b"]:
                problems.append(f"transaction {transaction_id} is not B's; left alone")
                continue
            path = found[0].get("receipt_path") or known_path
        if path:
            try:
                delete_receipt_object(base, service, path, owner_id=ids["b"])
            except Exception as exc:
                problems.append(str(exc))
                problems.append(f"transaction {transaction_id} kept so its receipt can be found again")
                continue
        try:
            delete_row(base, service, "transactions", transaction_id, owner_id=ids["b"])
        except Exception as exc:
            problems.append(str(exc))
    CREATED_TRANSACTIONS.clear()
    if problems:
        raise AssertionError("transaction cleanup failed:\n" + "\n".join(problems))


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
    created_body = response.json()
    CREATED_TRANSACTIONS[created_body["id"]] = created_body.get("receipt_path")
    created = rows_for(base, service, f"id=eq.{created_body['id']}&select=user_id")[0]
    assert created["user_id"] == ids["b"]
    assert client.delete(f"/transactions/{created_body['id']}", headers=bearer(token_b)).status_code == 204


def test_a_409_for_b_carries_only_b_rows(
    client: TestClient, token_b: str, monkeypatch: pytest.MonkeyPatch, b_own_row: dict[str, Any], a_row_id: str
) -> None:
    """B re-scans B's own receipt: the duplicate answer is B's row, and A's id appears nowhere."""
    response = scan(client, token_b, B_PHOTO, monkeypatch,
                    merchant=B_MERCHANT, amount=B_AMOUNT, day=B_DAY)
    assert response.status_code == 409
    assert response.json()["detail"]["transaction"]["id"] == b_own_row["id"]
    assert a_row_id not in response.text


def test_a_dedupe_key_match_in_b_s_own_rows_is_the_only_409_b_can_get(
    client: TestClient, token_b: str, monkeypatch: pytest.MonkeyPatch, b_own_row: dict[str, Any], a_row_id: str
) -> None:
    """Different photo, same merchant, amount and day as B's own row: the 409 names B's row, never A's."""
    response = scan(client, token_b, b"a photo that is not in the database", monkeypatch,
                    merchant=B_MERCHANT, amount=B_AMOUNT, day=B_DAY)
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
    created_body = response.json()
    CREATED_TRANSACTIONS[created_body["id"]] = created_body.get("receipt_path")
    assert rows_for(base, service, f"id=eq.{created_body['id']}&select=user_id")[0]["user_id"] == ids["b"]
    assert client.delete(f"/transactions/{created_body['id']}", headers=bearer(token_b)).status_code == 204


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


# ---------------------------------------------------------------- 0003: money settings, commitments, budget
# These run only when 0003 is applied. They are what proves the two things the migration's FORCE row level
# security could break: the service-key API still reads and writes its own rows with the policies forced
# on, and anon/publishable still gets nothing at all. `0003 down` leaves the project without these tables,
# so the fixtures skip with the reason rather than failing the whole module.

# Commitment id -> owner id, so cleanup deletes exactly what a test made and never scans by name.
CREATED_COMMITMENTS: dict[str, str] = {}
SETTINGS_MONTH = "2026-10"
MONEY_TABLES = ("user_finance_settings", "monthly_commitments", "commitment_payments")
# The column that identifies a row: the settings table is one row per owner and is keyed by user_id, the
# other two by id. Reads that only want to know "is a row there" name the key explicitly — the first version
# selected `id` from all three and PostgREST refused the settings read, failing the test for the wrong reason.
MONEY_KEY_COLUMN = {"user_finance_settings": "user_id", "monthly_commitments": "id", "commitment_payments": "id"}


@pytest.fixture(scope="module")
def money_tables(base: str, service: dict[str, str]) -> None:
    """Skip when 0003 is not applied: this module also runs between rehearsals."""
    response = httpx.get(f"{base}/rest/v1/monthly_commitments?select=id&limit=1", headers=service, timeout=30)
    if response.status_code != 200:
        pytest.skip(
            "0003 is not applied to staging "
            "(run migrations/0003_budget_commitments.up.sql, then verify_after_0003.sql)"
        )


@pytest.fixture(scope="module", autouse=True)
def cleanup_money_rows(base: str, service: dict[str, str]) -> Iterator[None]:
    """Remove the commitments these tests created, by id and owner; their paid marks cascade.

    Every id is attempted even if one fails, so a single bad delete cannot hide the rest, and the
    collected problems are raised at the end instead of disappearing into teardown.
    """
    yield
    problems: list[str] = []
    for commitment_id, owner_id in list(CREATED_COMMITMENTS.items()):
        try:
            delete_row(base, service, "monthly_commitments", commitment_id, owner_id=owner_id)
        except Exception as exc:
            problems.append(str(exc))
    CREATED_COMMITMENTS.clear()
    if problems:
        raise AssertionError("commitment cleanup failed:\n" + "\n".join(problems))


@pytest.fixture(scope="module")
def restore_b_settings(base: str, service: dict[str, str], ids: dict[str, str]) -> Iterator[None]:
    """Put B's settings row back exactly as it was, including deleting it when there was no row.

    `before` is read directly with the service key, so "no row" is distinguishable from a row of
    defaults. The restore is checked: a write that answers a non-success, or a read-back that differs,
    fails the module instead of leaving altered settings behind.
    """
    before = money_rows(base, service, "user_finance_settings", f"user_id=eq.{ids['b']}&select=*")
    yield
    problems: list[str] = []
    try:
        if before:
            response = httpx.post(
                f"{base}/rest/v1/user_finance_settings?on_conflict=user_id",
                headers={**service, "Prefer": "resolution=merge-duplicates"},
                json=before[0],
                timeout=30,
            )
            if response.status_code not in (200, 201):
                problems.append(f"B settings restore answered HTTP {response.status_code}")
            else:
                after = money_rows(
                    base, service, "user_finance_settings", f"user_id=eq.{ids['b']}&select=*"
                )
                stable = ("user_id", "opening_balance", "monthly_budget", "currency")
                if not after or any(after[0].get(key) != before[0].get(key) for key in stable):
                    problems.append("B settings did not read back as they were before the test")
        else:
            response = httpx.delete(
                f"{base}/rest/v1/user_finance_settings?user_id=eq.{ids['b']}", headers=service, timeout=30
            )
            if response.status_code not in (200, 204):
                problems.append(f"B settings restore-to-absence answered HTTP {response.status_code}")
            elif money_rows(
                base, service, "user_finance_settings", f"user_id=eq.{ids['b']}&select=user_id"
            ):
                problems.append("B settings row still exists; it did not exist before the test")
    except Exception as exc:
        problems.append(f"B settings restore failed: {exc}")
    if problems:
        raise AssertionError("settings cleanup failed:\n" + "\n".join(problems))


def money_rows(base: str, service: dict[str, str], table: str, query: str) -> list[dict[str, Any]]:
    response = httpx.get(f"{base}/rest/v1/{table}?{query}", headers=service, timeout=30)
    assert response.status_code == 200, response.text[:200]
    return response.json()


def test_the_api_still_reads_and_writes_with_force_rls_on(
    client: TestClient, token_b: str, base: str, service: dict[str, str], ids: dict[str, str],
    money_tables: None, restore_b_settings: None,
) -> None:
    """The service key bypasses RLS, and FORCE must not change that: the endpoint path is the proof."""
    settings = client.get("/finance/settings", headers=bearer(token_b))
    assert settings.status_code == 200 and settings.json()["user_id"] == ids["b"]

    written = client.put(
        "/finance/settings", headers=bearer(token_b),
        json={"opening_balance": 250.5, "monthly_budget": 1000},
    )
    assert written.status_code == 200 and written.json()["opening_balance"] == 250.5

    created = client.post(
        "/commitments", headers=bearer(token_b),
        json={"name": "Kedai Sewa Staging", "amount": 300, "day_of_month": 15},
    )
    assert created.status_code == 201, created.text
    commitment_id = created.json()["id"]
    CREATED_COMMITMENTS[commitment_id] = ids["b"]

    # The row is really in the table, not only in the response: the service key reads it back.
    assert money_rows(base, service, "monthly_commitments", f"id=eq.{commitment_id}&select=user_id")[0][
        "user_id"
    ] == ids["b"]

    marked = client.post(
        f"/commitments/{commitment_id}/paid", headers=bearer(token_b), json={"month": SETTINGS_MONTH}
    )
    assert marked.status_code == 200 and marked.json()["paid"] is True

    # The summary agrees with the rows the API just listed: no figure is stored, so they cannot drift.
    listed = client.get(f"/commitments?month={SETTINGS_MONTH}", headers=bearer(token_b)).json()
    assert next(row for row in listed if row["id"] == commitment_id)["paid"] is True
    expected_unpaid = sum(
        float(row["amount"]) for row in listed if row["active"] and not row["paid"]
    )
    summary = client.get(f"/finance/summary?month={SETTINGS_MONTH}", headers=bearer(token_b)).json()
    assert round(summary["unpaid_commitments"], 2) == round(expected_unpaid, 2)
    assert summary["monthly_budget"] == 1000.0

    undo = client.delete(
        f"/commitments/{commitment_id}/paid?month={SETTINGS_MONTH}", headers=bearer(token_b)
    )
    assert undo.status_code == 204
    unmarked = client.get(f"/commitments?month={SETTINGS_MONTH}", headers=bearer(token_b)).json()
    assert next(row for row in unmarked if row["id"] == commitment_id)["paid"] is False

    patched = client.patch(
        f"/commitments/{commitment_id}", headers=bearer(token_b), json={"amount": 320}
    )
    assert patched.status_code == 200 and patched.json()["amount"] == 320.0

    assert client.delete(f"/commitments/{commitment_id}", headers=bearer(token_b)).status_code == 204
    assert money_rows(base, service, "monthly_commitments", f"id=eq.{commitment_id}&select=id") == []


def test_anon_can_neither_read_nor_write_the_money_tables(
    base: str, env: dict[str, str], service: dict[str, str], money_tables: None
) -> None:
    """The policies are `to authenticated`, so the publishable key gets a refusal or an empty answer."""
    anon = {"apikey": env["SUPABASE_PUBLISHABLE_KEY"]}
    ghost = str(uuid.uuid4())  # an owner that exists nowhere, so every write is identifiable afterwards

    for table in MONEY_TABLES:
        rows_read = httpx.get(
            f"{base}/rest/v1/{table}?select={MONEY_KEY_COLUMN[table]}", headers=anon, timeout=30
        )
        assert rows_read.status_code != 200 or rows_read.json() == [], table

    for table, body in (
        ("user_finance_settings", {"user_id": ghost, "opening_balance": 1, "monthly_budget": 1}),
        ("monthly_commitments", {"user_id": ghost, "name": "Anon", "amount": 1, "day_of_month": 1}),
        (
            "commitment_payments",
            {"user_id": ghost, "commitment_id": str(uuid.uuid4()), "month": SETTINGS_MONTH},
        ),
    ):
        written = httpx.post(
            f"{base}/rest/v1/{table}",
            headers={**anon, "Prefer": "return=representation"},
            json=body,
            timeout=30,
        )
        assert written.status_code in (401, 403), f"{table}: {written.status_code} {written.text[:120]}"

    # And nothing slipped in behind the refusal.
    for table in MONEY_TABLES:
        assert money_rows(base, service, table, f"user_id=eq.{ghost}&select={MONEY_KEY_COLUMN[table]}") == [], table


def test_b_cannot_see_change_or_delete_a_commitment_through_postgrest(
    base: str, env: dict[str, str], token_a: str, token_b: str, ids: dict[str, str], service: dict[str, str],
    money_tables: None,
) -> None:
    """The same check 0002 got for transactions, on the new table and with the policies forced."""
    key = env["SUPABASE_SERVICE_KEY"]
    a_headers = {"apikey": key, "Authorization": f"Bearer {token_a}", "Prefer": "return=representation"}
    b_headers = {"apikey": key, "Authorization": f"Bearer {token_b}", "Prefer": "return=representation"}

    created = httpx.post(
        f"{base}/rest/v1/monthly_commitments",
        headers=a_headers,
        json={"user_id": ids["a"], "name": "Sewa Staging A", "amount": 150, "day_of_month": 5},
        timeout=30,
    )
    assert created.status_code in (200, 201), created.text[:200]
    commitment = created.json()[0]
    CREATED_COMMITMENTS[commitment["id"]] = ids["a"]

    seen = httpx.get(
        f"{base}/rest/v1/monthly_commitments?id=eq.{commitment['id']}&select=*", headers=b_headers, timeout=30
    )
    patched = httpx.patch(
        f"{base}/rest/v1/monthly_commitments?id=eq.{commitment['id']}",
        headers=b_headers, json={"amount": 1}, timeout=30,
    )
    deleted = httpx.delete(
        f"{base}/rest/v1/monthly_commitments?id=eq.{commitment['id']}", headers=b_headers, timeout=30
    )
    assert seen.status_code == 200 and seen.json() == []
    assert patched.status_code in (200, 204) and patched.json() == []
    assert deleted.status_code in (200, 204) and deleted.json() == []
    assert money_rows(base, service, "monthly_commitments", f"id=eq.{commitment['id']}&select=amount")[0][
        "amount"
    ] == 150.0

    # B may not hand a row to A either: the INSERT policy's WITH CHECK refuses it.
    smuggled = httpx.post(
        f"{base}/rest/v1/monthly_commitments",
        headers=b_headers,
        json={"user_id": ids["a"], "name": "Samseng B", "amount": 5, "day_of_month": 5},
        timeout=30,
    )
    assert smuggled.status_code in (401, 403), smuggled.text[:200]

    # And a row B creates is invisible to A.
    b_own = httpx.post(
        f"{base}/rest/v1/monthly_commitments",
        headers=b_headers,
        json={"user_id": ids["b"], "name": "Sewa Staging B", "amount": 60, "day_of_month": 6},
        timeout=30,
    )
    assert b_own.status_code in (200, 201), b_own.text[:200]
    CREATED_COMMITMENTS[b_own.json()[0]["id"]] = ids["b"]
    a_sees = httpx.get(
        f"{base}/rest/v1/monthly_commitments?id=eq.{b_own.json()[0]['id']}&select=id",
        headers=a_headers, timeout=30,
    )
    assert a_sees.status_code == 200 and a_sees.json() == []


def test_a_paid_mark_cannot_point_at_another_owners_commitment(
    base: str, env: dict[str, str], token_a: str, token_b: str, ids: dict[str, str], service: dict[str, str],
    money_tables: None,
) -> None:
    """The composite foreign key, which is the guard that holds even if the API's own check is skipped."""
    key = env["SUPABASE_SERVICE_KEY"]
    created = httpx.post(
        f"{base}/rest/v1/monthly_commitments",
        headers={**service, "Prefer": "return=representation"},
        json={"user_id": ids["a"], "name": "Sewa Untuk FK", "amount": 90, "day_of_month": 7},
        timeout=30,
    )
    assert created.status_code in (200, 201), created.text[:200]
    a_commitment = created.json()[0]["id"]
    CREATED_COMMITMENTS[a_commitment] = ids["a"]

    # B claims A's commitment: (commitment_id, user_id) has no such parent row, so the FK refuses it.
    as_b_for_a = httpx.post(
        f"{base}/rest/v1/commitment_payments",
        headers={"apikey": key, "Authorization": f"Bearer {token_b}", "Prefer": "return=representation"},
        json={"user_id": ids["b"], "commitment_id": a_commitment, "month": SETTINGS_MONTH},
        timeout=30,
    )
    assert as_b_for_a.status_code == 409, as_b_for_a.text[:200]

    # B filing a mark under A's name fails earlier, on the policy's WITH CHECK.
    as_b_named_a = httpx.post(
        f"{base}/rest/v1/commitment_payments",
        headers={"apikey": key, "Authorization": f"Bearer {token_b}", "Prefer": "return=representation"},
        json={"user_id": ids["a"], "commitment_id": a_commitment, "month": SETTINGS_MONTH},
        timeout=30,
    )
    assert as_b_named_a.status_code in (401, 403), as_b_named_a.text[:200]

    assert money_rows(
        base, service, "commitment_payments", f"commitment_id=eq.{a_commitment}&select=id"
    ) == []


def test_the_view_is_not_readable_with_a_user_token(
    base: str, env: dict[str, str], token_b: str, money_tables: None
) -> None:
    """`revoke all` on the view is the gate: it has no policy of its own to fall back on."""
    key = env["SUPABASE_SERVICE_KEY"]
    response = httpx.get(
        f"{base}/rest/v1/transaction_totals?select=user_id,total_expense",
        headers={"apikey": key, "Authorization": f"Bearer {token_b}"},
        timeout=30,
    )
    assert response.status_code in (401, 403), response.text[:200]


def test_the_view_agrees_with_the_owners_own_rows(
    base: str, service: dict[str, str], ids: dict[str, str], money_tables: None
) -> None:
    """The view is what the API sums for the balance, so it has to agree with the rows themselves."""
    rows = rows_for(base, service, f"user_id=eq.{ids['b']}&select=txn_date,amount,type,mode")
    expected_expense = sum(
        Decimal(str(row["amount"])) for row in rows if row["type"] == "expense"
    )
    expected_income = sum(Decimal(str(row["amount"])) for row in rows if row["type"] == "income")

    totals = money_rows(base, service, "transaction_totals", f"user_id=eq.{ids['b']}&select=*")

    assert totals, "B has seeded rows, so the view must have at least one"
    assert all(row["user_id"] == ids["b"] for row in totals)
    assert all(re.match(r"^\d{4}-\d{2}-01$", row["month"]) for row in totals)  # a month, first of it
    assert sum(Decimal(str(row["total_expense"] or 0)) for row in totals) == expected_expense
    assert sum(Decimal(str(row["total_income"] or 0)) for row in totals) == expected_income
    assert sum(row["row_count"] for row in totals) == len(rows)
