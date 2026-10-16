"""Move legacy receipt objects into the owner's folder: YYYY/MM/x.jpg -> <user_id>/YYYY/MM/x.jpg.

For each transactions row whose receipt_path is still in the legacy YYYY/MM/ form:
  1. copy the object to <user_id>/YYYY/MM/..., unless the same bytes are already there
  2. download the copy and compare its SHA-256 with the original
  3. point receipt_path at the copy, only while it still holds the old path
  4. delete the original, only after step 3 has been confirmed

Idempotent: a row already under <user_id>/ is skipped, so a re-run finishes whatever an earlier run left.
Dry run is the default. Nothing is written unless --apply is given.
Only counts are printed: no paths, user ids, merchants or keys.

Guards: --env-file is required (no default, so the live .env is never picked up by accident), the project ref
in its SUPABASE_URL must match --project-ref, and the live project is refused unless --allow-live is given.

Usage (staging):
  ./.venv/bin/python scripts/migrate_receipts.py --env-file .env.staging --project-ref <ref>
  ./.venv/bin/python scripts/migrate_receipts.py --env-file .env.staging --project-ref <ref> --apply
Exit codes: 0 clean, 1 some rows could not be moved (counts say which), 2 refused by a guard.
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import dotenv_values
from supabase import create_client

LIVE_PROJECT_REF = "viorpltdkpexswvofeul"
PAGE_SIZE = 500
LEGACY_PATH = re.compile(r"^\d{4}/\d{2}/[^/]+$")
PROJECT_URL = re.compile(r"^https://([a-z0-9]{20})\.supabase\.co/?$")


def project_ref(url: str) -> str | None:
    match = PROJECT_URL.match(url or "")
    return match.group(1) if match else None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def legacy_rows(client) -> list[dict]:
    """Every row that has a receipt, paged so a large table is read in full."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = (
            client.table("transactions")
            .select("id,user_id,receipt_path")
            .not_.is_("receipt_path", "null")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        ) or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def move_one(client, bucket_name: str, row: dict, stats: Counter, apply: bool) -> None:
    bucket = client.storage.from_(bucket_name)
    old = row["receipt_path"]
    new = f"{row['user_id']}/{old}"
    if not apply:
        if bucket.exists(old):
            stats["would_move"] += 1
        else:
            stats["missing_source"] += 1
        return

    if not bucket.exists(old):
        stats["missing_source"] += 1
        return
    original = bucket.download(old)

    if bucket.exists(new):
        if digest(bucket.download(new)) != digest(original):
            stats["conflict_at_target"] += 1  # something else already sits there: never overwrite it
            return
    else:
        content_type = mimetypes.guess_type(old)[0] or "application/octet-stream"
        bucket.upload(new, original, {"content-type": content_type, "upsert": "false"})
        stats["copied"] += 1
        stats["bytes_copied"] += len(original)
    if digest(bucket.download(new)) != digest(original):
        stats["verify_failed"] += 1  # the copy is not what we read: keep the original
        return

    updated = (
        client.table("transactions")
        .update({"receipt_path": new})
        .eq("id", row["id"])
        .eq("receipt_path", old)
        .execute()
        .data
    )
    if not updated:
        stats["row_changed_underneath"] += 1  # keep the original; the new copy is harmless and re-runnable
        return
    stats["rows_updated"] += 1

    bucket.remove([old])
    if bucket.exists(old):
        stats["delete_failed"] += 1
        return
    stats["originals_deleted"] += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", required=True, help="env file holding SUPABASE_URL and SUPABASE_SERVICE_KEY")
    parser.add_argument("--project-ref", required=True, help="the project ref the URL must point at")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--allow-live", action="store_true", help="permit the live project (not used in staging)")
    args = parser.parse_args(argv)

    values = dotenv_values(args.env_file)
    url = (values.get("SUPABASE_URL") or "").strip()
    key = (values.get("SUPABASE_SERVICE_KEY") or "").strip()
    bucket_name = (values.get("RECEIPTS_BUCKET") or "receipts").strip()
    ref = project_ref(url)
    if not url or not key or ref is None:
        print("refused: the env file lacks a usable SUPABASE_URL or SUPABASE_SERVICE_KEY", file=sys.stderr)
        return 2
    if ref != args.project_ref:
        print("refused: the env file's project does not match --project-ref", file=sys.stderr)
        return 2
    if ref == LIVE_PROJECT_REF and not args.allow_live:
        print("refused: this is the live project; pass --allow-live only on a reviewed runbook step", file=sys.stderr)
        return 2

    client = create_client(url, key)
    rows = legacy_rows(client)
    stats: Counter = Counter()
    stats["rows_with_receipt"] = len(rows)

    if any(row.get("user_id") is None for row in rows):
        print("refused: some receipt rows have no owner; finish the backfill first", file=sys.stderr)
        return 2

    to_move = []
    for row in rows:
        if row["receipt_path"].startswith(f"{row['user_id']}/"):
            stats["already_moved"] += 1
        elif LEGACY_PATH.match(row["receipt_path"]):
            to_move.append(row)
        else:
            stats["unexpected_format"] += 1

    stats["legacy_rows"] = len(to_move)
    for row in to_move:
        move_one(client, bucket_name, row, stats, args.apply)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"mode: {mode}")
    for name in (
        "rows_with_receipt", "already_moved", "legacy_rows", "would_move", "missing_source",
        "copied", "bytes_copied", "rows_updated", "originals_deleted", "conflict_at_target",
        "verify_failed", "row_changed_underneath", "delete_failed", "unexpected_format",
    ):
        if stats[name] or name in ("rows_with_receipt", "legacy_rows"):
            print(f"{name}: {stats[name]}")

    failed = sum(stats[name] for name in (
        "missing_source", "conflict_at_target", "verify_failed", "row_changed_underneath",
        "delete_failed", "unexpected_format",
    ))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
