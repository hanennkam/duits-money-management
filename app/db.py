"""Supabase (Postgres + Storage) client and query/insert helpers."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any

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


def dedupe_hash(source: str, txn_date: date, amount: Decimal, merchant: str | None) -> str | None:
    """Value for `transactions.dedupe_hash`, or None when this row must not be deduped.

    Only receipt scans with a readable merchant are deduped: text notes are typed on
    purpose, so the same amount on the same day is not the same transaction, and a
    receipt with no merchant is not evidence enough to call a duplicate. NULL never
    collides under the unique index in schema.sql, so those rows always insert.
    """
    merchant_key = normalise_merchant(merchant or "")
    if source != "receipt_scan" or not merchant_key:
        return None
    key = f"{txn_date.isoformat()}|{amount:.2f}|{merchant_key}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


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
    """Service-role client. Bypasses RLS, so it stays server-side only."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


def find_by_dedupe_hash(dedupe: str) -> dict[str, Any] | None:
    """Existing row with this dedupe hash, if any."""
    rows = (
        get_supabase().table("transactions").select("*").eq("dedupe_hash", dedupe).limit(1).execute().data
    ) or []
    return rows[0] if rows else None


def find_by_image_hash(image_hash: str) -> dict[str, Any] | None:
    """Existing row for this exact uploaded file, if any."""
    rows = (
        get_supabase()
        .table("transactions")
        .select("*")
        .eq("image_hash", image_hash)
        .limit(1)
        .execute()
        .data
    ) or []
    return rows[0] if rows else None


def get_transaction(transaction_id: str) -> dict[str, Any] | None:
    """One row by id, or None."""
    rows = (
        get_supabase().table("transactions").select("*").eq("id", transaction_id).limit(1).execute().data
    ) or []
    return rows[0] if rows else None


def update_transaction(transaction_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Apply `patch` to one row and return it as stored, or None if it is gone."""
    rows = (
        get_supabase().table("transactions").update(patch).eq("id", transaction_id).execute().data
    ) or []
    return rows[0] if rows else None


def delete_transaction(transaction_id: str) -> bool:
    """Delete one row; True if a row was actually removed."""
    rows = get_supabase().table("transactions").delete().eq("id", transaction_id).execute().data
    return bool(rows)


def insert_transaction(row: dict[str, Any]) -> dict[str, Any]:
    """Insert one row and return it as stored."""
    return get_supabase().table("transactions").insert(row).execute().data[0]


def list_transactions(start: date, end: date, mode: str) -> list[dict[str, Any]]:
    """Transactions with `start <= txn_date < end` for `mode`, newest first."""
    return (
        get_supabase()
        .table("transactions")
        .select("*")
        .gte("txn_date", start.isoformat())
        .lt("txn_date", end.isoformat())
        .eq("mode", mode)
        .order("txn_date", desc=True)
        .order("created_at", desc=True)
        .execute()
        .data
    ) or []


def summarize(start: date, end: date, mode: str) -> dict[str, Any]:
    """Totals for the period covered by [start, end).

    ponytail: adds up one month of rows in Python; move to a Postgres view/RPC if a
    month ever holds more than a few thousand rows.
    """
    total_expense = Decimal("0")
    total_income = Decimal("0")
    by_category: dict[str, Decimal] = {}
    for row in list_transactions(start, end, mode):
        amount = Decimal(str(row["amount"]))
        if row["type"] == "income":
            total_income += amount
        else:
            total_expense += amount
        category = row.get("category") or "other"
        by_category[category] = by_category.get(category, Decimal("0")) + amount
    return {"total_expense": total_expense, "total_income": total_income, "by_category": by_category}


def upload_receipt(path: str, content: bytes, content_type: str) -> str:
    """Upload a receipt image to the storage bucket; returns its path."""
    get_supabase().storage.from_(get_settings().receipts_bucket).upload(
        path, content, {"content-type": content_type, "upsert": "false"}
    )
    return path


def delete_receipt(path: str) -> None:
    """Best-effort cleanup so a failed insert does not leave an orphan in Storage."""
    try:
        get_supabase().storage.from_(get_settings().receipts_bucket).remove([path])
    except Exception:  # cleanup must never mask the original error
        logger.warning("Could not delete orphaned receipt %s", path, exc_info=True)


def create_receipt_url(path: str, expires_in: int) -> str:
    """Short-lived signed URL for a private receipt object."""
    signed = get_supabase().storage.from_(get_settings().receipts_bucket).create_signed_url(
        path, expires_in
    )
    url = signed.get("signedURL") or signed.get("signedUrl")
    if not url:
        raise RuntimeError(f"Supabase returned no signed URL for {path}")
    return url
