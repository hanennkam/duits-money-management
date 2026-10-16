"""One-off, read-only backup of the Supabase `receipts` bucket.

Walks every folder in the bucket and downloads each object to
~/Backups/duits-<YYYY-MM-DD>/receipts/, keeping the bucket's folder layout.
It only lists and downloads: nothing in Supabase is uploaded, moved or deleted.
An existing backup folder for today is never overwritten; the script stops instead.

Run from the repo root:  ./.venv/bin/python scripts/backup_receipts.py
The project URL, the file count and the total size are printed: the URL first, so a `.env` pointed at the
wrong project is visible in the output rather than silent.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import get_supabase  # noqa: E402

PAGE_SIZE = 1000


def list_folder(bucket, prefix: str) -> list[dict]:
    entries: list[dict] = []
    offset = 0
    while True:
        page = bucket.list(
            prefix,
            {"limit": PAGE_SIZE, "offset": offset, "sortBy": {"column": "name", "order": "asc"}},
        )
        entries.extend(page)
        if len(page) < PAGE_SIZE:
            return entries
        offset += PAGE_SIZE


def object_paths(bucket, prefix: str = "") -> Iterator[str]:
    for entry in list_folder(bucket, prefix):
        path = f"{prefix}/{entry['name']}" if prefix else entry["name"]
        if entry.get("id") is None:  # Supabase reports folders with no id
            yield from object_paths(bucket, path)
        else:
            yield path


def main() -> int:
    settings = get_settings()
    print(f"project: {settings.supabase_url.rstrip('/')}")
    bucket = get_supabase().storage.from_(settings.receipts_bucket)

    backup_root = Path.home() / "Backups" / f"duits-{date.today():%Y-%m-%d}"
    target = backup_root / "receipts"
    if backup_root.exists():
        print(f"stopped: {backup_root} already exists; move it aside first", file=sys.stderr)
        return 1
    target.mkdir(parents=True)
    resolved_target = target.resolve()

    count = 0
    size = 0
    failed = 0
    for path in object_paths(bucket):
        dest = (target / path).resolve()
        if not dest.is_relative_to(resolved_target):  # a name that would escape the backup folder
            failed += 1
            continue
        try:
            data = bucket.download(path)
        except Exception:  # noqa: BLE001 - one bad object must not stop the backup
            failed += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        count += 1
        size += len(data)

    print(f"downloaded {count} files, {size} bytes ({size / 1024 / 1024:.1f} MB)")
    if failed:
        print(f"failed: {failed} objects were not saved", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
