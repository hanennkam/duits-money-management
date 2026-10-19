"""The single-transaction endpoints: create, get, patch, delete, signed receipt URL.

Supabase is mocked with an in-memory row; nothing here touches the network.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Settings, get_settings
from app.main import app
from conftest import HEADERS, SETTINGS, TEST_USER

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


def test_a_pay_save_carries_its_commitments_link(
    client: TestClient, created: dict[str, Any], money: dict[str, Any]
) -> None:
    """The Pay flow's save posts `commitment_id` too, and the row stores it as it was sent."""
    money["commitments"] = [commitment_row()]

    response = client.post(
        "/transactions",
        headers=HEADERS,
        json={
            "amount": 300,
            "txn_date": "2026-10-11",
            "merchant": "Sewa rumah",
            "category": "bills",
            "commitment_id": COMMITMENT_ID,
        },
    )

    assert response.status_code == 201
    assert created["rows"][0]["commitment_id"] == COMMITMENT_ID
    assert created["lookups"] == []  # the link does not turn a Pay row into a deduped one


def test_a_pay_save_refuses_a_foreign_commitment(
    client: TestClient, created: dict[str, Any], money: dict[str, Any]
) -> None:
    """The link must name a commitment of the caller: another owner's id and an unknown id both 404.

    The column is deliberately not a foreign key (deleting a commitment must keep every expense), so
    this check is the app's job — and it answers like every other cross-owner read: 404, no write.
    """
    money["commitments"] = [commitment_row(OTHER_COMMITMENT_ID, owner=OTHER_USER)]

    for commitment_id in (OTHER_COMMITMENT_ID, "44444444-4444-4444-8444-444444444444"):
        response = client.post(
            "/transactions",
            headers=HEADERS,
            json={"amount": 300, "category": "bills", "commitment_id": commitment_id},
        )
        assert response.status_code == 404, commitment_id
        assert response.json()["detail"] == "No commitment with that id."
    assert created["rows"] == []  # nothing reached the table, with either id


def test_a_plain_save_sends_no_commitment_key_at_all(
    client: TestClient, created: dict[str, Any]
) -> None:
    """An ordinary manual save carries no link: the column stays null on every non-Pay row."""
    response = client.post("/transactions", headers=HEADERS, json={"amount": 12.5})

    assert response.status_code == 201
    assert created["rows"][0]["commitment_id"] is None


# ---------- the Pay flow's own guard: one bill, one expense, one month ----------

# The Pay flow's two writes are the expense and the paid mark. The mark is idempotent (the same
# month twice leaves one mark), but the expense in front of it was not: a Pay whose mark failed,
# retried, charged the same bill twice. The three scenarios below are that failure, measured.


@pytest.fixture
def pay_rows(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The Pay flow's rows, with the one-bill-one-expense lookup answered from them.

    The lookup is mocked the way the table would answer it: this owner's Pay expense for this
    commitment in this month. A plain save never asks, so the counter shows that too.
    """
    state: dict[str, Any] = {"rows": [], "lookups": []}

    def find_pay_expense(
        commitment_id: str, month: str, *, user_id: Any
    ) -> dict[str, Any] | None:
        state["lookups"].append((commitment_id, month, str(user_id)))
        return next(
            (
                row
                for row in state["rows"]
                if row.get("commitment_id") == commitment_id
                and row["user_id"] == str(user_id)
                and str(row["txn_date"])[:7] == month
            ),
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

    monkeypatch.setattr("app.db.find_pay_expense", find_pay_expense)
    monkeypatch.setattr("app.db.insert_transaction", insert)
    yield state


def test_a_pay_that_finds_the_bill_already_charged_answers_409(
    client: TestClient, pay_rows: dict[str, Any], money: dict[str, Any]
) -> None:
    """Scenario A: the expense is saved, the mark fails, and the user pays again.

    The first Pay's expense is in the table. The second Pay is the same bill in the same month, so
    the answer is 409 carrying the row that is already there — the UI then carries on to the mark
    instead of showing an error, and the bill is paid once and charged once.
    """
    money["commitments"] = [commitment_row()]
    body = {
        "amount": 300,
        "txn_date": "2026-10-11",
        "merchant": "Sewa rumah",
        "category": "bills",
        "commitment_id": COMMITMENT_ID,
    }

    first = client.post("/transactions", headers=HEADERS, json=body)
    assert first.status_code == 201
    assert len(pay_rows["rows"]) == 1

    second = client.post("/transactions", headers=HEADERS, json=body)
    assert second.status_code == 409
    assert len(pay_rows["rows"]) == 1, "the bill is charged once, not twice"
    detail = second.json()["detail"]
    assert detail["error"] == "duplicate"
    assert detail["transaction"]["id"] == pay_rows["rows"][0]["id"], "the row that is already there"


def test_paying_the_same_bill_twice_costs_once(
    client: TestClient, pay_rows: dict[str, Any], money: dict[str, Any]
) -> None:
    """Scenario B: the retry that follows a failed mark leaves one expense and one paid mark.

    The whole point of the guard: the user paid, the mark failed, and they paid again. One expense
    (so the balance drops once) and one mark (so the bill stops counting as due).
    """
    money["commitments"] = [commitment_row()]
    money["settings"] = {"user_id": TEST_USER, "opening_balance": 1000.0, "monthly_budget": 0.0}
    money["totals"] = []
    body = {
        "amount": 300,
        "txn_date": "2026-10-11",
        "merchant": "Sewa rumah",
        "category": "bills",
        "commitment_id": COMMITMENT_ID,
    }
    client.post("/transactions", headers=HEADERS, json=body)          # the first Pay
    # The expense half of the Pay, as the totals see it.
    money["totals"] = [totals_row(expense=300.0, commitment=300.0)]
    marked = client.post(
        f"/commitments/{COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-10"}
    )
    assert marked.status_code == 200
    assert len(money["payments"]) == 1

    retry = client.post("/transactions", headers=HEADERS, json=body)  # the second Pay
    assert retry.status_code == 409
    assert len(pay_rows["rows"]) == 1
    assert len(money["payments"]) == 1

    summary = client.get("/finance/summary?month=2026-10", headers=HEADERS).json()
    assert summary["unpaid_commitments"] == 0.0, "the bill is paid"
    assert summary["current_balance"] == 700.0, "and it was charged once"


def test_the_same_pay_payload_twice_is_refused(
    client: TestClient, pay_rows: dict[str, Any], money: dict[str, Any]
) -> None:
    """Scenario C: the identical payload sent twice, the second one is a 409 and no second row."""
    money["commitments"] = [commitment_row()]
    body = {
        "amount": 300,
        "txn_date": "2026-10-11",
        "merchant": "Sewa rumah",
        "category": "bills",
        "commitment_id": COMMITMENT_ID,
    }

    first = client.post("/transactions", headers=HEADERS, json=body)
    second = client.post("/transactions", headers=HEADERS, json=body)

    assert (first.status_code, second.status_code) == (201, 409)
    assert len(pay_rows["rows"]) == 1


def test_the_pay_guard_is_scoped_to_the_owner(
    client: TestClient, pay_rows: dict[str, Any], money: dict[str, Any]
) -> None:
    """Another owner's Pay expense must not stop this owner's Pay, and this owner's must not stop theirs.

    The service key bypasses RLS, so the owner filter is the query's own `user_id` condition and
    not a policy. This test reads the filter: the lookup is asked with the caller's id, and a row
    that belongs to somebody else is not a match.
    """
    money["commitments"] = [commitment_row()]
    body = {
        "amount": 300,
        "txn_date": "2026-10-11",
        "merchant": "Sewa rumah",
        "category": "bills",
        "commitment_id": COMMITMENT_ID,
    }
    client.post("/transactions", headers=HEADERS, json=body)

    # The lookup is asked with the caller's own id, so the rows it can see are the caller's rows.
    assert pay_rows["lookups"] == [(COMMITMENT_ID, "2026-10", TEST_USER)]

    # A row that belongs to another owner is not this caller's row, so it does not block the Pay.
    other = dict(pay_rows["rows"][0])
    other["user_id"] = OTHER_USER
    pay_rows["rows"] = [other]
    response = client.post("/transactions", headers=HEADERS, json=body)
    assert response.status_code == 201
    assert len(pay_rows["rows"]) == 2


def test_a_deleted_pay_expense_lets_the_bill_be_paid_again(
    client: TestClient, pay_rows: dict[str, Any], money: dict[str, Any]
) -> None:
    """The guard looks at the rows that exist, so deleting the expense frees the bill again.

    A mistaken Pay is undone by deleting its expense. The bill must then be payable once more —
    a guard that outlived the row it was about would lock the user out of their own bill.
    """
    money["commitments"] = [commitment_row()]
    body = {
        "amount": 300,
        "txn_date": "2026-10-11",
        "merchant": "Sewa rumah",
        "category": "bills",
        "commitment_id": COMMITMENT_ID,
    }
    first = client.post("/transactions", headers=HEADERS, json=body)
    assert first.status_code == 201

    pay_rows["rows"] = []                      # the expense was deleted

    again = client.post("/transactions", headers=HEADERS, json=body)
    assert again.status_code == 201
    assert len(pay_rows["rows"]) == 1


def test_a_plain_save_never_asks_the_pay_lookup(
    client: TestClient, pay_rows: dict[str, Any]
) -> None:
    """Only a Pay is guarded: an ordinary manual save is deliberate and must never be refused."""
    response = client.post("/transactions", headers=HEADERS, json={"amount": 12.5})

    assert response.status_code == 201
    assert pay_rows["lookups"] == [], "a plain save does not look for a Pay expense"


def test_a_pay_in_another_month_is_a_different_bill(
    client: TestClient, pay_rows: dict[str, Any], money: dict[str, Any]
) -> None:
    """The month is the transaction's own, so a bill paid in two months is two charges.

    The guard answers for one commitment in one month. Paying last month's bill and this month's
    bill are two expenses, and neither is a duplicate of the other.
    """
    money["commitments"] = [commitment_row()]
    october = {
        "amount": 300,
        "txn_date": "2026-10-11",
        "merchant": "Sewa rumah",
        "category": "bills",
        "commitment_id": COMMITMENT_ID,
    }
    november = {**october, "txn_date": "2026-11-11"}

    first = client.post("/transactions", headers=HEADERS, json=october)
    second = client.post("/transactions", headers=HEADERS, json=november)

    assert (first.status_code, second.status_code) == (201, 201)
    assert len(pay_rows["rows"]) == 2


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


def test_a_receipt_path_outside_the_owners_folder_is_404_not_500(
    client: TestClient, stored: dict[str, Any]
) -> None:
    """A migration leftover, not a photo the owner can reach. It answers like "no receipt", not a crash.

    A `down`/`up` cycle reassigns owners without moving the objects back, which is exactly what the
    cutover runbook's rollback path does. Before this, such a row returned 500 and was undeletable.
    """
    stored["row"]["receipt_path"] = "someone-else/2026/10/abc123.jpg"

    response = client.get(f"/transactions/{ROW_ID}/receipt-url", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["detail"] == "This transaction has no receipt image."
    assert stored["signed"] == [], "nothing outside the owner's folder may ever be signed"


def test_a_row_with_an_unreachable_receipt_can_still_be_deleted(
    client: TestClient, stored: dict[str, Any]
) -> None:
    """Deleting the row must work; the foreign object is not ours to remove and is left alone."""
    stored["row"]["receipt_path"] = "someone-else/2026/10/abc123.jpg"

    response = client.delete(f"/transactions/{ROW_ID}", headers=HEADERS)

    assert response.status_code == 204
    assert stored["row"] is None, "the row itself still goes"
    assert stored["removed"] == [], "a receipt outside the owner's folder is never deleted"


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



# ---------------------------------------------------------------- money settings, commitments, budget
# The three 0003 tables and the totals view, faked. Every helper takes its owner by keyword, like the
# real ones, so a route that forgot to pass the caller shows up as a wrong or missing owner here.

OTHER_USER = "0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f"
LEGACY_USER = "9c3e4a1b-2d5f-4a6e-8b7c-0d1e2f3a4b5c"
COMMITMENT_ID = "22222222-2222-4222-8222-222222222222"
OTHER_COMMITMENT_ID = "33333333-3333-4333-8333-333333333333"

MONEY_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("get", "/finance/settings", None),
    ("put", "/finance/settings", {"opening_balance": 1000}),
    ("get", "/finance/summary?month=2026-10", None),
    ("get", "/commitments?month=2026-10", None),
    ("post", "/commitments", {"name": "Sewa rumah", "amount": 1500, "day_of_month": 1}),
    ("patch", f"/commitments/{COMMITMENT_ID}", {"amount": 1600}),
    ("delete", f"/commitments/{COMMITMENT_ID}", None),
    ("post", f"/commitments/{COMMITMENT_ID}/paid", {"month": "2026-10"}),
    ("delete", f"/commitments/{COMMITMENT_ID}/paid?month=2026-10", None),
]


def commitment_row(
    row_id: str = COMMITMENT_ID, *, owner: str = TEST_USER, amount: float = 300.0, active: bool = True
) -> dict[str, Any]:
    return {
        "id": row_id,
        "user_id": owner,
        "name": "Sewa rumah",
        "amount": amount,
        "day_of_month": 1,
        "active": active,
        "created_at": "2026-10-01T00:00:00+00:00",
    }


def totals_row(
    *, owner: str = TEST_USER, month: str = "2026-10", mode: str = "personal",
    income: float | None = None, expense: float | None = None, commitment: float | None = None,
) -> dict[str, Any]:
    return {
        "user_id": owner,
        "mode": mode,
        "month": f"{month}-01",
        "total_income": income,
        "total_expense": expense,
        "commitment_expense": commitment,
        "row_count": 1,
    }


@pytest.fixture
def money(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """In-memory stand-ins for the settings, commitment, payment and totals helpers."""
    state: dict[str, Any] = {
        "settings": None,
        "commitments": [],
        "payments": [],
        "totals": [],
        "calls": [],
    }

    def get_settings(*, user_id: Any) -> dict[str, Any] | None:
        state["calls"].append(("get_settings", str(user_id)))
        return state["settings"] if str(user_id) == TEST_USER else None

    def upsert_settings(patch: dict[str, Any], *, user_id: Any) -> dict[str, Any]:
        state["calls"].append(("upsert_settings", str(user_id), dict(patch)))
        state["settings"] = {
            **(state["settings"] or {}),
            "user_id": str(user_id),
            "currency": "MYR",
            "updated_at": "2026-10-17T09:00:00+00:00",
            **patch,
        }
        return state["settings"]

    def list_commitments(*, user_id: Any) -> list[dict[str, Any]]:
        state["calls"].append(("list_commitments", str(user_id)))
        return [dict(row) for row in state["commitments"] if row["user_id"] == str(user_id)]

    def get_commitment(commitment_id: str, *, user_id: Any) -> dict[str, Any] | None:
        state["calls"].append(("get_commitment", str(user_id), commitment_id))
        return next(
            (
                dict(row)
                for row in state["commitments"]
                if row["id"] == commitment_id and row["user_id"] == str(user_id)
            ),
            None,
        )

    def insert_commitment(row: dict[str, Any], *, user_id: Any) -> dict[str, Any]:
        stored = {
            **row,
            "id": "44444444-4444-4444-8444-444444444444",
            "user_id": str(user_id),
            "created_at": "2026-10-17T09:00:00+00:00",
        }
        state["commitments"].append(stored)
        return dict(stored)

    def update_commitment(commitment_id: str, patch: dict[str, Any], *, user_id: Any) -> dict[str, Any] | None:
        row = get_commitment(commitment_id, user_id=user_id)
        if row is None:
            return None
        row.update(patch)
        next(existing for existing in state["commitments"] if existing["id"] == commitment_id).update(patch)
        return row

    def delete_commitment(commitment_id: str, *, user_id: Any) -> bool:
        if get_commitment(commitment_id, user_id=user_id) is None:
            return False
        state["commitments"] = [row for row in state["commitments"] if row["id"] != commitment_id]
        state["payments"] = [row for row in state["payments"] if row["commitment_id"] != commitment_id]
        return True

    def list_commitment_payments(month: str, *, user_id: Any) -> list[dict[str, Any]]:
        state["calls"].append(("list_commitment_payments", str(user_id), month))
        return [
            dict(row)
            for row in state["payments"]
            if row["month"] == month and row["user_id"] == str(user_id)
        ]

    def mark_commitment_paid(commitment_id: str, month: str, *, user_id: Any) -> dict[str, Any]:
        state["calls"].append(("mark_commitment_paid", str(user_id), commitment_id, month))
        existing = next(
            (
                row
                for row in state["payments"]
                if row["commitment_id"] == commitment_id and row["month"] == month
            ),
            None,
        )
        if existing is not None:
            return dict(existing)
        row = {
            "id": f"pay-{commitment_id}-{month}",
            "user_id": str(user_id),
            "commitment_id": commitment_id,
            "month": month,
            "paid_at": "2026-10-17T09:00:00+00:00",
        }
        state["payments"].append(row)
        return dict(row)

    def unmark_commitment_paid(commitment_id: str, month: str, *, user_id: Any) -> bool:
        state["calls"].append(("unmark_commitment_paid", str(user_id), commitment_id, month))
        before = len(state["payments"])
        state["payments"] = [
            row
            for row in state["payments"]
            if not (
                row["commitment_id"] == commitment_id
                and row["month"] == month
                and row["user_id"] == str(user_id)
            )
        ]
        return len(state["payments"]) != before

    def transaction_totals(*, user_id: Any) -> list[dict[str, Any]]:
        state["calls"].append(("transaction_totals", str(user_id)))
        return [dict(row) for row in state["totals"] if row["user_id"] == str(user_id)]

    for name, helper in [
        ("get_finance_settings", get_settings),
        ("upsert_finance_settings", upsert_settings),
        ("list_commitments", list_commitments),
        ("get_commitment", get_commitment),
        ("insert_commitment", insert_commitment),
        ("update_commitment", update_commitment),
        ("delete_commitment", delete_commitment),
        ("list_commitment_payments", list_commitment_payments),
        ("mark_commitment_paid", mark_commitment_paid),
        ("unmark_commitment_paid", unmark_commitment_paid),
        ("transaction_totals", transaction_totals),
    ]:
        monkeypatch.setattr(f"app.db.{name}", helper)
    yield state


def test_the_money_endpoints_need_a_token(client: TestClient, money: dict[str, Any]) -> None:
    for method, path, body in MONEY_ROUTES:
        response = getattr(client, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 401, path


def test_the_money_endpoints_are_never_cached(client: TestClient, money: dict[str, Any]) -> None:
    for method, path, body in MONEY_ROUTES:
        money["commitments"] = [commitment_row()]  # a fresh row per route: DELETE takes it away
        response = getattr(client, method)(path, headers=HEADERS, **({"json": body} if body else {}))
        assert response.status_code < 400, path
        assert response.headers["Cache-Control"] == "no-store", path


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("put", "/finance/settings", {"opening_balance": 1, "user_id": OTHER_USER}),
        ("post", "/commitments", {"name": "x", "amount": 1, "day_of_month": 1, "user_id": OTHER_USER}),
        ("patch", f"/commitments/{COMMITMENT_ID}", {"amount": 1, "user_id": OTHER_USER}),
        ("post", f"/commitments/{COMMITMENT_ID}/paid", {"month": "2026-10", "user_id": OTHER_USER}),
    ],
)
def test_a_user_id_in_the_body_is_rejected(
    client: TestClient, money: dict[str, Any], method: str, path: str, body: dict[str, Any]
) -> None:
    """The owner comes from the token. A body that names one is a 422, not a write."""
    assert getattr(client, method)(path, headers=HEADERS, json=body).status_code == 422


def test_another_owners_commitment_is_a_404_everywhere(
    client: TestClient, money: dict[str, Any]
) -> None:
    money["commitments"] = [commitment_row(OTHER_COMMITMENT_ID, owner=OTHER_USER)]

    assert client.patch(
        f"/commitments/{OTHER_COMMITMENT_ID}", headers=HEADERS, json={"amount": 1}
    ).status_code == 404
    assert client.delete(f"/commitments/{OTHER_COMMITMENT_ID}", headers=HEADERS).status_code == 404
    assert client.post(
        f"/commitments/{OTHER_COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-10"}
    ).status_code == 404
    assert client.delete(
        f"/commitments/{OTHER_COMMITMENT_ID}/paid?month=2026-10", headers=HEADERS
    ).status_code == 404
    assert money["payments"] == []
    assert len(money["commitments"]) == 1


def test_the_summary_is_derived_from_the_callers_rows(client: TestClient, money: dict[str, Any]) -> None:
    """One balance over every mode and every month; one budget spend over the asked mode and month."""
    money["settings"] = {
        "user_id": TEST_USER,
        "opening_balance": 1000.0,
        "monthly_budget": 2000.0,
        "currency": "MYR",
    }
    money["totals"] = [
        totals_row(month="2026-10", income=1200.0, expense=200.0),
        totals_row(month="2026-09", expense=50.0),
        totals_row(month="2026-10", mode="business", expense=999.0),
    ]
    money["commitments"] = [commitment_row(amount=300.0)]

    personal = client.get("/finance/summary?month=2026-10&mode=personal", headers=HEADERS)

    assert personal.status_code == 200
    assert personal.json() == {
        "month": "2026-10",
        "mode": "personal",
        "opening_balance": 1000.0,
        "monthly_budget": 2000.0,
        "total_income": 1200.0,
        "total_expense": 1249.0,  # every mode, every month
        "current_balance": 951.0,
        "unpaid_commitments": 300.0,
        "safe_to_spend": 651.0,
        "remaining_budget": 1800.0,  # 2000 - 200 spent; the unpaid bill is safe-to-spend's job
    }

    business = client.get("/finance/summary?month=2026-10&mode=business", headers=HEADERS)

    assert business.json()["mode"] == "business"
    assert business.json()["remaining_budget"] == 1001.0  # 2000 - 999 in that mode
    assert business.json()["current_balance"] == 951.0  # the balance does not move with the mode


def test_a_pay_expense_never_eats_the_budget_but_the_unpaid_bill_never_feeds_it(
    client: TestClient, money: dict[str, Any]
) -> None:
    """The Pay flow's expense is in the totals and out of the bar, by its commitment link.

    Before paying: 200 spent, no Pay expense — the bar reads 1800 left even though a 300 bill is
    still due. After paying: the totals gain the 300 expense AND its commitment_expense label, so the
    subtraction `month_expense - month_commitment_expense` does not move, and neither does the bar —
    while the bill leaves `unpaid`, so safe-to-spend holds.
    """
    money["settings"] = {
        "user_id": TEST_USER,
        "opening_balance": 1000.0,
        "monthly_budget": 2000.0,
        "currency": "MYR",
    }
    money["totals"] = [totals_row(expense=200.0)]
    money["commitments"] = [commitment_row(amount=300.0)]

    before = client.get("/finance/summary?month=2026-10", headers=HEADERS).json()

    marked = client.post(
        f"/commitments/{COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-10"}
    )
    money["totals"] = [totals_row(expense=500.0, commitment=300.0)]  # POST /transactions, then the mark

    after = client.get("/finance/summary?month=2026-10", headers=HEADERS).json()

    assert marked.status_code == 200
    assert before["remaining_budget"] == after["remaining_budget"] == 1800.0
    assert before["unpaid_commitments"] == 300.0 and after["unpaid_commitments"] == 0.0
    # 1000 opening - 200 other spend = 800 balance, minus 300 due; after: 1000 - 500 = 500 balance, no
    # bill due. The two halves move by the same 300, so safe-to-spend holds at 500 both times.
    assert before["safe_to_spend"] == after["safe_to_spend"] == 500.0


def test_the_summary_reads_no_settings_row_as_zero_and_no_budget(
    client: TestClient, money: dict[str, Any]
) -> None:
    money["totals"] = [totals_row(expense=25.0)]

    body = client.get("/finance/summary?month=2026-10", headers=HEADERS).json()

    assert body["opening_balance"] == 0.0
    assert body["monthly_budget"] == 0.0
    assert body["current_balance"] == -25.0
    assert body["remaining_budget"] is None  # no budget, so nothing to report
    assert body["mode"] == "personal"  # the default


def test_marking_a_commitment_paid_never_subtracts_the_money_twice(
    client: TestClient, money: dict[str, Any]
) -> None:
    """Paying is two writes in the UI: the expense, and the paid mark. Together, safe-to-spend holds."""
    money["settings"] = {"user_id": TEST_USER, "opening_balance": 1000.0, "monthly_budget": 0.0}
    money["totals"] = []  # nothing spent yet
    money["commitments"] = [commitment_row(amount=300.0)]

    before = client.get("/finance/summary?month=2026-10", headers=HEADERS).json()
    marked = client.post(
        f"/commitments/{COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-10"}
    )
    money["totals"] = [totals_row(expense=300.0, commitment=300.0)]  # POST /transactions, the other half
    after = client.get("/finance/summary?month=2026-10", headers=HEADERS).json()

    assert marked.status_code == 200 and marked.json()["paid"] is True
    assert before["current_balance"] == 1000.0
    assert before["unpaid_commitments"] == 300.0 and before["safe_to_spend"] == 700.0
    # The expense is now in the totals and the commitment is no longer due: the two cancel, so the
    # amount safe to spend does not move. Deducting the commitment as well would take the money twice.
    assert after["current_balance"] == 700.0
    assert after["unpaid_commitments"] == 0.0 and after["safe_to_spend"] == 700.0


def test_marking_paid_twice_leaves_one_mark_and_is_scoped_to_the_month(
    client: TestClient, money: dict[str, Any]
) -> None:
    money["commitments"] = [commitment_row()]

    first = client.post(f"/commitments/{COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-10"})
    second = client.post(f"/commitments/{COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-10"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert len(money["payments"]) == 1  # a retried tap cannot subtract the money twice
    assert first.json()["paid"] is True

    october = client.get("/commitments?month=2026-10", headers=HEADERS).json()
    november = client.get("/commitments?month=2026-11", headers=HEADERS).json()
    assert october[0]["paid"] is True
    assert november[0]["paid"] is False

    undo = client.delete(f"/commitments/{COMMITMENT_ID}/paid?month=2026-10", headers=HEADERS)
    assert undo.status_code == 204
    assert client.get("/commitments?month=2026-10", headers=HEADERS).json()[0]["paid"] is False


def test_the_commitment_list_shows_inactive_ones_too(client: TestClient, money: dict[str, Any]) -> None:
    money["commitments"] = [
        commitment_row("a" * 8 + "-1111-4111-8111-111111111111", amount=300.0),
        commitment_row("b" * 8 + "-2222-4222-8222-222222222222", amount=120.0, active=False),
    ]

    body = client.get("/commitments?month=2026-10", headers=HEADERS).json()

    assert [row["active"] for row in body] == [True, False]
    assert all(row["user_id"] == TEST_USER for row in body)


def test_a_new_commitment_is_created_for_the_caller_and_unpaid(
    client: TestClient, money: dict[str, Any]
) -> None:
    response = client.post(
        "/commitments",
        headers=HEADERS,
        json={"name": "  Sewa rumah  ", "amount": 1500, "day_of_month": 1},
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == TEST_USER
    assert response.json()["paid"] is False
    assert money["commitments"][0]["user_id"] == TEST_USER
    assert money["commitments"][0]["name"] == "Sewa rumah"  # trimmed


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Sewa", "amount": 0, "day_of_month": 1},
        {"name": "Sewa", "amount": -5, "day_of_month": 1},
        {"name": "Sewa", "amount": 5, "day_of_month": 0},
        {"name": "Sewa", "amount": 5, "day_of_month": 32},
        {"name": "   ", "amount": 5, "day_of_month": 1},
        {"name": "x" * 81, "amount": 5, "day_of_month": 1},
        {"name": "Sewa", "amount": 5, "day_of_month": 1, "paid": True},  # not a column the caller sets
    ],
)
def test_a_bad_commitment_is_rejected(
    client: TestClient, money: dict[str, Any], body: dict[str, Any]
) -> None:
    assert client.post("/commitments", headers=HEADERS, json=body).status_code == 422
    assert money["commitments"] == []


def test_patching_a_commitment_only_reports_paid_when_a_month_was_asked(
    client: TestClient, money: dict[str, Any]
) -> None:
    money["commitments"] = [commitment_row()]
    money["payments"] = [
        {
            "id": "pay-1",
            "user_id": TEST_USER,
            "commitment_id": COMMITMENT_ID,
            "month": "2026-10",
            "paid_at": "2026-10-17T09:00:00+00:00",
        }
    ]

    with_month = client.patch(
        f"/commitments/{COMMITMENT_ID}?month=2026-10", headers=HEADERS, json={"amount": 350}
    )
    without_month = client.patch(f"/commitments/{COMMITMENT_ID}", headers=HEADERS, json={"active": False})
    empty = client.patch(f"/commitments/{COMMITMENT_ID}", headers=HEADERS, json={})

    assert with_month.status_code == 200
    assert with_month.json()["amount"] == 350.0
    assert with_month.json()["paid"] is True
    assert without_month.json()["active"] is False
    assert without_month.json()["paid"] is None  # a commitment has no single paid state
    assert empty.status_code == 200


def test_settings_default_to_zero_myr_and_the_callers_id(
    client: TestClient, money: dict[str, Any]
) -> None:
    """No saved row is a normal state, not a 404: the caller sees their own id and zeroes."""
    body = client.get("/finance/settings", headers=HEADERS).json()

    assert body == {
        "user_id": TEST_USER,
        "opening_balance": 0.0,
        "monthly_budget": 0.0,
        "currency": "MYR",
        "updated_at": None,
    }


def test_settings_are_written_for_the_caller_never_for_a_body_owner(
    client: TestClient, money: dict[str, Any]
) -> None:
    set_them = client.put(
        "/finance/settings", headers=HEADERS, json={"opening_balance": -250.5, "monthly_budget": 2000}
    )

    assert set_them.status_code == 200
    assert set_them.json()["opening_balance"] == -250.5  # an overdraft is a real balance
    assert set_them.json()["monthly_budget"] == 2000.0
    assert ("upsert_settings", TEST_USER, {"opening_balance": -250.5, "monthly_budget": 2000.0}) in money["calls"]


def test_an_empty_settings_body_changes_nothing(client: TestClient, money: dict[str, Any]) -> None:
    assert client.put("/finance/settings", headers=HEADERS, json={}).status_code == 200
    assert not [call for call in money["calls"] if call[0] == "upsert_settings"]


def test_a_negative_budget_is_rejected(client: TestClient, money: dict[str, Any]) -> None:
    response = client.put("/finance/settings", headers=HEADERS, json={"monthly_budget": -1})

    assert response.status_code == 422
    assert not [call for call in money["calls"] if call[0] == "upsert_settings"]


def test_a_month_that_is_not_a_month_is_rejected(
    client: TestClient, money: dict[str, Any]
) -> None:
    money["commitments"] = [commitment_row()]

    assert client.get("/finance/summary?month=2026-13", headers=HEADERS).status_code == 400
    assert client.get("/commitments?month=2026-13", headers=HEADERS).status_code == 400
    assert client.delete(f"/commitments/{COMMITMENT_ID}/paid?month=nope", headers=HEADERS).status_code == 400
    # a month in a body goes through the model, so it is the same 422 shape as any other bad field
    assert client.post(
        f"/commitments/{COMMITMENT_ID}/paid", headers=HEADERS, json={"month": "2026-13"}
    ).status_code == 422


def test_a_commitment_id_that_is_not_a_uuid_is_rejected(
    client: TestClient, money: dict[str, Any]
) -> None:
    assert client.delete("/commitments/not-a-uuid", headers=HEADERS).status_code == 422
    assert client.post("/commitments/not-a-uuid/paid", headers=HEADERS, json={"month": "2026-10"}).status_code == 422


def test_the_legacy_api_key_reaches_the_money_endpoints_as_one_user(
    money: dict[str, Any],
) -> None:
    """`X-API-Key` is off by default; when it is on it resolves to the one configured user, no one else."""
    legacy = Settings(
        **{**SETTINGS.model_dump(), "allow_legacy_api_key": True, "legacy_user_id": UUID(LEGACY_USER)}
    )
    app.dependency_overrides[get_settings] = lambda: legacy
    try:
        with TestClient(app) as legacy_client:
            response = legacy_client.get("/finance/settings", headers={"X-API-Key": SETTINGS.api_key})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["user_id"] == LEGACY_USER
    assert ("get_settings", LEGACY_USER) in money["calls"]


def test_the_legacy_key_is_refused_when_it_is_switched_off(
    client: TestClient, money: dict[str, Any]
) -> None:
    assert client.get("/finance/settings", headers={"X-API-Key": SETTINGS.api_key}).status_code == 401
    assert money["calls"] == []
