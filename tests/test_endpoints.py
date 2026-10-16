"""The single-transaction endpoints: create, get, patch, delete, signed receipt URL.

Supabase is mocked with an in-memory row; nothing here touches the network.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from conftest import HEADERS, TEST_USER

ROW_ID = "11111111-1111-1111-1111-111111111111"
RECEIPT_PATH = f"{TEST_USER}/2026/10/abc123.jpg"

ROW: dict[str, Any] = {
    "id": ROW_ID,
    "user_id": TEST_USER,
    "created_at": "2026-10-11T12:00:00+00:00",
    "txn_date": "2026-10-11",
    "amount": 15.08,
    "currency": "MYR",
    "merchant": "Restoran Nasi Pelita",
    "category": "food",
    "type": "expense",
    "mode": "personal",
    "items": [{"name": "Nasi Lemak Ayam", "qty": 1, "price": 8.5}],
    "receipt_path": RECEIPT_PATH,
    "image_hash": "a" * 64,
    "source": "receipt_scan",
    "dedupe_hash": "b" * 64,
    "raw_extraction": {"needs_review": True, "extraction": {}},
}


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """An in-memory stand-in for the transactions table plus the storage bucket."""
    state: dict[str, Any] = {"row": dict(ROW), "patches": [], "removed": [], "signed": []}

    def owned(user_id: Any) -> bool:
        return state["row"] is not None and state["row"]["user_id"] == str(user_id)

    def get(transaction_id: str, *, user_id: Any) -> dict[str, Any] | None:
        return state["row"] if owned(user_id) and transaction_id == ROW_ID else None

    def update(transaction_id: str, patch: dict[str, Any], *, user_id: Any) -> dict[str, Any] | None:
        state["patches"].append(patch)
        if not owned(user_id):
            return None
        state["row"] = {**state["row"], **patch}
        return state["row"]

    def delete(transaction_id: str, *, user_id: Any) -> bool:
        existed = owned(user_id) and transaction_id == ROW_ID
        if existed:
            state["row"] = None
        return existed

    def delete_receipt(path: str, *, user_id: Any) -> None:
        state["removed"].append(path)

    def create_receipt_url(path: str, ttl: int, *, user_id: Any) -> str:
        state["signed"].append((path, ttl))
        return f"https://signed.example/{path}"

    monkeypatch.setattr("app.db.get_transaction", get)
    monkeypatch.setattr("app.db.update_transaction", update)
    monkeypatch.setattr("app.db.delete_transaction", delete)
    monkeypatch.setattr("app.db.delete_receipt", delete_receipt)
    monkeypatch.setattr("app.db.create_receipt_url", create_receipt_url)
    yield state


@pytest.fixture
def created(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture what POST /transactions inserts, with the dedupe lookup mocked out."""
    state: dict[str, Any] = {"rows": [], "lookups": []}

    def find(dedupe: str, *, user_id: Any) -> dict[str, Any] | None:
        state["lookups"].append(dedupe)
        return next(
            (row for row in state["rows"] if row["dedupe_hash"] == dedupe and row["user_id"] == str(user_id)),
            None,
        )

    def insert(row: dict[str, Any], *, user_id: Any) -> dict[str, Any]:
        stored = {
            **row,
            "user_id": str(user_id),
            "id": str(len(state["rows"])),
            "created_at": "2026-10-13T09:00:00+00:00",
        }
        state["rows"].append(stored)
        return stored

    monkeypatch.setattr("app.db.find_by_dedupe_hash", find)
    monkeypatch.setattr("app.db.insert_transaction", insert)
    yield state


def test_create_transaction_stores_a_manual_row(
    client: TestClient, created: dict[str, Any]
) -> None:
    response = client.post(
        "/transactions",
        headers=HEADERS,
        json={
            "amount": 12.5,
            "txn_date": "2026-10-11",
            "merchant": "Kopitiam Ali",
            "category": "food",
            "type": "expense",
            "mode": "personal",
            "note": "lunch with the team",
        },
    )

    assert response.status_code == 201
    assert response.json()["amount"] == 12.5
    row = created["rows"][0]
    assert row["source"] == "manual"
    assert row["txn_date"] == "2026-10-11"
    assert row["amount"] == 12.5
    assert row["currency"] == "MYR"
    assert row["category"] == "food"
    assert row["raw_extraction"] == {"needs_review": False, "note": "lunch with the team"}
    assert row["dedupe_hash"] is None  # a typed row is deliberate, so it is never deduped
    assert created["lookups"] == []  # and the dedupe table is not even asked
    assert row["receipt_path"] is None
    assert row["image_hash"] is None
    assert row["items"] is None


def test_create_transaction_defaults_for_a_bare_amount(
    client: TestClient, created: dict[str, Any]
) -> None:
    """The sheet can send just an amount: today, expense, personal, no category, no note."""
    response = client.post("/transactions", headers=HEADERS, json={"amount": "4.20"})

    assert response.status_code == 201
    row = created["rows"][0]
    assert row["txn_date"] == date.today().isoformat()
    assert row["type"] == "expense"
    assert row["mode"] == "personal"
    assert row["merchant"] is None
    assert row["category"] is None
    assert row["raw_extraction"] == {"needs_review": False}  # no note key when there is none


def test_create_transaction_saves_an_empty_category_as_null(
    client: TestClient, created: dict[str, Any]
) -> None:
    response = client.post(
        "/transactions",
        headers=HEADERS,
        json={"amount": 5, "merchant": "   ", "category": "", "note": ""},
    )

    assert response.status_code == 201
    row = created["rows"][0]
    assert row["category"] is None
    assert row["merchant"] is None
    assert row["raw_extraction"] == {"needs_review": False}


@pytest.mark.parametrize(
    "body",
    [
        {"amount": 5, "category": "foods"},          # not one of the nine categories
        {"amount": 5, "type": "refund"},
        {"amount": 5, "mode": "splitting"},
        {"amount": 5, "currency": "USD"},            # unknown keys are rejected, like PATCH
        {"txn_date": "2026-10-11"},                  # an amount is required
        {"amount": "twelve"},
        {"amount": 5, "note": "x" * 501},
    ],
)
def test_create_transaction_rejects_bad_input(
    client: TestClient, created: dict[str, Any], body: dict[str, Any]
) -> None:
    response = client.post("/transactions", headers=HEADERS, json=body)

    assert response.status_code == 422
    assert created["rows"] == []  # nothing reached the table


def test_create_transaction_answers_409_with_the_existing_row(
    client: TestClient, created: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The duplicate guard is the same one the receipt scan uses.

    Manual rows carry no hash under the current policy, so this pins the guard itself:
    when `dedupe_hash` does produce one and that row exists, POST answers 409, not 201.
    """
    existing = {"id": ROW_ID, "txn_date": "2026-10-11", "amount": 12.5, "merchant": "Kopitiam Ali"}
    monkeypatch.setattr("app.models.dedupe_hash", lambda *_args: "a" * 64)  # models imported it by name
    monkeypatch.setattr("app.db.find_by_dedupe_hash", lambda _dedupe, **_kw: existing)

    response = client.post(
        "/transactions",
        headers=HEADERS,
        json={"amount": 12.5, "txn_date": "2026-10-11", "merchant": "Kopitiam Ali"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "duplicate"
    assert response.json()["detail"]["transaction"] == existing
    assert created["rows"] == []  # and nothing was inserted


def test_two_identical_manual_entries_both_insert(
    client: TestClient, created: dict[str, Any]
) -> None:
    """Same amount, same day, same shop: typed twice on purpose is two transactions."""
    body = {"amount": 12.5, "txn_date": "2026-10-11", "merchant": "Kopitiam Ali"}

    first = client.post("/transactions", headers=HEADERS, json=body)
    second = client.post("/transactions", headers=HEADERS, json=body)

    assert (first.status_code, second.status_code) == (201, 201)
    assert len(created["rows"]) == 2


def test_create_transaction_needs_the_api_key(client: TestClient) -> None:
    assert client.post("/transactions", json={"amount": 5}).status_code == 401


def test_get_one_transaction(client: TestClient, stored: dict[str, Any]) -> None:
    response = client.get(f"/transactions/{ROW_ID}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == ROW_ID
    assert body["merchant"] == "Restoran Nasi Pelita"
    assert body["amount"] == 15.08
    assert body["items"] == [{"name": "Nasi Lemak Ayam", "qty": 1.0, "price": 8.5}]


def test_get_one_transaction_is_404_when_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.get_transaction", lambda _transaction_id, **_kw: None)

    assert client.get(f"/transactions/{ROW_ID}", headers=HEADERS).status_code == 404


def test_get_one_transaction_rejects_a_bad_id(client: TestClient) -> None:
    assert client.get("/transactions/not-a-uuid", headers=HEADERS).status_code == 422


def test_patch_updates_the_row_and_clears_needs_review(
    client: TestClient, stored: dict[str, Any]
) -> None:
    response = client.patch(
        f"/transactions/{ROW_ID}",
        headers=HEADERS,
        json={
            "txn_date": "2026-10-20",
            "amount": 20.8,
            "merchant": "Kopitiam Ali",
            "category": "groceries",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["txn_date"] == "2026-10-20"
    assert body["amount"] == 20.8
    assert body["merchant"] == "Kopitiam Ali"
    assert body["category"] == "groceries"
    assert body["raw_extraction"]["needs_review"] is False
    # the dedupe hash mirrors (date, amount, merchant), so it must follow the edit
    assert body["dedupe_hash"] == db.dedupe_hash(
        "receipt_scan", date(2026, 10, 20), Decimal("20.80"), "Kopitiam Ali"
    )
    assert stored["patches"][0]["raw_extraction"] == {"needs_review": False, "extraction": {}}


def test_patch_only_sends_the_fields_that_were_given(
    client: TestClient, stored: dict[str, Any]
) -> None:
    response = client.patch(f"/transactions/{ROW_ID}", headers=HEADERS, json={"amount": 9.99})

    assert response.status_code == 200
    assert stored["patches"][0]["amount"] == 9.99
    assert "txn_date" not in stored["patches"][0]
    assert "category" not in stored["patches"][0]
    assert response.json()["txn_date"] == "2026-10-11"


def test_patch_with_an_empty_body_changes_nothing(
    client: TestClient, stored: dict[str, Any]
) -> None:
    response = client.patch(f"/transactions/{ROW_ID}", headers=HEADERS, json={})

    assert response.status_code == 200
    assert stored["patches"] == []
    assert response.json()["amount"] == 15.08


def test_patch_can_clear_the_merchant(client: TestClient, stored: dict[str, Any]) -> None:
    response = client.patch(f"/transactions/{ROW_ID}", headers=HEADERS, json={"merchant": ""})

    assert response.status_code == 200
    assert stored["patches"][0]["merchant"] is None
    assert response.json()["merchant"] is None


def test_patch_rejects_a_bad_category(client: TestClient, stored: dict[str, Any]) -> None:
    response = client.patch(f"/transactions/{ROW_ID}", headers=HEADERS, json={"category": "foods"})

    assert response.status_code == 422
    assert stored["patches"] == []


def test_patch_rejects_unknown_fields(client: TestClient, stored: dict[str, Any]) -> None:
    assert client.patch(f"/transactions/{ROW_ID}", headers=HEADERS, json={"currency": "USD"}).status_code == 422


def test_patch_is_404_when_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.db.get_transaction", lambda _transaction_id, **_kw: None)

    response = client.patch(f"/transactions/{ROW_ID}", headers=HEADERS, json={"amount": 1})

    assert response.status_code == 404


def test_delete_removes_the_row_and_its_receipt(client: TestClient, stored: dict[str, Any]) -> None:
    response = client.delete(f"/transactions/{ROW_ID}", headers=HEADERS)

    assert response.status_code == 204
    assert response.content == b""
    assert stored["row"] is None
    assert stored["removed"] == [RECEIPT_PATH]


def test_delete_without_a_receipt_skips_storage(client: TestClient, stored: dict[str, Any]) -> None:
    stored["row"]["receipt_path"] = None

    assert client.delete(f"/transactions/{ROW_ID}", headers=HEADERS).status_code == 204
    assert stored["removed"] == []
    assert stored["row"] is None


def test_delete_is_404_when_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.db.get_transaction", lambda _transaction_id, **_kw: None)

    assert client.delete(f"/transactions/{ROW_ID}", headers=HEADERS).status_code == 404


def test_receipt_url_is_signed_and_short_lived(client: TestClient, stored: dict[str, Any]) -> None:
    response = client.get(f"/transactions/{ROW_ID}/receipt-url", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"url": f"https://signed.example/{RECEIPT_PATH}", "expires_in": 60}
    assert stored["signed"] == [(RECEIPT_PATH, 60)]


def test_receipt_url_is_404_without_a_receipt(client: TestClient, stored: dict[str, Any]) -> None:
    stored["row"]["receipt_path"] = None

    response = client.get(f"/transactions/{ROW_ID}/receipt-url", headers=HEADERS)

    assert response.status_code == 404
    assert stored["signed"] == []


def test_receipt_url_is_404_when_the_row_is_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.db.get_transaction", lambda _transaction_id, **_kw: None)

    assert client.get(f"/transactions/{ROW_ID}/receipt-url", headers=HEADERS).status_code == 404


def test_new_endpoints_need_the_api_key(client: TestClient) -> None:
    assert client.get(f"/transactions/{ROW_ID}").status_code == 401
    assert client.patch(f"/transactions/{ROW_ID}", json={"amount": 1}).status_code == 401
    assert client.delete(f"/transactions/{ROW_ID}").status_code == 401
    assert client.get(f"/transactions/{ROW_ID}/receipt-url").status_code == 401

