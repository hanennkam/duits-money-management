"""Multi-user isolation: what must hold once every route is scoped to the caller.

Two users, A and B. Each sends a JWT signed by an ES256 key this test generates, and the app is pointed
at that key's public half through a fake key fetch. Supabase is an in-memory fake: a row is visible to a
database call only when the call carries the row's owner, which is the owner filter step 2 must add. No
network, no live database, no real keys.

Until step 2 lands these tests fail, because the app still has one shared API key and no owner filter.
They are marked xfail so the suite stays green today. Set MULTI_USER_READY to True when step 2 is in: the
markers go, and any route that forgets the owner filter turns the suite red.
"""

from __future__ import annotations

import inspect
import time
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

import jwt
from app import auth, db, extractor
from app.models import Extraction
from conftest import SETTINGS

pytestmark = pytest.mark.isolation

MULTI_USER_READY = False
UNTIL_STEP_2 = pytest.mark.xfail(not MULTI_USER_READY, strict=True, reason="multi-user isolation not in place yet (step 2)")
UNTIL_STEP_2_LOOSE = pytest.mark.xfail(
    not MULTI_USER_READY,
    strict=False,
    reason="passes today only because the old API-key check rejects every request (step 2)",
)

USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ROW_A = "a1111111-1111-4111-8111-111111111111"
ROW_A2 = "a2222222-2222-4222-8222-222222222222"
ISSUER = f"{SETTINGS.supabase_url}/auth/v1"
KID = "isolation-test-key"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def token(user_id: str, *, aud: str = "authenticated", expires_in: int = 3600, key: Any = SIGNING_KEY) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "aud": aud,
        "iss": ISSUER,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": KID})


def bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(user_id)}"}


def visible(row: dict[str, Any], user_id: str | None) -> bool:
    """The owner filter: a call that names no owner sees every row, which is today's behaviour."""
    return user_id is None or row.get("user_id") == user_id


def make_row(row_id: str, owner: str, *, amount: str = "12.50", merchant: str = "Kedai Contoh",
             txn_date: date = date(2026, 10, 11), dedupe: str | None = None) -> dict[str, Any]:
    return {
        "id": row_id,
        "user_id": owner,
        "created_at": "2026-10-11T12:00:00+00:00",
        "txn_date": txn_date.isoformat(),
        "amount": float(Decimal(amount)),
        "currency": "MYR",
        "merchant": merchant,
        "category": "food",
        "type": "expense",
        "mode": "personal",
        "items": None,
        "receipt_path": f"{owner}/2026/10/{row_id}.jpg",
        "image_hash": None,
        "source": "receipt_scan",
        "dedupe_hash": dedupe,
        "raw_extraction": {"needs_review": False, "extraction": {}},
    }


class FakeStore:
    """An in-memory transactions table and receipts bucket, filtered by owner when one is given."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.removed: list[str] = []
        self.uploaded: list[str] = []
        self.signed: list[str] = []
        self.extraction: Extraction | None = None

    def seed(self, row: dict[str, Any]) -> None:
        self.rows[row["id"]] = row

    def visible_rows(self, user_id: str | None) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows.values() if visible(row, user_id)]

    def find(self, user_id: str | None, **match: Any) -> dict[str, Any] | None:
        for row in self.rows.values():
            if visible(row, user_id) and all(row.get(key) == value for key, value in match.items()):
                return dict(row)
        return None


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any call that reaches the real Supabase client fails the test. Failed-attempt counts reset per test."""
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("isolation tests must not reach Supabase")

    monkeypatch.setattr("app.db.get_supabase", refuse)
    monkeypatch.setattr("app.auth.fetch_signing_keys", lambda *a, **k: {KID: SIGNING_KEY.public_key()}, raising=False)
    auth._failures.clear()
    yield
    auth._failures.clear()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStore]:
    fake = FakeStore()
    fake.seed(make_row(ROW_A, USER_A, amount="100.00", merchant="Kedai A"))
    fake.seed(make_row(ROW_A2, USER_A, amount="30.00", merchant="Kedai A Dua"))

    def get_transaction(transaction_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        return fake.find(user_id, id=transaction_id)

    def list_transactions(start: date, end: date, mode: str, *, user_id: str | None = None) -> list[dict[str, Any]]:
        rows = [
            row for row in fake.visible_rows(user_id)
            if start.isoformat() <= row["txn_date"] < end.isoformat() and row["mode"] == mode
        ]
        return sorted(rows, key=lambda row: row["txn_date"], reverse=True)

    def update_transaction(transaction_id: str, patch: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any] | None:
        row = fake.find(user_id, id=transaction_id)
        if row is None:
            return None
        fake.rows[transaction_id] = {**fake.rows[transaction_id], **patch}
        return dict(fake.rows[transaction_id])

    def delete_transaction(transaction_id: str, *, user_id: str | None = None) -> bool:
        if fake.find(user_id, id=transaction_id) is None:
            return False
        del fake.rows[transaction_id]
        return True

    def insert_transaction(row: dict[str, Any]) -> dict[str, Any]:
        stored = {**row, "id": f"new-{len(fake.rows) + 1}", "created_at": "2026-10-13T09:00:00+00:00"}
        fake.rows[stored["id"]] = stored
        return dict(stored)

    def find_by_dedupe_hash(dedupe: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        return fake.find(user_id, dedupe_hash=dedupe)

    def find_by_dedupe_hashes(hashes: list[str], *, user_id: str | None = None) -> dict[str, Any] | None:
        return next((r for h in hashes if (r := fake.find(user_id, dedupe_hash=h))), None)

    def find_by_image_hash(image_hash: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        return fake.find(user_id, image_hash=image_hash)

    def upload_receipt(path: str, content: bytes, content_type: str) -> str:
        fake.uploaded.append(path)
        return path

    def delete_receipt(path: str) -> None:
        fake.removed.append(path)

    def create_receipt_url(path: str, expires_in: int, *, user_id: str | None = None) -> str:
        fake.signed.append(path)
        return f"https://signed.example/{path}"

    for name, fn in {
        "get_transaction": get_transaction,
        "list_transactions": list_transactions,
        "update_transaction": update_transaction,
        "delete_transaction": delete_transaction,
        "insert_transaction": insert_transaction,
        "find_by_dedupe_hash": find_by_dedupe_hash,
        "find_by_dedupe_hashes": find_by_dedupe_hashes,
        "find_by_image_hash": find_by_image_hash,
        "upload_receipt": upload_receipt,
        "delete_receipt": delete_receipt,
        "create_receipt_url": create_receipt_url,
    }.items():
        monkeypatch.setattr(f"app.db.{name}", fn)
    yield fake


def receipt_extraction(merchant: str = "Kedai Contoh") -> Extraction:
    return Extraction(
        txn_date=date(2026, 10, 11), amount=Decimal("12.50"), merchant=merchant,
        category="food", type="expense",
    )


# ---------------------------------------------------------------- the caller's own data still works

@UNTIL_STEP_2
def test_owner_still_reads_their_own_row(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions/{ROW_A}", headers=bearer(USER_A))
    assert response.status_code == 200
    assert response.json()["id"] == ROW_A


@UNTIL_STEP_2
def test_owner_still_lists_their_own_rows(client: TestClient, store: FakeStore) -> None:
    response = client.get("/transactions?month=2026-10", headers=bearer(USER_A))
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {ROW_A, ROW_A2}


# ---------------------------------------------------------------- B cannot reach A's rows

@UNTIL_STEP_2
def test_b_cannot_list_a_transactions(client: TestClient, store: FakeStore) -> None:
    response = client.get("/transactions?month=2026-10", headers=bearer(USER_B))
    assert response.status_code == 200
    assert response.json() == []


@UNTIL_STEP_2
def test_b_cannot_read_a_transaction(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions/{ROW_A}", headers=bearer(USER_B))
    assert response.status_code == 404


@UNTIL_STEP_2
def test_b_cannot_patch_a_transaction(client: TestClient, store: FakeStore) -> None:
    response = client.patch(f"/transactions/{ROW_A}", json={"amount": 1}, headers=bearer(USER_B))
    assert response.status_code == 404
    assert store.rows[ROW_A]["amount"] == 100.0


@UNTIL_STEP_2
def test_b_cannot_delete_a_transaction_or_its_receipt(client: TestClient, store: FakeStore) -> None:
    response = client.delete(f"/transactions/{ROW_A}", headers=bearer(USER_B))
    assert response.status_code == 404
    assert ROW_A in store.rows
    assert store.removed == []


@UNTIL_STEP_2
def test_b_cannot_get_a_receipt_url_for_a_transaction(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions/{ROW_A}/receipt-url", headers=bearer(USER_B))
    assert response.status_code == 404
    assert store.signed == []


@UNTIL_STEP_2
def test_summary_counts_only_the_callers_rows(client: TestClient, store: FakeStore) -> None:
    store.seed(make_row("b1111111-1111-4111-8111-111111111111", USER_B, amount="7.00", merchant="Kedai B"))
    response = client.get("/summary?month=2026-10", headers=bearer(USER_B))
    assert response.status_code == 200
    assert float(response.json()["total_expense"]) == 7.0


# ---------------------------------------------------------------- dedupe is per owner

@UNTIL_STEP_2
def test_a_dedupe_hash_does_not_block_b(client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    same_key = db.dedupe_hash("receipt_scan", date(2026, 10, 11), Decimal("12.50"), "Kedai Contoh")
    store.seed(make_row("a3333333-3333-4333-8333-333333333333", USER_A, dedupe=same_key))
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction())

    response = client.post(
        "/transactions/scan",
        files={"file": ("receipt.jpg", b"b-photo-bytes", "image/jpeg")},
        headers=bearer(USER_B),
    )
    assert response.status_code == 201
    assert response.json()["amount"] == 12.5


# ---------------------------------------------------------------- creates stamp the caller

@UNTIL_STEP_2
def test_text_create_stamps_the_caller_and_ignores_a_body_user_id(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.extractor.extract_from_text", lambda text: receipt_extraction("Kedai Teks"))
    response = client.post(
        "/transactions/text",
        json={"text": "makan 12 ringgit", "mode": "personal", "user_id": USER_A},
        headers=bearer(USER_B),
    )
    assert response.status_code == 201
    created = store.rows[response.json()["id"]]
    assert created["user_id"] == USER_B


@UNTIL_STEP_2
def test_scan_create_stamps_the_caller_and_ignores_a_form_user_id(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction("Kedai Scan"))
    response = client.post(
        "/transactions/scan",
        data={"user_id": USER_A},
        files={"file": ("receipt.jpg", b"b-photo-bytes-2", "image/jpeg")},
        headers=bearer(USER_B),
    )
    assert response.status_code == 201
    assert store.rows[response.json()["id"]]["user_id"] == USER_B


@UNTIL_STEP_2
def test_manual_create_never_writes_a_body_user_id(client: TestClient, store: FakeStore) -> None:
    """Either the unknown field is rejected (422), or the row is stamped with the caller. Never A."""
    response = client.post(
        "/transactions",
        json={"amount": 5, "merchant": "Kedai Tangan", "user_id": USER_A},
        headers=bearer(USER_B),
    )
    assert response.status_code in (201, 422)
    if response.status_code == 201:
        assert store.rows[response.json()["id"]]["user_id"] == USER_B


# ---------------------------------------------------------------- tokens

@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/transactions?month=2026-10", None),
        ("GET", f"/transactions/{ROW_A}", None),
        ("PATCH", f"/transactions/{ROW_A}", {"amount": 1}),
        ("DELETE", f"/transactions/{ROW_A}", None),
        ("GET", f"/transactions/{ROW_A}/receipt-url", None),
        ("GET", "/summary?month=2026-10", None),
        ("POST", "/transactions", {"amount": 5}),
        ("POST", "/transactions/text", {"text": "makan 12 ringgit"}),
    ],
)
def test_no_credentials_is_401_on_every_protected_route(
    client: TestClient, store: FakeStore, method: str, path: str, body: Any
) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code == 401


@UNTIL_STEP_2_LOOSE
def test_an_expired_token_is_401(client: TestClient, store: FakeStore) -> None:
    expired = token(USER_B, expires_in=-60)
    response = client.get("/transactions?month=2026-10", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


@UNTIL_STEP_2_LOOSE
def test_a_token_for_another_audience_is_401(client: TestClient, store: FakeStore) -> None:
    wrong_aud = token(USER_B, aud="anon")
    response = client.get("/transactions?month=2026-10", headers={"Authorization": f"Bearer {wrong_aud}"})
    assert response.status_code == 401


@UNTIL_STEP_2_LOOSE
def test_a_token_signed_by_an_unknown_key_is_401(client: TestClient, store: FakeStore) -> None:
    forged = token(USER_B, key=OTHER_KEY)
    response = client.get("/transactions?month=2026-10", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


# ---------------------------------------------------------------- every helper takes an owner

TRANSACTION_HELPERS = [
    "find_by_dedupe_hashes",
    "find_by_dedupe_hash",
    "find_by_image_hash",
    "get_transaction",
    "update_transaction",
    "delete_transaction",
    "insert_transaction",
    "list_transactions",
    "summarize",
    "create_receipt_url",
]


@pytest.mark.parametrize("name", TRANSACTION_HELPERS)
@UNTIL_STEP_2
def test_every_transaction_helper_requires_a_user_id(name: str) -> None:
    """A helper that can be called without an owner is how a filter gets forgotten. Make it impossible."""
    parameter = inspect.signature(getattr(db, name)).parameters.get("user_id")
    assert parameter is not None, f"{name} has no user_id parameter"
    assert parameter.default is inspect.Parameter.empty, f"{name} must require user_id, not default it"
