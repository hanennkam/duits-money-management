# Multi-user step 2: design

Status: proposal. Nothing here is implemented or migrated. Evidence: `docs/multi-user-audit.md`. "Done" means
`tests/test_isolation.py` passes with `MULTI_USER_READY = True`.

## 1. Data access: service key plus a required owner

**Decision: keep the service-role client, and make a forgotten owner filter impossible in the code.**

- Every transactions and Storage helper in `app/db.py` takes a keyword-only, **required** `user_id: UUID`, with
  no default. A call without it is a `TypeError`, not a silent unfiltered query. The step-1 test already checks
  the signatures.
- Only `app/db.py` may call `get_supabase()`. A test should enforce this; it is not written yet.
- Routes get the caller from one dependency, `current_user`, which returns a verified `UUID` that is passed down.
- RLS is enabled with owner policies. The service key bypasses RLS, so these policies only protect a future
  anon or user-key path. They stay in as a backstop.

**Why not a user-scoped client (anon key plus the user's JWT, RLS filters)?** It is the stronger runtime
guarantee, and I weighed it. It does not fit this app. The iOS Shortcut cannot hold a Supabase session safely:
it would need a long-lived refresh token, which is a full account credential. A personal access token that maps
to one `user_id` and can be revoked is the safer thing to put in a Shortcut. Once that mapping exists, the server
holds the user id and can act for a user only through helpers that require it. The residual risk is a future
developer calling the service client directly; the required parameter, the call-site check and the RLS backstop
cover that.

## 2. Authentication

- **Browser:** Supabase Auth, email and password. The page calls the Auth REST endpoints with `fetch`, so it stays
  one file with no build step. The access token goes in `Authorization: Bearer` through one `api()` wrapper.
  On a 401 it refreshes once, then shows the login card. The publishable (anon) key sits in the page; it is
  public by design.
- **Shortcut:** a personal access token, created in Settings and shown once, stored as a SHA-256 hash in
  `api_tokens`. Revocable, with no Supabase session.
- **Verification:** the JWT is checked locally against Supabase's JWKS, which is ES256 (audit section 3).
  Library: **PyJWT with the `cryptography` extra** (`pyjwt[crypto]`). It is already installed transitively and
  listed in `requirements-dev.txt`; add it to `requirements.txt` for production. Checks: `alg` is ES256, `kid` is
  in the JWKS, `aud == "authenticated"`, `iss == <SUPABASE_URL>/auth/v1`, `exp` and `iat` with 30s leeway, and
  `sub` parses as a UUID. Keys are cached, and refetched once on an unknown `kid` (rotation).
- **Why not `GET /auth/v1/user` per request?** It adds a round trip to every call on a free Render instance
  that already sleeps, and every request then depends on Auth being up. The trade-off of local verification: a
  revoked session stays valid until its token expires (one hour by default). Acceptable for a personal app.
- `X-API-Key` is retired at cutover.

## 3. Migration

`migrations/0002_multi_user.up.sql` and `.down.sql`. **Neither is executed.** In order:

1. Add `user_id uuid references auth.users(id)`, nullable.
2. Backfill every row to the owner. The owner is set with `set_config`; the script stops if it is missing.
3. Drop the global unique constraints on `dedupe_hash` and `image_hash`, found by catalog lookup.
4. Add partial unique indexes on `(user_id, dedupe_hash)` and `(user_id, image_hash)` where the hash is not null.
5. Add the owner listing index.
6. Set `user_id NOT NULL`, guarded so it raises if a row lacks an owner. This runs **after** the step-2 code is
   live, because step-1 code still inserts without an owner during the deploy.
7. RLS policies on `transactions`: select, insert, update and delete, all `user_id = auth.uid()`.
8. `api_tokens`, with RLS on and no policies.
9. Storage policies on `storage.objects` for bucket `receipts`, keyed on the first folder of the object name.

**Storage paths:** `<user_id>/YYYY/MM/<uuid>.jpg` for new uploads. Existing `YYYY/MM/...` objects move to
`<owner>/...` through the Storage API, with `receipt_path` updated together. That is a script, run in staging
first; the old path is kept until the move is verified.

**Rollback** (`.down.sql`): drop the policies, `api_tokens` and the new indexes; restore global uniqueness; drop
`user_id`. Rows are kept. The rollback refuses to run if two owners share a dedupe hash. Moved receipts go back
with the reverse script.

## 4. Rehearsal on staging

1. Create a **separate** staging Supabase project. Do not link it to production.
2. Rebuild the live structure (`schema.sql` plus `image_hash`, and what `scripts/audit_queries.sql` shows).
   Compare the audit output with production before going on.
3. Load a copy of production data. It is personal financial data: limit access to staging and delete the copy
   afterwards. Copy receipts with `scripts/backup_receipts.py`, then upload them to staging. Production is only
   ever read.
4. Run the audit against staging and confirm the row and object counts match production.
5. Apply the up migration with `app.owner_id` set to your staging account. Check that no row has a null
   `user_id`, and that the storage move leaves no object behind.
6. Create two staging users, A and B. Run `tests/test_isolation.py` with `MULTI_USER_READY = True` against
   staging, using real tokens. Exercise scan, text, manual create, edit, delete and receipt URLs as each user.
7. Rehearse the rollback, compare counts, then re-apply the up migration.
8. Go or no-go. Production: fresh backup of the table and the bucket, deploy the code, apply the up migration,
   run the NOT NULL step, move receipts, re-run the audit queries.

## 5. Decisions needed from you

- May the browser hold the publishable key in the page?
- Sign-up: close it entirely, or allow-list two accounts?
- Is a one-hour window for a revoked session acceptable, or should each request call Auth?
