# Multi-user step 1: audit of the live database

Date: 2026-10-16. Branch `multi-user`. Read-only: the audit made only GET requests, list calls and count
queries (`scripts/audit_live.py`). Nothing was written, uploaded, moved or deleted. No row contents, merchants,
notes or keys are recorded here.

## 1. Live state vs `schema.sql`

Source of the live facts: PostgREST's OpenAPI document, the row count, Storage listing, and the Auth
settings and JWKS endpoints. Anything marked **unverified** needs the catalog queries in
`scripts/audit_queries.sql`, which only a person can run in the SQL editor.

| Item | `schema.sql` | Live (verified) | Result |
| --- | --- | --- | --- |
| `id uuid` primary key | yes | `uuid`, NOT NULL, PK | match |
| `created_at timestamptz` | NOT NULL default now() | `timestamp with time zone`, NOT NULL | match |
| `txn_date date` | NOT NULL | `date`, NOT NULL | match |
| `amount numeric(12,2)` | NOT NULL | `numeric`, NOT NULL | type matches; **precision unverified** (query A) |
| `currency text` | NOT NULL default 'MYR' | `text`, NOT NULL | match; default unverified |
| `merchant`, `category` text | nullable | nullable | match |
| `type`, `mode` text | NOT NULL, check constraints | `text`, NOT NULL | match; **check constraints unverified** (query B) |
| `items jsonb` | nullable | nullable | match |
| `receipt_path text` | nullable | nullable | match |
| `source text` | nullable | nullable | match |
| `dedupe_hash text` | **`unique`** | nullable text | **uniqueness unverified** (query B) |
| `raw_extraction jsonb` | nullable | nullable | match |
| `image_hash text` | **absent** | **present**, nullable | **difference**: live has a column schema.sql does not |
| Index `transactions_mode_txn_date_idx` | yes | **unverified** | query B |
| RLS enabled on `transactions` | yes (schema.sql) | **unverified** | query C |
| RLS policies on `transactions` | none | **unverified** | query D |
| Bucket `receipts` private | yes | `public=False`, no size or MIME limit | match (limits not in schema.sql) |
| Storage policies on `storage.objects` | none in schema.sql | **unverified** | query E |
| Grants to `anon` / `authenticated` | none in schema.sql | **unverified** | query G |

Column order differs (`image_hash` is last, which fits an `ALTER TABLE ... ADD COLUMN`). That is cosmetic.

**Differences to fix in `schema.sql` before step 2** (not done here; schema changes need your go-ahead):
`image_hash` column and its index or constraint, plus whatever query B shows for `dedupe_hash`.

## 2. Counts

- `transactions` rows: **72**
- `receipts` objects: **16**, in 2 folders. This matches the 16 files downloaded by `scripts/backup_receipts.py`
  on 2026-10-16.

## 3. Auth settings (Supabase Auth, read-only)

- **Public sign-up is open** (`disable_signup = false`). Only the email provider is enabled.
  Email auto-confirm is off.
- **JWKS:** one public key, `kty=EC`, `alg=ES256`, `crv=P-256`. The project signs with asymmetric keys, so tokens
  can be verified locally from the public JWKS without the JWT secret.

**This matters before step 2:** with open sign-up, anyone can create an account and reach the API. Turn sign-up
off (or add an allow-list) before any second user is created. That is a dashboard setting, not a code change.

## 4. Checklist for step 2: routes and helpers that touch transactions or storage

None of the routes or helpers filters by owner, because no owner exists yet. The checklist below is what
step 2 must change. "Owner" means the caller's `user_id` from the verified token.

### Routes (`app/main.py`)

| Route | Reads or writes | Owner filter today | Step 2 change |
| --- | --- | --- | --- |
| `POST /transactions/scan` | image-hash lookup (global), dedupe lookup (global), Storage upload, insert, Storage delete on failure | **no** | owner on every lookup; stamp `user_id`; storage path under `user_id/` |
| `POST /transactions/text` | dedupe lookup (only when a hash exists), insert | **no** | stamp `user_id`; lookup by owner |
| `POST /transactions` | dedupe lookup (manual rows have no hash), insert | **no** | stamp `user_id`; ignore any body `user_id` |
| `GET /transactions?month&mode` | list | **no** | list by owner |
| `GET /transactions/{id}` | read by id | **no** | read by id AND owner, 404 otherwise |
| `PATCH /transactions/{id}` | read by id, update by id | **no** | owner on read and update |
| `DELETE /transactions/{id}` | read by id, Storage delete, delete by id | **no** | owner on read and delete; never delete a foreign receipt |
| `GET /transactions/{id}/receipt-url` | read by id, sign any path given | **no** | owner on read (404 for foreign ids) |
| `GET /summary?month&mode` | sums via list | **no** | sums by owner |
| `GET /`, `/health`, icon routes | none | n/a | stay public |

### Database helpers (`app/db.py`)

| Helper | Table or Storage | Owner filter today | Step 2 change |
| --- | --- | --- | --- |
| `find_by_dedupe_hashes`, `find_by_dedupe_hash` | transactions | **no**: global | add required `user_id` |
| `find_by_image_hash` | transactions | **no**: global | add required `user_id` |
| `get_transaction`, `update_transaction`, `delete_transaction` | transactions | **no**: by id only | add required `user_id` |
| `insert_transaction` | transactions | **no**: the row carries no owner | require the row's `user_id` |
| `list_transactions`, `summarize` | transactions | **no** | add required `user_id` |
| `upload_receipt`, `delete_receipt`, `create_receipt_url` | Storage | **no**: paths are `YYYY/MM/<uuid>` | paths under `user_id/` |
| `dedupe_hash`, `dedupe_hashes`, `month_bounds`, `normalise_merchant` | none (pure) | n/a | none |
| `get_supabase` | service-role client | n/a | only `db.py` may call it |

Also outside the app: `scripts/backup_receipts.py` and `scripts/audit_live.py` use the service key and see the whole
bucket. They are admin tools, not user-facing, and should stay that way.

## 5. Findings

1. **A 409 response leaks another user's transaction.** A duplicate scan or dedupe match returns
   `{"transaction": <existing row>}`, and the lookup is global. A second user who scans the same receipt (or
   types the same dedupe key) gets the first user's full row back. This is the most serious finding.
2. **By-id routes ignore ownership.** `GET`, `PATCH`, `DELETE` and `receipt-url` all act on any id. Anyone with the
   shared key can delete another user's row and its receipt.
3. **The dedupe key is globally unique in the schema.** Two users with the same merchant, amount and day collide at
   the database level. Today a lookup that misses would surface as a 500 at insert, not a 409.
4. **Public sign-up is open** (section 3).
5. **Storage paths carry no owner**, so `receipt-url` can sign any object a row points at, and the path scheme gives
   no isolation at the bucket level.
6. **`image_hash` exists live but not in `schema.sql`**, so a fresh database built from the repo would not match
   production. *(2026-10-17: the column was since added to `schema.sql`. Production also carries the partial
   unique index on it, which `schema.sql` does not create — see §6.)*

## 6. Not verified

- Column precision (`numeric(12,2)`), defaults and the `type`/`mode` check constraints.
- Whether `dedupe_hash` is unique in the live database, and the existence and definition of the
  `transactions_mode_txn_date_idx` index and any `image_hash` index.
- RLS enabled or forced, RLS policies, Storage policies, and grants to `anon` and `authenticated`.
- Triggers and functions in `public`.

All of these are in `scripts/audit_queries.sql`. Results should be pasted back as structure only, with no row data.

### Closed 2026-10-17 (read in the live SQL editor, structure only)

The two uniqueness facts listed above are no longer unverified:

- `dedupe_hash` carries the **constraint** `transactions_dedupe_hash_key = UNIQUE (dedupe_hash)`.
- `image_hash` carries a **partial unique index** `transactions_image_hash_uidx`, defined as
  `CREATE UNIQUE INDEX ... ON public.transactions USING btree (image_hash) WHERE (image_hash IS NOT NULL)` —
  an **index**, not a constraint.
- The other objects on the table are `transactions_pkey` and `transactions_mode_txn_date_idx`.

This closes the "unique constraint names and index definitions" gap in
`docs/migration-runbook.md` §9. Both objects are read from the catalog by
`migrations/0002_multi_user.up.sql`, so a partial index is snapshotted with its `WHERE` clause, dropped, and
restored verbatim by `migrations/0002_multi_user.down.sql`. The remaining "not verified" items above are
untouched.
