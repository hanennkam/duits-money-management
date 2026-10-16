"""Multi-user isolation: one user never reads, changes, deletes or signs another user's data.

Two users, A and B, each call with a real ES256 token signed by the test key (see conftest). Supabase is an
in-memory fake whose signatures mirror app/db.py exactly: every helper requires the owner, and a row is visible
only to its owner. No network, no live database, no real keys.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import db
from app.models import Extraction
from conftest import token_for

pytestmark = pytest.mark.isolation

USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ROW_A = "a1111111-1111-4111-8111-111111111111"
ROW_A2 = "a2222222-2222-4222-8222-222222222222"
ROW_B = "b1111111-1111-4111-8111-111111111111"
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
SHARED_PHOTO = b"the same receipt photo, byte for byte"


def bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id)}"}


def make_row(
    row_id: str,
    owner: str,
    *,
    amount: str = "12.50",
    merchant: str = "Kedai Contoh",
    txn_date: date = date(2026, 10, 11),
    dedupe: str | None = None,
    image_hash: str | None = None,
) -> dict[str, Any]:
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
        "image_hash": image_hash,
        "source": "receipt_scan",
        "dedupe_hash": dedupe,
        "raw_extraction": {"needs_review": False, "extraction": {}},
    }


class FakeStore:
    """An in-memory transactions table and receipts bucket. Every call names its owner."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.removed: list[str] = []
        self.uploaded: list[str] = []
        self.signed: list[str] = []
        self.next_id = 0

    def seed(self, row: dict[str, Any]) -> None:
        self.rows[row["id"]] = row

    def owned(self, user_id: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows.values() if row["user_id"] == str(user_id)]

    def find(self, user_id: Any, **match: Any) -> dict[str, Any] | None:
        for row in self.owned(user_id):
            if all(row.get(key) == value for key, value in match.items()):
                return row
        return None


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any call that reaches the real Supabase client fails the test."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("isolation tests must not reach Supabase")

    monkeypatch.setattr("app.db.get_supabase", refuse)
    yield


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStore]:
    fake = FakeStore()
    fake.seed(make_row(ROW_A, USER_A, amount="100.00", merchant="Kedai A", image_hash=_hash(SHARED_PHOTO)))
    fake.seed(make_row(ROW_A2, USER_A, amount="30.00", merchant="Kedai A Dua"))

    def get_transaction(transaction_id: str, *, user_id: Any) -> dict[str, Any] | None:
        return fake.find(user_id, id=transaction_id)

    def list_transactions(start: date, end: date, mode: str, *, user_id: Any) -> list[dict[str, Any]]:
        rows = [
            row for row in fake.owned(user_id)
            if start.isoformat() <= row["txn_date"] < end.isoformat() and row["mode"] == mode
        ]
        return sorted(rows, key=lambda row: row["txn_date"], reverse=True)

    def update_transaction(transaction_id: str, patch: dict[str, Any], *, user_id: Any) -> dict[str, Any] | None:
        if fake.find(user_id, id=transaction_id) is None:
            return None
        fake.rows[transaction_id] = {**fake.rows[transaction_id], **patch}
        return dict(fake.rows[transaction_id])

    def delete_transaction(transaction_id: str, *, user_id: Any) -> bool:
        if fake.find(user_id, id=transaction_id) is None:
            return False
        del fake.rows[transaction_id]
        return True

    def insert_transaction(row: dict[str, Any], *, user_id: Any) -> dict[str, Any]:
        fake.next_id += 1
        stored = {**row, "user_id": str(user_id), "id": f"new-{fake.next_id}", "created_at": "2026-10-13T09:00:00+00:00"}
        fake.rows[stored["id"]] = stored
        return dict(stored)

    def find_by_dedupe_hash(dedupe: str, *, user_id: Any) -> dict[str, Any] | None:
        return fake.find(user_id, dedupe_hash=dedupe)

    def find_by_dedupe_hashes(hashes: list[str], *, user_id: Any) -> dict[str, Any] | None:
        return next((row for h in hashes if (row := fake.find(user_id, dedupe_hash=h))), None)

    def find_by_image_hash(image_hash: str, *, user_id: Any) -> dict[str, Any] | None:
        return fake.find(user_id, image_hash=image_hash)

    def upload_receipt(path: str, content: bytes, content_type: str, *, user_id: Any) -> str:
        _assert_owned_path(path, user_id)
        fake.uploaded.append(path)
        return path

    def delete_receipt(path: str, *, user_id: Any) -> None:
        _assert_owned_path(path, user_id)
        fake.removed.append(path)

    def create_receipt_url(path: str, expires_in: int, *, user_id: Any) -> str:
        _assert_owned_path(path, user_id)
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


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _assert_owned_path(path: str, user_id: Any) -> None:
    assert path.startswith(f"{user_id}/"), "storage object outside the owner's folder"


def receipt_extraction(merchant: str = "Kedai Contoh") -> Extraction:
    return Extraction(
        txn_date=date(2026, 10, 11), amount=Decimal("12.50"), merchant=merchant,
        category="food", type="expense",
    )


# ---------------------------------------------------------------- the caller's own data still works

def test_owner_still_reads_their_own_row(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions/{ROW_A}", headers=bearer(USER_A))
    assert response.status_code == 200
    assert response.json()["id"] == ROW_A


def test_owner_still_lists_their_own_rows(client: TestClient, store: FakeStore) -> None:
    response = client.get("/transactions?month=2026-10", headers=bearer(USER_A))
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {ROW_A, ROW_A2}


# ---------------------------------------------------------------- B cannot reach A's rows

def test_b_cannot_list_a_transactions(client: TestClient, store: FakeStore) -> None:
    response = client.get("/transactions?month=2026-10", headers=bearer(USER_B))
    assert response.status_code == 200
    assert response.json() == []


def test_b_cannot_read_a_transaction(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions/{ROW_A}", headers=bearer(USER_B))
    assert response.status_code == 404


def test_b_cannot_patch_a_transaction(client: TestClient, store: FakeStore) -> None:
    response = client.patch(f"/transactions/{ROW_A}", json={"amount": 1}, headers=bearer(USER_B))
    assert response.status_code == 404
    assert store.rows[ROW_A]["amount"] == 100.0


def test_b_cannot_delete_a_transaction_or_its_receipt(client: TestClient, store: FakeStore) -> None:
    response = client.delete(f"/transactions/{ROW_A}", headers=bearer(USER_B))
    assert response.status_code == 404
    assert ROW_A in store.rows
    assert store.removed == []


def test_b_cannot_get_a_receipt_url_for_a_transaction(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions/{ROW_A}/receipt-url", headers=bearer(USER_B))
    assert response.status_code == 404
    assert store.signed == []


def test_summary_counts_only_the_callers_rows(client: TestClient, store: FakeStore) -> None:
    store.seed(make_row(ROW_B, USER_B, amount="7.00", merchant="Kedai B"))
    response = client.get("/summary?month=2026-10", headers=bearer(USER_B))
    assert response.status_code == 200
    assert float(response.json()["total_expense"]) == 7.0


def test_a_user_id_in_the_query_is_ignored(client: TestClient, store: FakeStore) -> None:
    response = client.get(f"/transactions?month=2026-10&user_id={USER_A}", headers=bearer(USER_B))
    assert response.status_code == 200
    assert response.json() == []


def test_a_user_id_in_a_patch_body_is_refused_and_changes_nothing(client: TestClient, store: FakeStore) -> None:
    response = client.patch(
        f"/transactions/{ROW_A}", json={"amount": 1, "user_id": USER_B}, headers=bearer(USER_A)
    )
    assert response.status_code == 422
    assert store.rows[ROW_A]["user_id"] == USER_A


# ---------------------------------------------------------------- the 409 leak and dedupe are per owner

def test_a_photo_a_already_saved_is_not_a_duplicate_for_b(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same bytes as A's receipt: B gets a row of their own, and A's row is not returned."""
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction())
    response = client.post(
        "/transactions/scan", files={"file": ("r.jpg", SHARED_PHOTO, "image/jpeg")}, headers=bearer(USER_B)
    )
    assert response.status_code == 201
    assert response.json()["id"] not in {ROW_A, ROW_A2}
    assert ROW_A not in response.text


def test_a_duplicate_of_b_s_own_receipt_answers_409_with_b_s_row_only(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.seed(make_row(ROW_B, USER_B, image_hash=_hash(SHARED_PHOTO)))
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction())
    response = client.post(
        "/transactions/scan", files={"file": ("r.jpg", SHARED_PHOTO, "image/jpeg")}, headers=bearer(USER_B)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["transaction"]["id"] == ROW_B
    assert ROW_A not in response.text


def test_a_dedupe_match_in_a_409_body_is_always_the_callers_own_row(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A has the same merchant, amount and day as B's scan. B's 409 must not carry A's row."""
    same_key = db.dedupe_hash("receipt_scan", date(2026, 10, 11), Decimal("12.50"), "Kedai Contoh")
    store.seed(make_row("a3333333-3333-4333-8333-333333333333", USER_A, dedupe=same_key))
    store.seed(make_row(ROW_B, USER_B, dedupe=same_key))
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction())

    response = client.post(
        "/transactions/scan", files={"file": ("r.jpg", b"b-other-photo", "image/jpeg")}, headers=bearer(USER_B)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["transaction"]["id"] == ROW_B
    assert "a3333333-3333-4333-8333-333333333333" not in response.text


def test_a_dedupe_hash_of_a_does_not_block_b(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    same_key = db.dedupe_hash("receipt_scan", date(2026, 10, 11), Decimal("12.50"), "Kedai Contoh")
    store.seed(make_row("a3333333-3333-4333-8333-333333333333", USER_A, dedupe=same_key))
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction())

    response = client.post(
        "/transactions/scan", files={"file": ("r.jpg", b"b-photo-bytes", "image/jpeg")}, headers=bearer(USER_B)
    )
    assert response.status_code == 201
    assert response.json()["amount"] == 12.5


# ---------------------------------------------------------------- creates stamp the caller

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
    assert store.rows[response.json()["id"]]["user_id"] == USER_B


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


def test_scan_stores_the_receipt_under_the_callers_folder(
    client: TestClient, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.extractor.extract_from_image", lambda image, media_type: receipt_extraction("Kedai Dua"))
    response = client.post(
        "/transactions/scan", files={"file": ("r.jpg", b"b-fresh-photo", "image/jpeg")}, headers=bearer(USER_B)
    )
    assert response.status_code == 201
    [path] = store.uploaded
    assert re.fullmatch(rf"{USER_B}/\d{{4}}/\d{{2}}/[0-9a-f]{{32}}\.jpg", path)


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


def test_an_expired_token_is_401(client: TestClient, store: FakeStore) -> None:
    expired = token_for(USER_B, expires_in=-60)
    response = client.get("/transactions?month=2026-10", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_a_token_for_another_audience_is_401(client: TestClient, store: FakeStore) -> None:
    wrong_aud = token_for(USER_B, aud="anon")
    response = client.get("/transactions?month=2026-10", headers={"Authorization": f"Bearer {wrong_aud}"})
    assert response.status_code == 401


def test_a_token_signed_by_an_unknown_key_is_401(client: TestClient, store: FakeStore) -> None:
    forged = token_for(USER_B, key=OTHER_KEY)
    response = client.get("/transactions?month=2026-10", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


# ---------------------------------------------------------------- every helper takes an owner

TRANSACTION_AND_STORAGE_HELPERS = [
    "find_by_dedupe_hashes",
    "find_by_dedupe_hash",
    "find_by_image_hash",
    "get_transaction",
    "update_transaction",
    "delete_transaction",
    "insert_transaction",
    "list_transactions",
    "summarize",
    "upload_receipt",
    "delete_receipt",
    "create_receipt_url",
]


@pytest.mark.parametrize("name", TRANSACTION_AND_STORAGE_HELPERS)
def test_every_transaction_helper_requires_a_user_id(name: str) -> None:
    """A helper that can be called without an owner is how a filter gets forgotten. Make it impossible."""
    parameter = inspect.signature(getattr(db, name)).parameters.get("user_id")
    assert parameter is not None, f"{name} has no user_id parameter"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, f"{name}: user_id must be keyword-only"
    assert parameter.default is inspect.Parameter.empty, f"{name} must require user_id, not default it"


def test_only_the_db_module_talks_to_supabase() -> None:
    """The service-role client bypasses RLS, so nothing outside app/db.py may create or use it."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path.name
        for path in app_dir.glob("*.py")
        if path.name != "db.py" and "get_supabase" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
