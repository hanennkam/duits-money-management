"""`dedupe_hash` policy, and the routes that depend on it.

Only receipt scans with a readable merchant carry a dedupe hash; text notes and
merchant-less receipts store NULL, so they can never be reported as duplicates.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import extractor
from app.db import dedupe_hash, month_bounds
from app.models import Extraction
from conftest import HEADERS


def test_receipt_with_merchant_hashes_the_same_whatever_the_formatting() -> None:
    assert dedupe_hash("receipt_scan", date(2026, 3, 4), Decimal("12.50"), "Kopitiam Ali") == dedupe_hash(
        "receipt_scan", date(2026, 3, 4), Decimal("12.5"), "  kopitiam ALI "
    )


def test_a_changed_field_changes_the_hash() -> None:
    base = dedupe_hash("receipt_scan", date(2026, 3, 4), Decimal("12.50"), "Kopitiam Ali")
    assert dedupe_hash("receipt_scan", date(2026, 3, 5), Decimal("12.50"), "Kopitiam Ali") != base
    assert dedupe_hash("receipt_scan", date(2026, 3, 4), Decimal("12.51"), "Kopitiam Ali") != base
    assert dedupe_hash("receipt_scan", date(2026, 3, 4), Decimal("12.50"), "Other Shop") != base


def test_merchant_normalisation_ignores_case_parens_and_spacing() -> None:
    """"ECO-SHOP MARKETING BERHAD" and "Eco-Shop Marketing Berhad (CPE)" are the same shop."""
    assert dedupe_hash(
        "receipt_scan", date(2026, 3, 4), Decimal("12.50"), "ECO-SHOP MARKETING BERHAD"
    ) == dedupe_hash(
        "receipt_scan", date(2026, 3, 4), Decimal("12.50"), "Eco-Shop   Marketing Berhad (CPE)"
    )


@pytest.mark.parametrize(
    ("source", "merchant"),
    [
        ("text", "Kopitiam Ali"),
        ("text", None),
        ("receipt_scan", None),
        ("receipt_scan", "  "),
        ("manual", "Kopitiam Ali"),
    ],
)
def test_nothing_to_dedupe_on_returns_none(source: str, merchant: str | None) -> None:
    assert dedupe_hash(source, date(2026, 3, 4), Decimal("12.50"), merchant) is None


def test_month_bounds_wrap_into_the_next_year() -> None:
    assert month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))
    assert month_bounds("2026-03") == (date(2026, 3, 1), date(2026, 4, 1))


def test_two_text_entries_same_amount_same_day_both_insert(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"makan tengah hari 12 ringgit" and "makan malam 12 ringgit" are two transactions."""
    rows: list[dict[str, Any]] = []
    lookups: list[str] = []

    def fake_find(dedupe: str) -> dict[str, Any] | None:
        lookups.append(dedupe)
        return next((row for row in rows if row["dedupe_hash"] == dedupe), None)

    def fake_insert(row: dict[str, Any]) -> dict[str, Any]:
        stored = {**row, "id": str(len(rows)), "created_at": "2026-03-04T12:00:00+00:00"}
        rows.append(stored)
        return stored

    monkeypatch.setattr("app.db.find_by_dedupe_hash", fake_find)
    monkeypatch.setattr("app.db.insert_transaction", fake_insert)
    monkeypatch.setattr(
        "app.extractor.extract_from_text",
        lambda _text: Extraction.model_validate({"txn_date": "2026-03-04", "amount": 12, "merchant": None}),
    )

    first = client.post("/transactions/text", headers=HEADERS, json={"text": "makan tengah hari 12 ringgit"})
    second = client.post("/transactions/text", headers=HEADERS, json={"text": "makan malam 12 ringgit"})

    assert (first.status_code, second.status_code) == (201, 201)
    assert [row["dedupe_hash"] for row in rows] == [None, None]
    assert lookups == []  # no dedupe lookup at all for text entries


def test_duplicate_receipt_still_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt with a merchant is still deduped, even from a different photo."""
    existing = {"id": "existing-id", "txn_date": "2026-03-04", "amount": 12.5}
    deleted: list[str] = []
    monkeypatch.setattr("app.db.find_by_image_hash", lambda _image_hash: None)
    monkeypatch.setattr("app.db.upload_receipt", lambda path, _content, _content_type: path)
    monkeypatch.setattr("app.db.delete_receipt", lambda path: deleted.append(path))
    monkeypatch.setattr("app.db.find_by_dedupe_hash", lambda dedupe: existing if dedupe else None)
    monkeypatch.setattr(
        "app.extractor.extract_from_image",
        lambda _image, _media_type: Extraction.model_validate(
            {"txn_date": "2026-03-04", "amount": 12.5, "merchant": "Kopitiam Ali"}
        ),
    )

    response = client.post(
        "/transactions/scan",
        headers=HEADERS,
        files={"file": ("receipt.jpg", b"jpeg-bytes", "image/jpeg")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["transaction"] == existing
    assert len(deleted) == 1  # the rejected duplicate left no receipt in Storage


def test_scan_does_not_upload_when_extraction_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extraction runs first, so an unreadable receipt never reaches Storage."""
    uploads: list[str] = []

    def unreadable(*_args: object) -> Extraction:
        raise extractor.ExtractionError(extractor.IMAGE_UNREADABLE)

    monkeypatch.setattr("app.db.find_by_image_hash", lambda _image_hash: None)
    monkeypatch.setattr("app.db.upload_receipt", lambda path, _c, _t: uploads.append(path) or path)
    monkeypatch.setattr("app.extractor.extract_from_image", unreadable)

    response = client.post(
        "/transactions/scan",
        headers=HEADERS,
        files={"file": ("receipt.jpg", b"faded-jpeg-bytes", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "That image could not be read. Try a clearer one, or type the transaction in."
    assert uploads == []



def test_same_image_twice_returns_409_without_calling_claude(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: two runs of Claude on one photo gave two different merchants, so two rows."""
    rows: list[dict[str, Any]] = []
    claude_calls: list[bytes] = []
    uploads: list[str] = []

    def fake_find_image(image_hash: str) -> dict[str, Any] | None:
        return next((row for row in rows if row["image_hash"] == image_hash), None)

    def fake_insert(row: dict[str, Any]) -> dict[str, Any]:
        stored = {**row, "id": str(len(rows)), "created_at": "2026-03-04T12:00:00+00:00"}
        rows.append(stored)
        return stored

    def fake_extract(image: bytes, _media_type: str) -> Extraction:
        claude_calls.append(image)
        # Claude is not deterministic: a second run re-words the shop.
        return Extraction.model_validate(
            {"txn_date": "2026-03-04", "amount": 12.5, "merchant": f"Eco-Shop Marketing (run {len(claude_calls)})"}
        )

    monkeypatch.setattr("app.db.find_by_image_hash", fake_find_image)
    monkeypatch.setattr("app.db.find_by_dedupe_hash", lambda _dedupe: None)
    monkeypatch.setattr("app.db.insert_transaction", fake_insert)
    monkeypatch.setattr(
        "app.db.upload_receipt",
        lambda path, _content, _content_type: uploads.append(path) or path,
    )
    monkeypatch.setattr("app.extractor.extract_from_image", fake_extract)

    receipt = b"\xff\xd8\xff\xe0same-photo-bytes"
    files = {"file": ("receipt.jpg", receipt, "image/jpeg")}
    first = client.post("/transactions/scan", headers=HEADERS, files=files)
    second = client.post("/transactions/scan", headers=HEADERS, files=files)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "duplicate"
    assert second.json()["detail"]["transaction"]["id"] == first.json()["id"]
    assert len(claude_calls) == 1  # the second scan never reached Claude...
    assert len(uploads) == 1  # ...nor Storage
    assert rows[0]["image_hash"] == hashlib.sha256(receipt).hexdigest()
