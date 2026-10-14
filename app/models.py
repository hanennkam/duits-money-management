"""Pydantic v2 models: Claude's extraction output, API payloads, DB rows.

Money is a `Decimal` internally (exact addition for the summary) and a plain JSON
number on the wire via `Amount`, which is what Apple Shortcuts expects.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.db import dedupe_hash

Category = Literal[
    "food",
    "transport",
    "groceries",
    "bills",
    "shopping",
    "health",
    "entertainment",
    "business",
    "other",
]
CATEGORIES: tuple[str, ...] = get_args(Category)

TxnType = Literal["expense", "income"]
Mode = Literal["personal", "business"]
Source = Literal["receipt_scan", "text", "manual"]

# Decimal internally (exact money maths), JSON number on the wire (Shortcuts friendly).
Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class LineItem(BaseModel):
    """One line on a receipt. Anything Claude cannot read stays null."""

    model_config = ConfigDict(extra="ignore")

    name: str
    qty: float | None = None
    price: Amount | None = None


class Extraction(BaseModel):
    """The structured transaction Claude must return for every request."""

    model_config = ConfigDict(extra="ignore")

    txn_date: date
    amount: Amount | None = None
    currency: str | None = None
    merchant: str | None = None
    category: Category | None = None
    type: TxnType | None = None
    items: list[LineItem] | None = None

    @field_validator("merchant", "category", "type", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Claude sometimes answers "" instead of null."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def _normalise_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper() or None
        return value

    @property
    def needs_review(self) -> bool:
        """Basic confidence signal: we could not read the amount or the merchant."""
        return self.amount is None or self.merchant is None

    def raw(self) -> dict[str, Any]:
        """Everything we keep for debugging, including the confidence flag."""
        return {"needs_review": self.needs_review, "extraction": self.model_dump(mode="json")}

    def to_row(
        self,
        *,
        mode: Mode,
        source: Source,
        receipt_path: str | None = None,
        image_hash: str | None = None,
    ) -> dict[str, Any]:
        """Shape this extraction as a `public.transactions` row, JSON-ready for insert.

        Every value must be JSON-native: the client JSON-encodes this dict, so a
        `Decimal` left in it (in items, say) blows up with a TypeError.
        """
        # extractor.extract_* rejects amount-less extractions before we get here.
        assert self.amount is not None
        items = [item.model_dump(mode="json", exclude_none=True) for item in self.items or []]
        return {
            "txn_date": self.txn_date.isoformat(),
            "amount": float(self.amount),
            "currency": self.currency or "MYR",
            "merchant": self.merchant,
            "category": self.category,
            "type": self.type or "expense",
            "mode": mode,
            "items": items or None,
            "receipt_path": receipt_path,
            "image_hash": image_hash,
            "source": source,
            "dedupe_hash": dedupe_hash(source, self.txn_date, self.amount, self.merchant),
            "raw_extraction": self.raw(),
        }


class TextTransactionRequest(BaseModel):
    """Body of POST /transactions/text."""

    text: str = Field(min_length=1, max_length=2000, description="e.g. 'makan tengah hari 12 ringgit'")
    mode: Mode = "personal"


class TransactionUpdate(BaseModel):
    """Body of PATCH /transactions/{id}. Only the fields a human may correct."""

    model_config = ConfigDict(extra="forbid")

    txn_date: date | None = None
    amount: Amount | None = None
    merchant: str | None = None
    category: Category | None = None
    type: TxnType | None = None
    mode: Mode | None = None

    @field_validator("merchant", mode="before")
    @classmethod
    def _blank_merchant_is_none(cls, value: Any) -> Any:
        """An emptied field clears the merchant instead of storing ""."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def changes(self) -> dict[str, Any]:
        """Only the fields actually sent, JSON-ready. An explicit null clears a field."""
        patch = self.model_dump(mode="json", include=self.model_fields_set)
        if self.amount is None:
            patch.pop("amount", None)  # an amount can be corrected but never cleared
        return patch


class TransactionCreate(BaseModel):
    """Body of POST /transactions: one row typed in by hand, no Claude involved.

    Same field rules as `TransactionUpdate` (unknown keys rejected, blank text is absent),
    plus the fields a fresh row needs. `note` is free text the API keeps in
    `raw_extraction.note`; there is no column for it.
    """

    model_config = ConfigDict(extra="forbid")

    amount: Amount
    txn_date: date = Field(default_factory=date.today)
    merchant: str | None = None
    category: Category | None = None
    type: TxnType = "expense"
    mode: Mode = "personal"
    note: str | None = Field(default=None, max_length=500)

    @field_validator("merchant", "category", "note", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """An empty field means absent: an empty category is stored as null, not ""."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def raw(self) -> dict[str, Any]:
        """`raw_extraction` for a typed row: never flagged for review, note kept as sent."""
        raw: dict[str, Any] = {"needs_review": False}
        if self.note:
            raw["note"] = self.note
        return raw

    def to_row(self, *, source: Source = "manual") -> dict[str, Any]:
        """Shape this as a `public.transactions` row, JSON-ready for insert.

        `dedupe_hash` comes from the shared policy, which returns None for a manual row:
        a typed entry is deliberate, so the same amount on the same day is not a duplicate.
        """
        return {
            "txn_date": self.txn_date.isoformat(),
            "amount": float(self.amount),
            "currency": "MYR",
            "merchant": self.merchant,
            "category": self.category,
            "type": self.type,
            "mode": self.mode,
            "items": None,
            "receipt_path": None,
            "image_hash": None,
            "source": source,
            "dedupe_hash": dedupe_hash(source, self.txn_date, self.amount, self.merchant),
            "raw_extraction": self.raw(),
        }


class ReceiptUrl(BaseModel):
    """Body of GET /transactions/{id}/receipt-url."""

    url: str
    expires_in: int = 60


class Transaction(BaseModel):
    """A row in `public.transactions`, used as the API response."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    created_at: datetime | None = None
    txn_date: date
    amount: Amount
    currency: str = "MYR"
    merchant: str | None = None
    category: str | None = None
    type: TxnType = "expense"
    mode: Mode = "personal"
    items: list[LineItem] | None = None
    receipt_path: str | None = None
    image_hash: str | None = None  # sha256 of the uploaded file: dedupes the same photo twice
    source: Source | None = None
    dedupe_hash: str | None = None  # null for text entries and merchant-less receipts: not deduped
    # `raw_extraction.needs_review` is the confidence flag for this row.
    raw_extraction: dict[str, Any] | None = None


class Summary(BaseModel):
    """Body of GET /summary."""

    month: str
    mode: Mode
    total_expense: Amount
    total_income: Amount
    by_category: dict[str, Amount] = Field(default_factory=dict)
