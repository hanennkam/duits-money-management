"""Seed the STAGING project with FAKE data for the migration rehearsal. Never run against the live project.

Phase "before" (pre-migration schema, rows have no owner):
  - 12 paper receipts at the legacy YYYY/MM/ path, each with a fake image object and its real dedupe/image hashes
  - 3 bank screenshots (no image), 2 text entries, 2 manual rows
Phase "after" (run after 0002 up, with the owner column present):
  - user B's rows, including rows whose dedupe and image hashes equal user A's rows (duplicates across users)
  - two B receipts under B's own folder
  - a same-owner duplicate attempt, which the per-owner unique index must refuse

Guards: the env file must name the staging project ref, and the live ref is refused. Only counts are printed.

Usage:
  ./.venv/bin/python scripts/staging_seed.py --env-file .env.staging --phase before
  ./.venv/bin/python scripts/staging_seed.py --env-file .env.staging --phase after
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import dedupe_hash  # noqa: E402  (the real policy, so the seeded hashes match production's)

LIVE_PROJECT_REF = "viorpltdkpexswvofeul"
STAGING_PROJECT_REF = "tddigsmukmhkjrwiqdec"
NAMESPACE = uuid.UUID("6f1d2c3a-0000-4000-8000-000000000042")
BUCKET = "receipts"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fake_receipt(label: str, day: int, amount: str, merchant: str) -> dict:
    """A receipt row whose image is fake bytes. The hashes are the ones the app would compute."""
    payload = f"fake receipt {label}".encode()
    txn_date = date(2026, 10, day)
    return {
        "_label": label,
        "_payload": payload,
        "txn_date": txn_date.isoformat(),
        "amount": float(Decimal(amount)),
        "merchant": merchant,
        "category": "food",
        "type": "expense",
        "mode": "personal",
        "source": "receipt_scan",
        "dedupe_hash": dedupe_hash("receipt_scan", txn_date, Decimal(amount), merchant),
        "image_hash": sha(payload),
    }


def fake_screenshot(label: str, day: int, amount: str, merchant: str, reference: str) -> dict:
    txn_date = date(2026, 10, day)
    return {
        "txn_date": txn_date.isoformat(),
        "amount": float(Decimal(amount)),
        "merchant": merchant,
        "category": "other",
        "type": "expense",
        "mode": "personal",
        "source": "bank_screenshot",
        "receipt_path": None,
        "dedupe_hash": dedupe_hash(
            "bank_screenshot", txn_date, Decimal(amount), merchant, reference=reference
        ),
        "image_hash": None,
        "raw_extraction": {"needs_review": False, "extraction": {"reference": reference}},
    }


def before_rows() -> list[dict]:
    rows: list[dict] = []
    merchants = ["Kedai Ujian Satu", "Kedai Ujian Dua", "Gerai Ujian Tiga"]
    for n in range(12):
        row = fake_receipt(f"legacy-{n}", 1 + n, f"{5 + n}.50", merchants[n % 3])
        receipt_id = uuid.uuid5(NAMESPACE, f"legacy-receipt-{n}")
        row["receipt_path"] = f"2026/10/{receipt_id}.jpg"
        rows.append(row)
    for n in range(3):
        rows.append(fake_screenshot(f"bank-{n}", 15 + n, f"{20 + n}.00", f"Pindahan Ujian {n}", f"REF{900 + n}"))
    rows.append({"txn_date": "2026-10-20", "amount": 9.0, "merchant": None, "category": None, "type": "expense",
                 "mode": "personal", "source": "text", "receipt_path": None, "dedupe_hash": None,
                 "image_hash": None, "raw_extraction": {"needs_review": False}})
    rows.append({"txn_date": "2026-10-21", "amount": 9.0, "merchant": None, "category": None, "type": "expense",
                 "mode": "personal", "source": "text", "receipt_path": None, "dedupe_hash": None,
                 "image_hash": None, "raw_extraction": {"needs_review": False}})
    rows.append({"txn_date": "2026-10-22", "amount": 30.0, "merchant": "Kedai Manual", "category": "food",
                 "type": "expense", "mode": "personal", "source": "manual", "receipt_path": None,
                 "dedupe_hash": None, "image_hash": None, "raw_extraction": {"needs_review": False}})
    rows.append({"txn_date": "2026-10-23", "amount": 14.0, "merchant": "Kedai Manual", "category": "food",
                 "type": "expense", "mode": "personal", "source": "manual", "receipt_path": None,
                 "dedupe_hash": None, "image_hash": None, "raw_extraction": {"needs_review": False}})
    return rows


def upload_fake_object(bucket, path: str, payload: bytes) -> None:
    bucket.upload(path, payload, {"content-type": "image/jpeg", "upsert": "false"})


def write_rows(client, rows: list[dict], *, with_objects: bool, owner: str | None = None) -> int:
    """Insert rows (after uploading their fake images, when they have receipts)."""
    bucket = client.storage.from_(BUCKET)
    prepared = []
    for row in rows:
        payload = row.pop("_payload", None)
        row.pop("_label", None)
        if with_objects and row.get("receipt_path") and payload is not None:
            upload_fake_object(bucket, row["receipt_path"], payload)
        if owner is not None:
            row["user_id"] = owner
        prepared.append(row)
    client.table("transactions").insert(prepared).execute()
    return len(prepared)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--phase", required=True, choices=["before", "after"])
    args = parser.parse_args(argv)

    values = dotenv_values(args.env_file)
    url = (values.get("SUPABASE_URL") or "").rstrip("/")
    key = values.get("SUPABASE_SERVICE_KEY") or ""
    match = re.match(r"^https://([a-z0-9]{20})\.supabase\.co$", url)
    ref = match.group(1) if match else None
    if ref == LIVE_PROJECT_REF:
        print("refused: live project", file=sys.stderr)
        return 2
    if ref != STAGING_PROJECT_REF:
        print("refused: not the staging project", file=sys.stderr)
        return 2
    client = create_client(url, key)

    if args.phase == "before":
        count = write_rows(client, before_rows(), with_objects=True)
        print(f"before: inserted {count} rows and their fake receipt objects")
        return 0

    owner_a = values.get("STAGING_USER_A_ID")
    owner_b = values.get("STAGING_USER_B_ID")
    if not owner_a or not owner_b:
        print("refused: STAGING_USER_A_ID / STAGING_USER_B_ID missing from the env file", file=sys.stderr)
        return 2

    # Duplicates across owners: B repeats A's dedupe and image hashes exactly.
    a_rows = client.table("transactions").select("dedupe_hash,image_hash,receipt_path").eq(
        "user_id", owner_a).not_.is_("dedupe_hash", "null").limit(3).execute().data
    b_rows: list[dict] = []
    for index, source in enumerate(a_rows):
        b_rows.append({
            "txn_date": "2026-10-11", "amount": 55.0 + index, "merchant": f"Kedai B {index}",
            "category": "food", "type": "expense", "mode": "personal", "source": "receipt_scan",
            "dedupe_hash": source["dedupe_hash"], "image_hash": source["image_hash"],
            "receipt_path": None, "raw_extraction": {"needs_review": False},
        })
    fresh = fake_receipt("b-own-1", 25, "66.60", "Kedai B Sendiri")
    fresh["receipt_path"] = f"{owner_b}/2026/10/{uuid.uuid5(NAMESPACE, 'b-own-1')}.jpg"
    fresh_payload = fresh.pop("_payload")
    fresh.pop("_label")
    upload_fake_object(client.storage.from_(BUCKET), fresh["receipt_path"], fresh_payload)
    b_rows.append(fresh)
    b_rows.append({"txn_date": "2026-10-26", "amount": 7.0, "merchant": None, "category": None,
                   "type": "expense", "mode": "personal", "source": "text", "receipt_path": None,
                   "dedupe_hash": None, "image_hash": None, "raw_extraction": {"needs_review": False}})
    for row in b_rows:
        row["user_id"] = owner_b
    client.table("transactions").insert(b_rows).execute()
    print(f"after: inserted {len(b_rows)} rows for owner B, {len(a_rows)} of them repeating owner A's hashes")

    # Same-owner duplicate: B's own receipt again. The per-owner unique index must refuse it.
    own_receipt = b_rows[len(a_rows)]  # B's fresh receipt, whose hash belongs to B alone
    try:
        client.table("transactions").insert({**own_receipt, "receipt_path": None, "merchant": "Kedai B Pendua"}).execute()
        print("same-owner duplicate: ACCEPTED (unexpected: the per-owner unique index is missing)")
        return 1
    except Exception as exc:  # noqa: BLE001 - PostgREST raises on the unique violation
        print(f"same-owner duplicate: refused ({type(exc).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
