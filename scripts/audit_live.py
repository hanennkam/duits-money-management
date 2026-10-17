"""Read-only audit of the live Supabase project: structure and counts only.

Only GET requests, list calls and count queries are made. Nothing is written, uploaded, moved or deleted,
and no row contents, merchants, notes or keys are printed.

What the Supabase APIs can and cannot show:
- PostgREST's OpenAPI document gives table columns, types and nullability.
- Storage lists buckets and objects.
- The Auth endpoints show the sign-in settings and the public JWKS.
- Unique constraints, indexes, RLS state and storage policies are catalog data that the APIs do not
  expose. Those are checked with the read-only queries in scripts/audit_queries.sql, run by a person in
  the SQL editor.

Run from the repo root:  ./.venv/bin/python scripts/audit_live.py
The project URL is printed first, so the console shows which project was actually read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import get_supabase  # noqa: E402

PAGE_SIZE = 1000


def object_count(bucket, prefix: str = "") -> tuple[int, int]:
    """Total objects under a prefix and the number of folders walked. Lists only."""
    objects = 0
    folders = 0
    offset = 0
    while True:
        page = bucket.list(prefix, {"limit": PAGE_SIZE, "offset": offset})
        for entry in page:
            name = f"{prefix}/{entry['name']}" if prefix else entry["name"]
            if entry.get("id") is None:
                folders += 1
                sub_objects, sub_folders = object_count(bucket, name)
                objects += sub_objects
                folders += sub_folders
            else:
                objects += 1
        if len(page) < PAGE_SIZE:
            return objects, folders
        offset += PAGE_SIZE


def main() -> int:
    settings = get_settings()
    base = settings.supabase_url.rstrip("/")
    print(f"project: {base}")
    key_headers = {"apikey": settings.supabase_service_key, "Authorization": f"Bearer {settings.supabase_service_key}"}
    client = get_supabase()

    with httpx.Client(timeout=30) as http:
        print("== 1. PostgREST schema (public tables) ==")
        spec = http.get(f"{base}/rest/v1/", headers=key_headers).json()
        tables = sorted(spec.get("definitions", {}))
        print(f"tables exposed: {tables}")
        definition = spec["definitions"].get("transactions", {})
        required = set(definition.get("required", []))
        print("transactions columns (name: type, nullability):")
        for name, prop in definition.get("properties", {}).items():
            kind = prop.get("format") or prop.get("type")
            print(f"  {name}: {kind}, {'NOT NULL' if name in required else 'nullable'}")
        pk_notes = [n for n, p in definition.get("properties", {}).items() if "Primary Key" in p.get("description", "")]
        print(f"primary key column(s) per OpenAPI: {pk_notes}")

        print()
        print("== 2. Row count ==")
        rows = client.table("transactions").select("id", count="exact").limit(1).execute()
        print(f"transactions rows: {rows.count}")

        print()
        print("== 3. Storage buckets (settings only) ==")
        for bucket in client.storage.list_buckets():
            print(
                f"  {bucket.name}: public={bucket.public}, "
                f"file_size_limit={bucket.file_size_limit}, "
                f"allowed_mime_types={bucket.allowed_mime_types}"
            )

        print()
        print("== 4. receipts bucket object count ==")
        objects, folders = object_count(client.storage.from_(settings.receipts_bucket))
        print(f"receipts objects: {objects} (in {folders} folders)")

        print()
        print("== 5. Auth: JWKS and sign-in settings (flags only) ==")
        jwks = http.get(f"{base}/auth/v1/.well-known/jwks.json")
        keys = jwks.json().get("keys", []) if jwks.status_code == 200 else []
        print(f"JWKS status {jwks.status_code}, public keys: {len(keys)}")
        for key in keys:
            print(f"  kty={key.get('kty')} alg={key.get('alg')} crv={key.get('crv')}")
        settings_resp = http.get(f"{base}/auth/v1/settings", headers=key_headers)
        if settings_resp.status_code == 200:
            auth = settings_resp.json()
            print(f"  disable_signup={auth.get('disable_signup')}")
            print(f"  mailer_autoconfirm={auth.get('mailer_autoconfirm')}")
            print(f"  anonymous_users={auth.get('anonymous_users_enabled', auth.get('anonymous_users'))}")
            external = auth.get("external", {}) or {}
            print(f"  external providers enabled: {sorted(name for name, on in external.items() if on is True)}")
        else:
            print(f"  auth settings status {settings_resp.status_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
