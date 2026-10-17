"""Supabase (Postgres + Storage) client and query/insert helpers.

Every helper that reads, writes or signs a transaction, a receipt, a finance setting or a commitment takes a
required, keyword-only `user_id`. There is no default and no optional form, so a call without an owner is a
TypeError, not an unfiltered query. The service-role client bypasses RLS, so this module is the only place
that talks to Supabase.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone
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
    """Every owner-scoped query goes through here: a row is seen or changed only by its owner.

    That covers transactions, finance settings, commitments and their payments. The service key bypasses
    RLS, so this filter — not a policy — is what keeps tenants apart on the API's own path.
    """
    return query.eq("user_id", str(user_id))


def owned_receipt_path(path: str | None, *, user_id: UUID) -> str | None:
    """The receipt path when this owner can reach it, otherwise None.

    `receipt_path` is only meaningful under the owner's folder. Anything else is left over from a data
    migration — a `down`/`up` cycle reassigns owners without moving the objects back — and the owner can
    neither view nor delete that object. To the API that is exactly the same as "no receipt", so callers
    can decide without a 500.
    """
    if not path:
        return None
    return path if path.startswith(f"{user_id}/") else None


def _owned_path(path: str, user_id: UUID) -> str:
    """Receipts live under the owner's folder (user_id/YYYY/MM/<uuid>.ext). Any other path is refused.

    The final guard: nothing is ever handed to the Storage client that is not the owner's, even if a
    caller skipped `owned_receipt_path`.
    """
    owned = owned_receipt_path(path, user_id=user_id)
    if owned is None:
        raise ValueError("receipt path is outside the owner's folder")
    return owned


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


# ---------------------------------------------------------------- money settings and commitments
# Every helper below is owner-scoped through `_owned` and sets `user_id` itself on a write: the owner is
# never taken from the payload. They are the only code that touches 0003's tables.


def _settings_table() -> Any:
    return get_supabase().table("user_finance_settings")


def _commitments_table() -> Any:
    return get_supabase().table("monthly_commitments")


def _payments_table() -> Any:
    return get_supabase().table("commitment_payments")


def _totals_view() -> Any:
    return get_supabase().table("transaction_totals")


def get_finance_settings(*, user_id: UUID) -> dict[str, Any] | None:
    """This owner's settings row, or None when they have never saved one (the caller applies defaults)."""
    rows = _owned(_settings_table().select("*"), user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def upsert_finance_settings(patch: dict[str, Any], *, user_id: UUID) -> dict[str, Any]:
    """Insert or update this owner's one row. The owner and `updated_at` are set here, never from `patch`."""
    if "user_id" in patch:
        raise ValueError("finance settings' owner cannot be changed")
    row = {
        **patch,
        "user_id": str(user_id),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # default_to_null=False: a column left out of `patch` keeps its default instead of becoming NULL.
    rows = _settings_table().upsert(row, on_conflict="user_id", default_to_null=False).execute().data or []
    return rows[0]


def list_commitments(*, user_id: UUID) -> list[dict[str, Any]]:
    """Every commitment this owner has, active or not, in due-date order (settings needs to show both)."""
    query = (
        _commitments_table()
        .select("*")
        .order("day_of_month")
        .order("created_at")
    )
    return _owned(query, user_id).execute().data or []


def get_commitment(commitment_id: str, *, user_id: UUID) -> dict[str, Any] | None:
    """One of this owner's commitments by id, or None (another owner's id is None, never a row)."""
    rows = (
        _owned(_commitments_table().select("*").eq("id", commitment_id), user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def insert_commitment(row: dict[str, Any], *, user_id: UUID) -> dict[str, Any]:
    """Insert one commitment for `user_id`. The owner is set here, never taken from `row`."""
    return _commitments_table().insert({**row, "user_id": str(user_id)}).execute().data[0]


def update_commitment(
    commitment_id: str, patch: dict[str, Any], *, user_id: UUID
) -> dict[str, Any] | None:
    """Apply `patch` to one of this owner's commitments, or None if it is not theirs."""
    if "user_id" in patch:
        raise ValueError("a commitment's owner cannot be changed")
    rows = (
        _owned(_commitments_table().update(patch).eq("id", commitment_id), user_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def delete_commitment(commitment_id: str, *, user_id: UUID) -> bool:
    """Delete one of this owner's commitments; True if a row was actually removed.

    The payments go with it (ON DELETE CASCADE on the composite key), so a deleted commitment cannot
    leave a paid mark behind.
    """
    rows = _owned(_commitments_table().delete().eq("id", commitment_id), user_id).execute().data
    return bool(rows)


def list_commitment_payments(month: str, *, user_id: UUID) -> list[dict[str, Any]]:
    """This owner's paid marks for one month (YYYY-MM), across every commitment."""
    query = _payments_table().select("*").eq("month", month)
    return _owned(query, user_id).execute().data or []


def mark_commitment_paid(commitment_id: str, month: str, *, user_id: UUID) -> dict[str, Any]:
    """Mark one commitment paid for one month, idempotently: a repeat returns the same mark.

    The composite foreign key refuses a commitment that belongs to someone else, so this cannot be used
    to write across tenants even if the ownership check above it were ever skipped. default_to_null=False
    keeps `paid_at` at its default on the conflicting update rather than nulling it.
    """
    row = {"commitment_id": commitment_id, "month": month, "user_id": str(user_id)}
    rows = (
        _payments_table()
        .upsert(row, on_conflict="commitment_id,month", default_to_null=False)
        .execute()
        .data
        or []
    )
    return rows[0]


def unmark_commitment_paid(commitment_id: str, month: str, *, user_id: UUID) -> bool:
    """Remove the paid mark for one commitment and month; True if one was there."""
    rows = (
        _owned(_payments_table().delete().eq("commitment_id", commitment_id).eq("month", month), user_id)
        .execute()
        .data
    )
    return bool(rows)


def transaction_totals(*, user_id: UUID) -> list[dict[str, Any]]:
    """This owner's per-month, per-mode totals from `public.transaction_totals`.

    The view aggregates inside Postgres on purpose: an all-time sum built by fetching every transaction
    would be capped by PostgREST's max-rows and would come up short without saying so.
    """
    query = _totals_view().select("mode,month,total_income,total_expense,row_count")
    return _owned(query, user_id).execute().data or []


def upload_receipt(path: str, content: bytes, content_type: str, *, user_id: UUID) -> str:
    """Upload a receipt image under the owner's folder; returns its path."""
    path = _owned_path(path, user_id)  # ownership first: never hand the client a foreign path
    _bucket().upload(path, content, {"content-type": content_type, "upsert": "false"})
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
    """Short-lived signed URL for one of the owner's private receipt objects.

    Supabase answers with a path relative to its Storage API (`/object/sign/...`), which no client can
    open on its own, so it is joined to the project's Storage base here and the caller gets an absolute
    URL it can fetch or `open` directly.
    """
    path = _owned_path(path, user_id)  # ownership first: never hand the client a foreign path
    signed = _bucket().create_signed_url(path, expires_in)
    url = signed.get("signedURL") or signed.get("signedUrl")
    if not url:
        raise RuntimeError("Supabase returned no signed URL for this receipt")
    return absolute_receipt_url(url)


def absolute_receipt_url(signed: str) -> str:
    """Join Supabase's relative signed path to the Storage base. An absolute URL is left alone."""
    if signed.startswith(("http://", "https://")):
        return signed
    if not signed.startswith("/"):
        signed = "/" + signed
    return f"{get_settings().supabase_url.rstrip('/')}/storage/v1{signed}"
