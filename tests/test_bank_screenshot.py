"""Bank and e-wallet screenshots: source tagging, the storage rule, and the two dedupe keys.

A screenshot of a "Payment Successful" screen is evidence of a transaction, not a document worth keeping,
so the fields are stored and the image is dropped — unlike a photo of paper, which goes to Storage.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import extractor
from app.db import dedupe_hash, dedupe_hashes
from app.models import Extraction, _mask_account_numbers
from conftest import HEADERS

SCAN = "/transactions/scan"
FILES = {"file": ("screen.png", b"png-bytes", "image/png")}


def _screenshot(**fields: Any) -> Extraction:
    """An extraction of the kind Claude returns for a bank app screenshot."""
    base: dict[str, Any] = {
        "txn_date": "2026-10-14",
        "document_kind": "bank_screenshot",
        "currency": "MYR",
    }
    return Extraction.model_validate({**base, **fields})


def _fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Rows in memory, plus a record of every Storage call, so the rule can be asserted on."""
    state: dict[str, Any] = {"rows": [], "uploads": [], "deletes": []}

    def fake_find(dedupe: str) -> dict[str, Any] | None:
        return next((row for row in state["rows"] if row.get("dedupe_hash") == dedupe), None)

    def fake_find_many(hashes: list[str]) -> dict[str, Any] | None:
        return next((row for row in state["rows"] if row.get("dedupe_hash") in hashes), None)

    def fake_insert(row: dict[str, Any]) -> dict[str, Any]:
        stored = {**row, "id": str(len(state["rows"]) + 1), "created_at": "2026-10-14T12:00:00+00:00"}
        state["rows"].append(stored)
        return stored

    monkeypatch.setattr("app.db.find_by_image_hash", lambda _hash: None)
    monkeypatch.setattr("app.db.find_by_dedupe_hash", fake_find)
    monkeypatch.setattr("app.db.find_by_dedupe_hashes", fake_find_many)
    monkeypatch.setattr("app.db.insert_transaction", fake_insert)
    monkeypatch.setattr("app.db.upload_receipt", lambda path, _c, _t: state["uploads"].append(path))
    monkeypatch.setattr("app.db.delete_receipt", lambda path: state["deletes"].append(path))
    return state


def test_money_out_is_an_expense_with_no_image_kept(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A MAE "Transfer to" screen: money left, so it is an expense - and the screenshot is not stored."""
    state = _fake_db(monkeypatch)
    monkeypatch.setattr(
        "app.extractor.extract_from_image",
        lambda _image, _media_type: _screenshot(
            merchant="Ahmad Bin Ali",
            amount=250,
            type="expense",
            category="other",
            reference="MB2026101400123",
            txn_time="14:32",
        ),
    )

    response = client.post(SCAN, headers=HEADERS, files=FILES)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "bank_screenshot"
    assert body["type"] == "expense"
    assert body["merchant"] == "Ahmad Bin Ali"
    assert body["amount"] == 250
    assert body["receipt_path"] is None, "a screenshot must never be kept in Storage"
    assert state["uploads"] == [], "no image upload for a bank screenshot"
    raw = body["raw_extraction"]
    assert raw["needs_review"] is False
    assert raw["extraction"]["document_kind"] == "bank_screenshot"
    assert raw["extraction"]["reference"] == "MB2026101400123"
    assert raw["extraction"]["txn_time"] == "14:32"


def test_money_in_is_income(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """"Received from" is money arriving, so the same screen shape becomes income."""
    _fake_db(monkeypatch)
    monkeypatch.setattr(
        "app.extractor.extract_from_image",
        lambda _image, _media_type: _screenshot(
            merchant="Siti Nurhaliza", amount=80, type="income", category="other",
            reference="DZ7712", txn_time="09:05",
        ),
    )

    response = client.post(SCAN, headers=HEADERS, files=FILES)

    assert response.status_code == 201, response.text
    assert response.json()["type"] == "income"
    assert response.json()["source"] == "bank_screenshot"
    assert response.json()["receipt_path"] is None


def test_an_unclear_direction_is_flagged_for_review() -> None:
    """No in/out signal on the screen means type stays null and a human is asked."""
    extraction = _screenshot(merchant="Someone", amount=30, type=None, category="other")
    assert extraction.needs_review is True
    assert extraction.raw()["extraction"]["type"] is None
    # A paper receipt is one-way, so a missing type there is not a flag.
    receipt = Extraction.model_validate(
        {"txn_date": "2026-10-14", "amount": 12, "merchant": "Kopitiam Ali", "document_kind": "receipt"}
    )
    assert receipt.needs_review is False


def test_an_unreadable_amount_is_never_saved_or_uploaded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude cannot read the amount, so there is nothing to record: 422, no row, no image."""
    state = _fake_db(monkeypatch)

    def unreadable(_image: bytes, _media_type: str) -> Extraction:
        raise extractor.ExtractionError(extractor.IMAGE_UNREADABLE)

    monkeypatch.setattr("app.extractor.extract_from_image", unreadable)

    response = client.post(SCAN, headers=HEADERS, files=FILES)

    assert response.status_code == 422
    assert response.json()["detail"] == extractor.IMAGE_UNREADABLE
    assert state["rows"] == []
    assert state["uploads"] == []


def test_the_same_screenshot_twice_is_a_duplicate_by_reference(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bank's reference number is the strongest signal, so it wins over amount and time."""
    _fake_db(monkeypatch)
    monkeypatch.setattr(
        "app.extractor.extract_from_image",
        lambda _image, _media_type: _screenshot(
            merchant="Ahmad Bin Ali", amount=250, type="expense", reference="MB2026101400123",
            txn_time="14:32",
        ),
    )

    first = client.post(SCAN, headers=HEADERS, files=FILES)
    second = client.post(SCAN, headers=HEADERS, files=FILES)

    assert first.status_code == 201
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["error"] == "duplicate"
    assert detail["message"] == "Already recorded."
    assert detail["transaction"]["id"] == "1"


def test_a_screenshot_without_a_reference_dedupes_within_ten_minutes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """14:29 and 14:33 are four minutes apart but land in different ten-minute windows."""
    _fake_db(monkeypatch)
    times = ["14:29", "14:33"]
    monkeypatch.setattr(
        "app.extractor.extract_from_image",
        lambda _image, _media_type: _screenshot(
            merchant="Ahmad Bin Ali", amount=250, type="expense", reference=None,
            txn_time=times.pop(0),
        ),
    )

    first = client.post(SCAN, headers=HEADERS, files=FILES)
    second = client.post(SCAN, headers=HEADERS, files=FILES)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["message"] == "Already recorded."


def test_a_paper_receipt_still_uploads_and_hashes_like_before(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule is about screenshots only: paper keeps its image and its receipt_scan source."""
    state = _fake_db(monkeypatch)
    monkeypatch.setattr(
        "app.extractor.extract_from_image",
        lambda _image, _media_type: Extraction.model_validate(
            {
                "txn_date": "2026-10-14", "amount": 12.5, "merchant": "Kopitiam Ali",
                "document_kind": "receipt", "category": "food",
            }
        ),
    )

    response = client.post(SCAN, headers=HEADERS, files=FILES)

    assert response.status_code == 201, response.text
    assert response.json()["source"] == "receipt_scan"
    assert response.json()["receipt_path"] is not None
    assert len(state["uploads"]) == 1


def test_dedupe_keys_and_the_account_mask() -> None:
    """The key policy and the redaction, at the unit level rather than through the route."""
    amount, day = Decimal("250.00"), date(2026, 10, 14)
    # A reference number alone keys the row: amount, merchant and time are irrelevant to it.
    assert dedupe_hash(
        "bank_screenshot", day, amount, "Ahmad", reference="MB 123", txn_time="14:32"
    ) == dedupe_hash("bank_screenshot", day, Decimal("999.00"), "Other", reference="mb123")
    # Without one, the row is keyed on date|amount|merchant|window and probed on both sides of it.
    keys = dedupe_hashes("bank_screenshot", day, amount, "Ahmad Bin Ali", txn_time="14:29")
    assert len(keys) == 3
    assert keys[0] == dedupe_hash("bank_screenshot", day, amount, "Ahmad Bin Ali", txn_time="14:29")
    # A receipt and a text note keep exactly the keys they had before this change.
    assert dedupe_hashes("receipt_scan", day, amount, "Kopitiam Ali") == [
        dedupe_hash("receipt_scan", day, amount, "Kopitiam Ali")
    ]
    assert dedupe_hashes("text", day, amount, "Kopitiam Ali") == []
    # A screenshot with no readable time falls back to the day-level key, like a receipt.
    assert dedupe_hashes("bank_screenshot", day, amount, "Ahmad Bin Ali") == [
        dedupe_hash("bank_screenshot", day, amount, "Ahmad Bin Ali")
    ]


def test_account_numbers_are_masked_but_dates_and_amounts_are_not() -> None:
    """raw_extraction is all we keep of a screenshot, so no account number may survive in it."""
    assert _mask_account_numbers({"a": "1234567890", "b": "1234 5678 9012 3456"}) == {
        "a": "[redacted]",
        "b": "[redacted]",
    }
    assert _mask_account_numbers("2026-10-14") == "2026-10-14"
    assert _mask_account_numbers("2026-10-14T14:32") == "2026-10-14T14:32"
    assert _mask_account_numbers("12.50") == "12.50"
    assert _mask_account_numbers("Kopitiam Ali") == "Kopitiam Ali"
    # The receipt path changes nothing about how a paper scan is stored.
    paper = Extraction.model_validate({"txn_date": "2026-10-14", "amount": 12, "merchant": "Shop 12345678"})
    assert paper.raw()["extraction"]["merchant"] == "Shop 12345678"
