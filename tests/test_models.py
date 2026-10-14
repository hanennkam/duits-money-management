"""Extraction and Transaction models: validation, defaults, JSON shape."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Extraction, Transaction

GOOD_JSON = """
{
  "txn_date": "2026-03-04",
  "amount": 12.5,
  "currency": "myr",
  "merchant": "Kopitiam Ali",
  "category": "food",
  "type": "expense",
  "items": [{"name": "Nasi lemak", "qty": 1, "price": 5.5}]
}
"""


def test_valid_extraction_parses_and_keeps_money_exact() -> None:
    extraction = Extraction.model_validate_json(GOOD_JSON)
    assert extraction.amount == Decimal("12.50")
    assert extraction.currency == "MYR"
    assert extraction.items is not None and extraction.items[0].name == "Nasi lemak"
    assert extraction.needs_review is False
    # Shortcuts wants a number, not a string.
    assert '"amount":12.5' in extraction.model_dump_json()


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(json.loads(GOOD_JSON) | {"category": "foods"})


def test_unreadable_fields_become_null_and_defaults_fill_in() -> None:
    extraction = Extraction.model_validate(
        {"txn_date": "2026-03-04", "amount": 5, "merchant": " ", "type": ""}
    )
    assert extraction.merchant is None
    assert extraction.needs_review is True

    row = extraction.to_row(mode="personal", source="text")
    assert row["currency"] == "MYR"
    assert row["type"] == "expense"
    assert row["amount"] == 5.0
    assert row["raw_extraction"]["needs_review"] is True
    assert row["dedupe_hash"] is None  # text rows are never deduped


def test_row_with_line_items_is_json_serialisable() -> None:
    """Regression: a Decimal price inside items broke the Supabase insert with a TypeError."""
    row = Extraction.model_validate_json(GOOD_JSON).to_row(
        mode="personal", source="receipt_scan", receipt_path="2026/03/x.jpg"
    )

    assert row["items"] == [{"name": "Nasi lemak", "qty": 1, "price": 5.5}]
    json.dumps(row)  # the insert payload must survive JSON encoding


def test_transaction_response_renders_money_as_a_number() -> None:
    txn = Transaction.model_validate(
        {"txn_date": "2026-03-04", "amount": "12.50", "mode": "personal", "type": "expense"}
    )
    payload = json.loads(txn.model_dump_json())
    assert isinstance(payload["amount"], float)
    assert payload["amount"] == 12.5
