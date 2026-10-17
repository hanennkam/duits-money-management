"""The real owner filters in app/db.py, run against an in-memory query builder.

The isolation tests replace the db helpers with fakes, so they cannot see a missing `.eq("user_id", ...)` inside
db.py. This module runs the real helpers. The fake client applies the filters it is given (eq, in, gte, lt), so a
query that forgets the owner returns the other user's rows and the test fails.
"""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID

import pytest

from app import db
from conftest import SETTINGS

pytestmark = pytest.mark.isolation

USER_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ROW_A = "a1111111-1111-4111-8111-111111111111"
ROW_B = "b1111111-1111-4111-8111-111111111111"
HASH = "c" * 64


class Result:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class Table:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.ids = itertools.count(1000)


class Query:
    """Records each builder call and applies the filters when executed."""

    def __init__(self, table: Table) -> None:
        self.table = table
        self.op = "select"
        self.payload: Any = None
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_to: int | None = None

    def select(self, _columns: str) -> "Query":
        self.op = "select"
        return self

    def insert(self, row: dict[str, Any]) -> "Query":
        self.op, self.payload = "insert", row
        return self

    def update(self, patch: dict[str, Any]) -> "Query":
        self.op, self.payload = "update", patch
        return self

    def delete(self) -> "Query":
        self.op = "delete"
        return self

    def eq(self, column: str, value: Any) -> "Query":
        self.filters.append((column, "eq", value))
        return self

    def in_(self, column: str, values: list[Any]) -> "Query":
        self.filters.append((column, "in", values))
        return self

    def gte(self, column: str, value: Any) -> "Query":
        self.filters.append((column, "gte", value))
        return self

    def lt(self, column: str, value: Any) -> "Query":
        self.filters.append((column, "lt", value))
        return self

    def order(self, _column: str, desc: bool = False) -> "Query":
        return self

    def limit(self, count: int) -> "Query":
        self.limit_to = count
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for column, op, value in self.filters:
            cell = row.get(column)
            if op == "eq" and cell != value:
                return False
            if op == "in" and cell not in value:
                return False
            if op == "gte" and not (cell >= value):
                return False
            if op == "lt" and not (cell < value):
                return False
        return True

    def execute(self) -> Result:
        matched = [row for row in self.table.rows if self._matches(row)]
        if self.op == "insert":
            row = {"id": f"new-{next(self.table.ids)}", **self.payload}
            self.table.rows.append(row)
            return Result([dict(row)])
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
            return Result([dict(row) for row in matched])
        if self.op == "delete":
            for row in matched:
                self.table.rows.remove(row)
            return Result([dict(row) for row in matched])
        if self.limit_to is not None:
            matched = matched[: self.limit_to]
        return Result([dict(row) for row in matched])


class Bucket:
    def __init__(self) -> None:
        self.objects: list[str] = []
        self.signed: list[str] = []

    def upload(self, path: str, _content: bytes, _options: dict[str, str]) -> None:
        self.objects.append(path)

    def remove(self, paths: list[str]) -> None:
        self.objects = [obj for obj in self.objects if obj not in paths]

    def create_signed_url(self, path: str, _expires_in: int) -> dict[str, str]:
        self.signed.append(path)
        return {"signedURL": f"https://signed.example/{path}"}


class FakeClient:
    def __init__(self) -> None:
        self.table_store = Table()
        self.bucket = Bucket()

    def table(self, _name: str) -> Query:
        return Query(self.table_store)

    class _Storage:
        def __init__(self, bucket: Bucket) -> None:
            self.bucket = bucket

        def from_(self, _name: str) -> Bucket:
            return self.bucket

    @property
    def storage(self) -> "_Storage":
        return FakeClient._Storage(self.bucket)


def row(row_id: str, owner: UUID, *, amount: str = "12.50", dedupe: str | None = None,
        image_hash: str | None = None, path: str | None = None) -> dict[str, Any]:
    return {
        "id": row_id,
        "user_id": str(owner),
        "txn_date": "2026-10-11",
        "amount": float(Decimal(amount)),
        "type": "expense",
        "mode": "personal",
        "category": "food",
        "merchant": "Kedai Contoh",
        "receipt_path": path or f"{owner}/2026/10/{row_id}.jpg",
        "dedupe_hash": dedupe,
        "image_hash": image_hash,
        "created_at": "2026-10-11T12:00:00+00:00",
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClient]:
    fake = FakeClient()
    monkeypatch.setattr("app.db.get_supabase", lambda: fake)
    monkeypatch.setattr("app.db.get_settings", lambda: SETTINGS)
    yield fake


@pytest.fixture
def seeded(client: FakeClient) -> FakeClient:
    client.table_store.rows.extend([
        row(ROW_A, USER_A, amount="100.00", dedupe=HASH, image_hash=HASH),
        row(ROW_B, USER_B, amount="7.00", dedupe=HASH, image_hash=HASH),
    ])
    return client


# ---------------------------------------------------------------- reads only see the owner

def test_find_helpers_only_see_the_callers_rows(seeded: FakeClient) -> None:
    assert db.find_by_dedupe_hash(HASH, user_id=USER_B)["id"] == ROW_B
    assert db.find_by_dedupe_hashes([HASH], user_id=USER_B)["id"] == ROW_B
    assert db.find_by_image_hash(HASH, user_id=USER_B)["id"] == ROW_B
    assert db.find_by_dedupe_hash("d" * 64, user_id=USER_B) is None


def test_a_dedupe_match_that_belongs_to_another_owner_is_never_returned(seeded: FakeClient) -> None:
    seeded.table_store.rows = [row(ROW_A, USER_A, dedupe=HASH)]
    assert db.find_by_dedupe_hash(HASH, user_id=USER_B) is None
    assert db.find_by_dedupe_hashes([HASH], user_id=USER_B) is None
    assert db.find_by_image_hash(HASH, user_id=USER_B) is None


def test_get_transaction_is_none_for_another_owners_id(seeded: FakeClient) -> None:
    assert db.get_transaction(ROW_A, user_id=USER_B) is None
    assert db.get_transaction(ROW_A, user_id=USER_A)["id"] == ROW_A


def test_list_and_summary_only_count_the_callers_rows(seeded: FakeClient) -> None:
    start, end = date(2026, 10, 1), date(2026, 11, 1)
    assert [r["id"] for r in db.list_transactions(start, end, "personal", user_id=USER_B)] == [ROW_B]
    totals = db.summarize(start, end, "personal", user_id=USER_B)
    assert totals["total_expense"] == Decimal("7.00")


# ---------------------------------------------------------------- writes only touch the owner's rows

def test_update_of_another_owners_row_changes_nothing(seeded: FakeClient) -> None:
    assert db.update_transaction(ROW_A, {"amount": 1}, user_id=USER_B) is None
    assert next(r for r in seeded.table_store.rows if r["id"] == ROW_A)["amount"] == 100.0


def test_delete_of_another_owners_row_removes_nothing(seeded: FakeClient) -> None:
    assert db.delete_transaction(ROW_A, user_id=USER_B) is False
    assert {r["id"] for r in seeded.table_store.rows} == {ROW_A, ROW_B}


def test_update_cannot_move_a_row_to_another_owner(seeded: FakeClient) -> None:
    with pytest.raises(ValueError, match="owner cannot be changed"):
        db.update_transaction(ROW_B, {"user_id": str(USER_A)}, user_id=USER_B)
    assert next(r for r in seeded.table_store.rows if r["id"] == ROW_B)["user_id"] == str(USER_B)


def test_insert_stamps_the_owner_passed_in_not_the_one_in_the_row(client: FakeClient) -> None:
    stored = db.insert_transaction({"amount": 5, "user_id": str(USER_A)}, user_id=USER_B)
    assert stored["user_id"] == str(USER_B)


def test_delete_removes_only_the_callers_row(seeded: FakeClient) -> None:
    assert db.delete_transaction(ROW_B, user_id=USER_B) is True
    assert [r["id"] for r in seeded.table_store.rows] == [ROW_A]


# ---------------------------------------------------------------- storage stays inside the owner's folder

def test_upload_outside_the_owners_folder_is_refused(client: FakeClient) -> None:
    with pytest.raises(ValueError, match="outside the owner"):
        db.upload_receipt(f"{USER_A}/2026/10/x.jpg", b"bytes", "image/jpeg", user_id=USER_B)
    assert client.bucket.objects == []


def test_a_legacy_unscoped_path_is_refused_for_signing_and_deleting(client: FakeClient) -> None:
    with pytest.raises(ValueError, match="outside the owner"):
        db.create_receipt_url("2026/10/x.jpg", 60, user_id=USER_A)
    with pytest.raises(ValueError, match="outside the owner"):
        db.delete_receipt("2026/10/x.jpg", user_id=USER_A)
    assert client.bucket.signed == []


def test_the_owner_can_upload_sign_and_delete_within_their_folder(client: FakeClient) -> None:
    path = f"{USER_A}/2026/10/abc.jpg"
    db.upload_receipt(path, b"bytes", "image/jpeg", user_id=USER_A)
    assert db.create_receipt_url(path, 60, user_id=USER_A).endswith(path)
    db.delete_receipt(path, user_id=USER_A)
    assert client.bucket.objects == []
