"""Pydantic v2 models: Claude's extraction output, API payloads, DB rows.

Money is a `Decimal` internally (exact addition for the summary) and a plain JSON
number on the wire via `Amount`, which is what Apple Shortcuts expects.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.db import dedupe_hash
from app.finance import DAY_MAX, DAY_MIN, valid_day_of_month, valid_month

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
# What the image turned out to be. Absent means the model could not tell.
DocumentKind = Literal["receipt", "bank_screenshot"]
Mode = Literal["personal", "business"]
# receipt_scan: a photo of a paper receipt (the image is kept).
# bank_screenshot: a Maybank MAE/M2U, DuitNow, TNG or GrabPay screen — the fields are kept, the image is not.
Source = Literal["receipt_scan", "bank_screenshot", "text", "manual"]

# Decimal internally (exact money maths), JSON number on the wire (Shortcuts friendly).
Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


# An account, card or phone number: 8 or more digits, optionally grouped with spaces or hyphens. Only a
# whole value is considered, and an ISO date or timestamp is never one of them.
_ACCOUNT_LIKE = re.compile(r"(?:\d[ -]?){7,}\d")
_DATE_OR_TIME = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?")


def _mask_account_numbers(value: Any) -> Any:
    """Replace account-shaped values with a marker, keeping the shape of the data intact."""
    if isinstance(value, str):
        text = value.strip()
        if _ACCOUNT_LIKE.fullmatch(text) and not _DATE_OR_TIME.fullmatch(text):
            return "[redacted]"
        return value
    if isinstance(value, dict):
        return {key: _mask_account_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_account_numbers(item) for item in value]
    return value


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
    # A bank or e-wallet screenshot is a different kind of document: no line items, but a reference
    # number and a time that a paper receipt does not have.
    document_kind: DocumentKind | None = None
    reference: str | None = None
    txn_time: str | None = None   # "HH:MM", 24-hour, as printed on the screen

    @field_validator("merchant", "category", "type", "document_kind", "reference", "txn_time",
                     mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Claude sometimes answers "" instead of null."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("txn_time", mode="after")
    @classmethod
    def _time_is_hh_mm(cls, value: str | None) -> str | None:
        """Keep only a real HH:MM; anything else is treated as unread, never guessed at."""
        if value is None:
            return None
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            return None
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    @field_validator("currency", mode="before")
    @classmethod
    def _normalise_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper() or None
        return value

    @property
    def needs_review(self) -> bool:
        """Confidence signal: a field we could not read, or an unclear direction on a bank screen.

        On a paper receipt the amount only ever goes one way, so a missing `type` means nothing. On a
        screenshot it decides expense versus income, so an unread one is a flag for a human.
        """
        if self.amount is None or self.merchant is None:
            return True
        return self.document_kind == "bank_screenshot" and self.type is None

    def raw(self) -> dict[str, Any]:
        """Everything we keep for debugging, including the confidence flag.

        For a bank or e-wallet screenshot this dict is *all* that is kept — the image is never stored —
        so anything account-shaped is masked before it goes in. The pattern only matches a value that is
        entirely digits (optionally in groups), so a date, a time or a shop name is never touched.
        """
        extraction = self.model_dump(mode="json")
        if self.document_kind == "bank_screenshot":
            extraction = _mask_account_numbers(extraction)
        return {"needs_review": self.needs_review, "extraction": extraction}

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
            "dedupe_hash": dedupe_hash(
                source,
                self.txn_date,
                self.amount,
                self.merchant,
                reference=self.reference,
                txn_time=self.txn_time,
            ),
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
    # The Pay flow's link to one commitment (0004). A plain save sends nothing, so it stays None. Data,
    # not a foreign key on purpose: deleting a commitment must keep every expense; the route answers 404
    # for an id that is not a commitment of the caller.
    commitment_id: UUID | None = None

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
            # The Pay flow's link (0004): a UUID on the wire, null for every other save.
            "commitment_id": str(self.commitment_id) if self.commitment_id is not None else None,
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
    # The Pay flow's link (0004): set when the row was saved from a commitment's Pay button, None otherwise.
    commitment_id: UUID | None = None


class Summary(BaseModel):
    """Body of GET /summary."""

    month: str
    mode: Mode
    total_expense: Amount
    total_income: Amount
    by_category: dict[str, Amount] = Field(default_factory=dict)


# ---------------------------------------------------------------- money settings and commitments
# `user_id` appears on the response models only. Every payload model uses extra="forbid", so a request
# that carries a `user_id` is a 422 rather than a write against someone else's rows.


def _commitment_name(value: Any) -> Any:
    """Trim a name, and refuse one that is only spaces (the column's own check refuses it too)."""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
    return value


def _positive_amount(value: Decimal) -> Decimal:
    """A commitment is money due, so zero and negative are not commitments."""
    if value <= 0:
        raise ValueError("amount must be greater than zero")
    return value


def _day_in_range(value: int) -> int:
    """1-31, display-only: nothing is scheduled, so 31 in a 30-day month is simply "the 31st"."""
    if not valid_day_of_month(value):
        raise ValueError(f"day_of_month must be between {DAY_MIN} and {DAY_MAX}")
    return value


class FinanceSettings(BaseModel):
    """One row in `public.user_finance_settings`, as returned. The balance is never stored here."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None  # response only
    opening_balance: Amount = Decimal("0")
    monthly_budget: Amount = Decimal("0")
    currency: str = "MYR"
    updated_at: datetime | None = None


class FinanceSettingsUpdate(BaseModel):
    """Body of PUT /finance/settings: the two figures a human sets.

    An omitted field is left alone. An explicit `null` is treated as omitted rather than as "clear",
    because both columns are NOT NULL and 0 is how a budget is cleared.
    """

    model_config = ConfigDict(extra="forbid")

    opening_balance: Amount | None = None
    monthly_budget: Amount | None = None

    @field_validator("monthly_budget")
    @classmethod
    def _budget_is_not_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("monthly_budget cannot be negative; use 0 for no budget")
        return value

    def changes(self) -> dict[str, Any]:
        """Only the fields actually sent, JSON-ready."""
        patch = self.model_dump(mode="json", include=self.model_fields_set)
        return {key: value for key, value in patch.items() if value is not None}


class Commitment(BaseModel):
    """A row in `public.monthly_commitments`, plus `paid` for the month that was asked for.

    `paid` is derived from `public.commitment_payments`; it is not a column. It is `null` only when the
    request named no month to answer for (a PATCH without `?month=`), never as a stand-in for "no".
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    user_id: str | None = None  # response only
    created_at: datetime | None = None
    name: str
    amount: Amount
    day_of_month: int
    active: bool = True
    paid: bool | None = None


class CommitmentCreate(BaseModel):
    """Body of POST /commitments."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    amount: Amount
    day_of_month: int
    active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def _name_is_not_blank(cls, value: Any) -> Any:
        return _commitment_name(value)

    @field_validator("amount")
    @classmethod
    def _amount_is_positive(cls, value: Decimal) -> Decimal:
        return _positive_amount(value)

    @field_validator("day_of_month")
    @classmethod
    def _day_is_in_range(cls, value: int) -> int:
        return _day_in_range(value)

    def to_row(self) -> dict[str, Any]:
        """Shape this as a `public.monthly_commitments` row. The owner is set by db.py, never here."""
        return {
            "name": self.name,
            "amount": float(self.amount),
            "day_of_month": self.day_of_month,
            "active": self.active,
        }


class CommitmentUpdate(BaseModel):
    """Body of PATCH /commitments/{id}. An omitted field is left alone; nothing can be cleared."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    amount: Amount | None = None
    day_of_month: int | None = None
    active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _name_is_not_blank(cls, value: Any) -> Any:
        return value if value is None else _commitment_name(value)

    @field_validator("amount")
    @classmethod
    def _amount_is_positive(cls, value: Decimal | None) -> Decimal | None:
        return value if value is None else _positive_amount(value)

    @field_validator("day_of_month")
    @classmethod
    def _day_is_in_range(cls, value: int | None) -> int | None:
        return value if value is None else _day_in_range(value)

    def changes(self) -> dict[str, Any]:
        """Only the fields actually sent, JSON-ready. `active: false` is a value, not an omission."""
        patch = self.model_dump(mode="json", include=self.model_fields_set)
        return {key: value for key, value in patch.items() if value is not None}


class CommitmentPayment(BaseModel):
    """Body of POST /commitments/{id}/paid: the month being marked paid, as YYYY-MM."""

    model_config = ConfigDict(extra="forbid")

    month: str

    @field_validator("month")
    @classmethod
    def _month_is_real(cls, value: str) -> str:
        if not valid_month(value):
            raise ValueError("month must be YYYY-MM with a real month number")
        return value


class FinanceSummary(BaseModel):
    """Body of GET /finance/summary.

    `total_income`, `total_expense` and `current_balance` are all-time and span **every** mode: the balance
    is one real-world number. `remaining_budget` is scoped to the requested `mode` — the same rows the
    Home screen is showing — and is `null` when no budget is set. It leaves the month's Pay-flow expenses
    out (a paid bill stops eating the budget once it is paid); the bills still due are counted by
    `unpaid_commitments` and `safe_to_spend`, never by the bar.
    """

    month: str
    mode: Mode
    opening_balance: Amount
    monthly_budget: Amount
    total_income: Amount
    total_expense: Amount
    current_balance: Amount
    unpaid_commitments: Amount
    safe_to_spend: Amount
    remaining_budget: Amount | None = None
