"""Supabase (Postgres + Storage) client and query/insert helpers.

Every helper that reads, writes or signs a transaction or a receipt takes a required, keyword-only `user_id`.
There is no default and no optional form, so a call without an owner is a TypeError, not an unfiltered query.
The service-role client bypasses RLS, so this module is the only place that talks to Supabase.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import UUID

from supabase import Client, create_client

from app.config import get_settings

logger = logging.getLogger(__name__)


_PARENTHESISED = re.compile(r"\([^)]*\)")


def normalise_merchant(merchant: str) -> str:
    """Lowercase, drop parenthesised noise ("Eco-Shop Marketing Berhad (CPE)") and collapse spaces.

    Claude re-words the same shop differently between runs, so hashing has to look at
    the underlying name rather than the exact string it returned.
    """
    return " ".join(_PARENTHESISED.sub(" ", merchant).split()).lower()


# A bank screenshot without a reference number is deduped on (amount, merchant, date, time) "within ten
# minutes": the time is folded into ten-minute windows, and the lookup probes the window either side, so a
# pair six minutes apart is still caught when it straddles a boundary.
DEDUPE_WINDOW_MINUTES = 10

# The sources that dedupe at all. A text note is typed on purpose and a manual row is deliberate, so the
# same amount on the same day is not the same transaction for either of them.
DEDUPED_SOURCES = ("receipt_scan", "bank_screenshot")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _time_bucket(txn_time: str | None) -> int | None:
    """Minutes of the day, floor-divided into the dedupe window. None when there is no usable time."""
    if not txn_time:
        return None
    hours, _, minutes = txn_time.partition(":")
    if not (hours.isdigit() and minutes.isdigit()):
        return None
    return (int(hours) * 60 + int(minutes)) // DEDUPE_WINDOW_MINUTES


def dedupe_hash(
    source: str,
    txn_date: date,
    amount: Decimal,
    merchant: str | None,
    *,
    reference: str | None = None,
    txn_time: str | None = None,
) -> str | None:
    """Value for `transactions.dedupe_hash`, or None when this row must not be deduped.

    - A bank or e-wallet screenshot with a reference number is keyed on that reference alone: it is the
      bank's own identifier for the transaction, so amount, merchant and time are irrelevant.
    - Otherwise a scan (paper or screenshot) is keyed on date, amount and normalised merchant, and a
      screenshot adds its ten-minute window when the screen printed a time.
    - Everything else returns None. NULL never collides under the unique index in schema.sql, so those
      rows always insert.
    """
    if source not in DEDUPED_SOURCES:
        return None
    # A reference is an identifier, not prose: "MB 123" and "mb123" are the same reference, and
    # any space in it is only how the app spaced the digits.
    reference_key = "".join((reference or "").split()).upper()
    if source == "bank_screenshot" and reference_key:
        return _hash(f"ref|{reference_key}")
    merchant_key = normalise_merchant(merchant or "")
    if not merchant_key:
        return None
    key = f"{txn_date.isoformat()}|{amount:.2f}|{merchant_key}"
    bucket = _time_bucket(txn_time) if source == "bank_screenshot" else None
    return _hash(f"{key}|{bucket}" if bucket is not None else key)


def dedupe_hashes(
    source: str,
    txn_date: date,
    amount: Decimal,
    merchant: str | None,
    *,
    reference: str | None = None,
    txn_time: str | None = None,
) -> list[str]:
    """Every hash a duplicate lookup should probe, the row's own key first.

    A row stores `dedupe_hash(...)`; a lookup also probes the neighbouring time windows, which is what
    makes "within ten minutes" work across a window boundary.
    """
    primary = dedupe_hash(source, txn_date, amount, merchant, reference=reference, txn_time=txn_time)
    if primary is None:
        return []
    bucket = _time_bucket(txn_time) if source == "bank_screenshot" else None
    if bucket is None or reference or bucket == 0:
        return [primary]
    merchant_key = normalise_merchant(merchant or "")
    base = f"{txn_date.isoformat()}|{amount:.2f}|{merchant_key}"
    return [primary] + [_hash(f"{base}|{other}") for other in (bucket - 1, bucket + 1)]


def month_bounds(month: str) -> tuple[date, date]:
    """Return the first day of `month` (YYYY-MM) and the first day of the following month."""
    year_part, _, month_part = month.partition("-")
    if len(year_part) != 4 or len(month_part) != 2 or not (year_part + month_part).isdigit():
        raise ValueError(f"Invalid month {month!r}; expected YYYY-MM.")
    year, month_number = int(year_part), int(month_part)
    if not 1 <= month_number <= 12:
        raise ValueError(f"Invalid month {month!r}; expected YYYY-MM.")
    return date(year, month_number, 1), date(year + month_number // 12, month_number % 12 + 1, 1)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Service-role client. Bypasses RLS: only this module may use it, and every call is owner-scoped."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _table() -> Any:
    return get_supabase().table("transactions")


def _bucket() -> Any:
    return get_supabase().storage.from_(get_settings().receipts_bucket)


def _owned(query: Any, user_id: UUID) -> Any:
    """Every transactions query goes through here: a row is seen or changed only by its owner."""
    return query.eq("user_id", str(user_id))


def _owned_path(path: str, user_id: UUID) -> str:
    """Receipts live under the owner's folder (user_id/YYYY/MM/<uuid>.ext). Any other path is refused."""
    if not path.startswith(f"{user_id}/"):
        raise ValueError("receipt path is outside the owner's folder")
    return path


def find_by_dedupe_hashes(hashes: list[str], *, user_id: UUID) -> dict[str, Any] | None:
    """Any of this owner's rows carrying one of these hashes (the neighbouring time windows)."""
    if not hashes:
        return None
    rows = _owned(_table().select("*").in_("dedupe_hash", hashes), user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def find_by_dedupe_hash(dedupe: str, *, user_id: UUID) -> dict[str, Any] | None:
    """This owner's row with this dedupe hash, if any."""
    rows = _owned(_table().select("*").eq("dedupe_hash", dedupe), user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def find_by_image_hash(image_hash: str, *, user_id: UUID) -> dict[str, Any] | None:
    """This owner's row for this exact uploaded file, if any."""
    rows = _owned(_table().select("*").eq("image_hash", image_hash), user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def get_transaction(transaction_id: str, *, user_id: UUID) -> dict[str, Any] | None:
    """One of this owner's rows by id, or None (another owner's id is None, never a row)."""
    rows = _owned(_table().select("*").eq("id", transaction_id), user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def update_transaction(transaction_id: str, patch: dict[str, Any], *, user_id: UUID) -> dict[str, Any] | None:
    """Apply `patch` to one of this owner's rows and return it as stored, or None if it is not theirs."""
    if "user_id" in patch:
        raise ValueError("a transaction's owner cannot be changed")
    rows = _owned(_table().update(patch).eq("id", transaction_id), user_id).execute().data or []
    return rows[0] if rows else None


def delete_transaction(transaction_id: str, *, user_id: UUID) -> bool:
    """Delete one of this owner's rows; True if a row was actually removed."""
    rows = _owned(_table().delete().eq("id", transaction_id), user_id).execute().data
    return bool(rows)


def insert_transaction(row: dict[str, Any], *, user_id: UUID) -> dict[str, Any]:
    """Insert one row for `user_id`, and return it as stored. The owner is set here, never taken from `row`."""
    return _table().insert({**row, "user_id": str(user_id)}).execute().data[0]


def list_transactions(start: date, end: date, mode: str, *, user_id: UUID) -> list[dict[str, Any]]:
    """This owner's transactions with `start <= txn_date < end` for `mode`, newest first."""
    query = (
        _table()
        .select("*")
        .gte("txn_date", start.isoformat())
        .lt("txn_date", end.isoformat())
        .eq("mode", mode)
        .order("txn_date", desc=True)
        .order("created_at", desc=True)
    )
    return _owned(query, user_id).execute().data or []


def summarize(start: date, end: date, mode: str, *, user_id: UUID) -> dict[str, Any]:
    """Totals for this owner's rows in [start, end).

    ponytail: adds up one month of rows in Python; move to a Postgres view/RPC if a
    month ever holds more than a few thousand rows.
    """
    total_expense = Decimal("0")
    total_income = Decimal("0")
    by_category: dict[str, Decimal] = {}
    for row in list_transactions(start, end, mode, user_id=user_id):
        amount = Decimal(str(row["amount"]))
        if row["type"] == "income":
            total_income += amount
        else:
            total_expense += amount
        category = row.get("category") or "other"
        by_category[category] = by_category.get(category, Decimal("0")) + amount
    return {"total_expense": total_expense, "total_income": total_income, "by_category": by_category}


def upload_receipt(path: str, content: bytes, content_type: str, *, user_id: UUID) -> str:
    """Upload a receipt image under the owner's folder; returns its path."""
    _bucket().upload(
        _owned_path(path, user_id), content, {"content-type": content_type, "upsert": "false"}
    )
    return path


def delete_receipt(path: str, *, user_id: UUID) -> None:
    """Best-effort cleanup so a failed insert does not leave an orphan in Storage.

    The ownership check sits outside the try: a foreign path is a bug and must surface, not be swallowed.
    """
    path = _owned_path(path, user_id)
    try:
        _bucket().remove([path])
    except Exception:  # cleanup must never mask the original error
        logger.warning("Could not delete orphaned receipt %s", path, exc_info=True)


def create_receipt_url(path: str, expires_in: int, *, user_id: UUID) -> str:
    """Short-lived signed URL for one of the owner's private receipt objects."""
    signed = _bucket().create_signed_url(_owned_path(path, user_id), expires_in)
    url = signed.get("signedURL") or signed.get("signedUrl")
    if not url:
        raise RuntimeError("Supabase returned no signed URL for this receipt")
    return url
