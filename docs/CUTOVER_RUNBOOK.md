# Cutover runbook — going live

**Status: written, not run.** Nothing here has been executed against the live project.

**Legend.** Every step is marked:

- **MINE** = a step **you** do by hand, in a dashboard or the Supabase SQL editor.
- **YOURS** = a step **the assistant** runs as a command.
- Where a command needs a credential only you hold (the database connection string), it is marked **MINE**
  and the exact command is given to paste.

**Projects.** Live is `viorpltdkpexswvofeul`. Staging is `tddigsmukmhkjrwiqdec`. Only commands that take a
`--project-ref` name their project — that is `migrate_receipts.py` in step 9 — and they refuse the live
project unless `--allow-live` is also passed. The other two commands, `backup_receipts.py` (step 3) and
`audit_live.py` (step 4), take no project argument: they follow whatever project `.env` points at. Both now
print that project's URL as their **first output line**, so check it there. For the rest, **check the ref in
every console before you run anything.**

**Rules.** Stop on any unexpected result. Do not fix forward. Take the backups before step 7 — the migration
is the only irreversible-feeling step and it is the one with a rollback.

---

## 1. Check the live Users list for unknown accounts — MINE

- **Do:** Supabase dashboard → project `viorpltdkpexswvofeul` → **Authentication → Users**.
- **Expected:** only the accounts you expect. For a project that has never been open to the internet, that is
  your own account and nothing else.
- **STOP if** there are accounts you do not recognise. On **staging**, three Gmail accounts appeared while
  sign-up was open there and created rows; they were later confirmed to be the household's, but this check
  remains because **live's** account list is the real question. If live has accounts you do not recognise,
  note the addresses and decide what to do with them **before** step 7 (the migration will assign all
  existing rows to one owner).
- **Roll back from here:** nothing to undo — this step is read-only.

## 2. Back up the database with pg_dump — MINE

The free Supabase plan may have **no dashboard backups**, so this is the only safety net.

- **Do:** Supabase dashboard → **Connect → Session pooler** (or Direct) → copy the URI. Then, on a machine
  with `pg_dump`, run:

  ```bash
  pg_dump --no-owner --no-privileges --file=duits-live-$(date +%Y%m%d-%H%M).sql \
    "postgresql://<user>:<password>@<host>:5432/<db>"
  ```

- **Expected:** a `.sql` file of a sensible size, and `pg_dump` exits 0 with no error.
- **Check:** `grep -c "COPY public.transactions" duits-live-*.sql` should show the table present, and the
  file should not be empty.
- **STOP if** `pg_dump` errors, the file is empty, or you cannot reach the database.
- **Roll back from here:** nothing to undo. Keep the file; it is the restore path for every later step.

## 3. Pre-check the project, then back up the receipts bucket — YOURS

**3a. Confirm which project `.env` points at — before either script below runs.**

```bash
cd /Users/Apple/Dev/Duits-money-management
./.venv/bin/python -c "from app.config import get_settings; print(get_settings().supabase_url)"
```

- **Expected:** `https://viorpltdkpexswvofeul.supabase.co`. This command takes no project argument, and
  neither do the two scripts in steps 3b and 4; all three follow `.env`. Both scripts print this same URL as
  their **first output line**, so the ref is visible in their own output too.
- **STOP if** the ref is anything else — `tddigsmukmhkjrwiqdec` (staging) most of all. A wrong `.env` does
  not error: steps 3 and 4 would back up and audit the wrong project, and every count after them would be
  measured against a bad baseline. Fix `.env`, then re-run.
- **Roll back from here:** nothing to undo — this prints one value and reads nothing.

**3b. Back up the receipts bucket.**

```bash
./.venv/bin/python scripts/backup_receipts.py
```

- **Expected:** first line `project: https://viorpltdkpexswvofeul.supabase.co`, then
  `downloaded N files, … bytes`, exit 0, and the files land in `~/Backups/duits-<date>/receipts/`. The script
  reads `.env` and is read-only.
- **Check:** the file count equals the object count from step 4. The script refuses to overwrite an existing
  folder, so a re-run is safe.
- **STOP if** the first line is not the live project (step 3a), the exit code is non-zero, or any object
  failed (the script prints a `failed:` count).
- **Roll back from here:** nothing to undo. Keep the folder; it is the restore path for receipt objects.

## 4. Baseline audit — YOURS

This script takes no project argument either — run step 3a first if you have not.

```bash
./.venv/bin/python scripts/audit_live.py
```

- **Check first:** the first output line is `project: https://viorpltdkpexswvofeul.supabase.co`.
  **STOP if it is not** — you are baselining the wrong project, and every later step is compared against it
  (see step 3a).
- **Expected:** transaction row count **N**, receipts object count **O**, plus the table columns. Write both
  numbers down; every later step is checked against them.
- **STOP if** the column list does not match `docs/multi-user-audit.md`, or either count is surprising.
- **Roll back from here:** nothing to undo — read-only.

## 5. Site URL, Redirect URLs and custom SMTP — MINE

- **Do (Supabase → Authentication):**
  - **URL Configuration → Site URL:** `https://duits-money-tracking.onrender.com`
  - **Redirect URLs:** add `https://duits-money-tracking.onrender.com/` and, for phone testing,
    `http://<mac-lan-ip>:8765/`.
  - **Emails → SMTP Settings:** enable custom SMTP and copy the values that are **known good on staging**:
    host `smtp.gmail.com`, port `465`, sender `hanennkam@gmail.com`, sender name **Duits**, username the
    same Gmail address, and the password (an App Password if the account has 2FA). Leave
    "Minimum interval per user" at `60` seconds.
- **Expected:** **send one real test message and confirm it actually arrives in the mailbox.** A settings
  page that saves cleanly proves nothing about port, TLS or the credentials. Then confirm
  `POST /auth/v1/recover` for a real address returns **200 with an empty body** — both a known and an
  unknown address must answer the same, or the endpoint leaks which accounts exist.
- **Two caveats, both from the staging setup:**
  - Supabase warns that Gmail is *"designed for sending personal rather than transactional email
    messages. Email deliverability may be impacted."* Gmail caps a **personal** account at roughly 500
    emails a day and 2000 for Workspace, and can throttle or suspend an account it reads as
    bulk-sending. **Batch invites carefully** — one or two at a time, not a list.
  - **The minimum interval per user is 60 seconds.** A second email to the same address inside a minute is
    **silently dropped** — no error, no queue. This will masquerade as a broken SMTP copy if the verifier
    sends a reset and then an invite back to back. Wait a minute between them, or use two addresses.
- **STOP if** the test email does not arrive, or `recover` still returns a non-200 for an existing
  address. Password reset and invites both depend on this.
- **Roll back from here:** the old Site URL / Redirect URLs, noted down before you change them. SMTP can be
  reset to the default provider at any time.

## 6. Close sign-up — MINE

**Do this before the cutover window opens, not during it.** While sign-up is open, anyone with the
publishable key can create an account and write rows; a row created during the migration would be
backfilled to the owner and muddy every count from there on. On staging this exposure produced three
accounts and five rows — later confirmed to be the household's, but the mechanism is real, and it is why
this closes before step 7.

- **Do:** Supabase → **Authentication → Providers → Email** → turn **"Allow new users to sign up"** off.
- **Expected:** this is refused with `signup_disabled`.
- **Check (YOURS):**

  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' -X POST \
    "https://viorpltdkpexswvofeul.supabase.co/auth/v1/signup" \
    -H "apikey: <publishable key>" -H "Content-Type: application/json" \
    -d '{"email":"probe@example.com","password":"a-long-enough-password"}'
  ```

  Expected **HTTP 422** with `"Signups not allowed for this instance"` / `signup_disabled`. This is exactly
  what staging returned once it was closed.
- **STOP if** it returns 200 (an account would be created).
- **Roll back from here:** turn the setting back on. No data changes.

## 7. Run migration 0002 — MINE (SQL editor)

**This is the live write. Do it in one session, and do not run anything else against the database while it runs.**

- **Do:** Supabase dashboard → **SQL Editor** → project `viorpltdkpexswvofeul` → paste, as **one run**:

  ```sql
  select set_config('app.owner_id', '<your auth.users id>', false);
  ```

  followed immediately by the full contents of `migrations/0002_multi_user.up.sql`.

  The `<your auth.users id>` is the id from step 1's Users list. It is not a secret, but do not commit it.
- **Expected:** the run completes with no error. Every existing row is backfilled to that owner. The script
  refuses to start without `app.owner_id` (rehearsed: `set app.owner_id first: …`).
- **Check (YOURS), right after:**

  ```bash
  curl -s "https://viorpltdkpexswvofeul.supabase.co/rest/v1/transactions?select=id" \
    -H "apikey: <service key>" -H "Authorization: Bearer <service key>" \
    -H "Prefer: count=exact" -H "Range-Unit: items" -H "Range: 0-0" -D - -o /dev/null | grep -i content-range
  ```

  Expected the same **N** as step 4. Then run `migrations/staging/verify_after_up.sql` in the SQL editor: it is
  **one statement returning one grid**, and every row must match the expectation written in that row's own
  name — rows without owner **0**, owners **1**, `user_id` **uuid / NO**, **no** global unique left on
  `dedupe_hash` or `image_hash` (they are reported from the catalog, so a *partial* index counts), the
  constraint `transactions_user_dedupe_key`, the partial unique index `transactions_user_image_uidx`,
  `transactions_user_mode_txn_date_idx`, RLS on for `transactions` and `api_tokens`, 4 transaction /
  3 storage receipts / 0 api_tokens policies, and a **2-row** snapshot.
- **STOP if** any statement errors, or the row count changed, or any verification line differs. The whole
  script runs in one transaction, so an error rolls it all back — nothing is half-applied.
- **Roll back from here:** run `migrations/0002_multi_user.down.sql` in the SQL editor. It restores the
  original global unique constraints and indexes from the snapshot table, verbatim (live's `image_hash`
  index comes back **with** its `WHERE (image_hash IS NOT NULL)`), and drops `user_id`. **Rows are kept.**
  It refuses to run if two owners share a hash (rehearsed), and changes nothing in that case.

## 8. Verify the migration — MINE

- **Do:** run `migrations/staging/verify_after_up.sql` (read-only) in the SQL editor and read the grid.
- **Expected:** as listed in step 7. Also confirm `public.migration_0002_saved_constraints` holds **both**
  saved definitions — `constraint transactions_dedupe_hash_key` and `index transactions_image_hash_uidx`
  (with its `WHERE` clause) — **keep that table** until the rollback window closes.
- **STOP if** any row differs from step 7's expectations.
- **Roll back from here:** `migrations/0002_multi_user.down.sql`, as above.

## 9. Migrate the receipt objects — YOURS

```bash
./.venv/bin/python scripts/migrate_receipts.py \
  --env-file .env --project-ref viorpltdkpexswvofeul --allow-live          # dry run
./.venv/bin/python scripts/migrate_receipts.py \
  --env-file .env --project-ref viorpltdkpexswvofeul --allow-live --apply  # then apply
./.venv/bin/python scripts/migrate_receipts.py \
  --env-file .env --project-ref viorpltdkpexswvofeul --allow-live          # confirm
```

- **Expected (dry run):** `legacy_rows` equals the number of rows with a receipt that are not yet under their
  owner's folder, `missing_source: 0`, `unexpected_format: 0`.
- **Expected (apply):** `copied`, `rows_updated` and `originals_deleted` all equal that same number, every
  failure counter 0.
- **Expected (confirm):** `legacy_rows: 0`, `already_moved` equals the number of receipt rows.
- **Note:** a row whose `receipt_path` sits under *another* owner's folder is re-homed, not refused —
  the foreign prefix is stripped and the object lands at `<owner>/YYYY/MM/x.jpg`. This is what a
  **rollback** produces: `0002 down` then `up` reassigns rows without moving the objects back, so it is
  expected after a recovery and is not a reason to stop.
- **A `shared_object` is a skip, not an error.** It means one object is referenced by two rows, so it
  cannot be moved for one without breaking the other; the script reports it and leaves it alone. The rows
  keep working — the app answers 404 for a receipt it cannot reach and still deletes the row. Note it and
  carry on. The script prints `shared_object: skipped … — not an error` and exits 0 for it.
- **STOP if** the dry run shows any `missing_source` or `unexpected_format`, or the apply leaves any
  failure counter non-zero.
- **Roll back from here:** the objects are copied before the original is deleted and the row update is
  conditional, so a partial run leaves the original intact. Re-running is safe. To move an object back by
  hand, use the Storage browser; `receipt_path` is the source of truth, so no rollback script is needed.

## 10. Set the Render environment variables — MINE

- **Do:** Render dashboard → service **duits** → **Environment**:
  - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `ANTHROPIC_API_KEY`, `API_KEY`
  - `ENVIRONMENT=production`
  - `ALLOW_LEGACY_API_KEY=true` and `LEGACY_USER_ID=<owner id>` — only while the iOS Shortcut still uses the
    shared key. Remove both once personal access tokens exist.
  - `PORT` is already set to `10000` by `render.yaml`. **Do not change the Dockerfile default of 8000.**
- **Expected:** every variable saves, and no secret is printed back in full.
- **STOP if** any required variable is blank — the app refuses to start and names the missing ones.
- **Roll back from here:** restore the previous values from the dashboard's own history, or unset the two
  `ALLOW_LEGACY_API_KEY` / `LEGACY_USER_ID` values (the web UI no longer needs them).

## 11. Merge to main and deploy — MINE

- **Do:** open a pull request `multi-user` → `main`, review, and merge. Render auto-deploys from `main`.
  If you want to control the moment, turn **Auto-Deploy** off first and deploy by hand.
- **Expected:** the Render build succeeds and the service goes live.
- **STOP if** the build fails, or the deploy target is not the service you expect.
- **Roll back from here:** Render → **Deploys** → redeploy the previous successful deploy. The pre-migration
  code never reads `user_id`, so it works against the rolled-back schema.

## 12. Smoke test — YOURS

```bash
BASE=https://duits-money-tracking.onrender.com
curl -s -o /dev/null -w 'health %{http_code}\n' $BASE/health
curl -s -D - -o /dev/null $BASE/ | grep -iE '^(HTTP|cache-control|content-security-policy)'
```

- **Expected:** `/health` → **200**. `/` → **200** with `cache-control: no-store` and a
  `content-security-policy` carrying a nonce. Then, on the phone: sign in, one scan, one edit, one delete,
  and the **Build** row in Settings matches the deployed commit.
- **STOP if** health is not 200, the page is cached, or the Build row shows an old stamp (the Home Screen
  shortcut would be serving a stale copy: delete it and add it again).
- **Roll back from here:** redeploy the previous deploy (step 11).

## 13. Invite other users — MINE

- **Do:** Supabase → **Authentication → Users** → **Invite user**, or the equivalent. Then the recipient
  opens the link, which lands on **Set a new password**, and signs in.
- **Expected:** the new user sees an **empty Home** and none of the owner's rows (verified on staging).
- **STOP if** the invite email does not arrive (see step 5) or the link does not land on the set-password
  screen.
- **Roll back from here:** delete the invited user in the dashboard. Their rows (there are none) are removed
  with them.

## 14. After the window — MINE / YOURS

- Keep `public.migration_0002_saved_constraints` until you are satisfied with the release, then
  **MINE**: `drop table public.migration_0002_saved_constraints;` in the SQL editor.
- **YOURS:** re-run `scripts/audit_live.py` and compare the counts with step 4.
- **MINE:** remove `ALLOW_LEGACY_API_KEY` and `LEGACY_USER_ID` once the Shortcut no longer needs them.

---

## What has been rehearsed, and what has not

Rehearsed on a real Postgres with the exact files, and on staging:

> The shape fix of **2026-10-17** (production's `image_hash` uniqueness is a *partial* unique index, not a
> constraint) is rehearsed locally on PGlite with production's exact shape, and re-run on **staging**:
> rebuilt to that shape, `0002 up`, `verify_after_up.sql` (every grid row as expected) and the 15 isolation
> tests, all clean. The staging **rollback** is the one rehearsal step still open — see the current pass in
> `NEXT_STEPS.md`.

- `schema.sql` (now including `image_hash`) creates the table production has. It does **not** create
  production's global uniqueness on `image_hash`: production keeps that as the partial index
  `transactions_image_hash_uidx`, created outside this repo.
  `migrations/staging/00_pre_migration_schema.sql` now creates it, so the rehearsal runs against the shape
  production actually has.
- `0002 up` → `verify` → `0002 down` → `0002 up` again with that shape, never dropping a row: the partial
  index is snapshotted **with its `WHERE` clause**, dropped, replaced by the per-owner constraint and
  partial index, and restored **verbatim** by the rollback. Guard 3c raises when a global unique survives,
  and the rollback still refuses while two owners share a hash (2026-10-17, PGlite, local).
- `0002 up` → `verify_after_up.sql` → the 15 isolation tests on **staging**, with the fixed files against the
  rebuilt shape: 29 rows before and after, one owner, no duplicate hashes, every grid row as expected, and
  **15 passed**. Staging's snapshot came back with **2** rows — the constraint and the partial index, the
  latter with its `WHERE` clause (2026-10-17). The **staging rollback** is not re-run yet.
- `0002 up` → `verify` → `0002 down` → `0002 up` again, never dropping a row: **6 → 6 → 6 → 6** on the local
  Postgres rehearsal, and **30 → 30 → 30 → 30** on staging (both runs used the shape staging had at the
  time, before the `image_hash` index above was added to the rehearsal). Staging reads **29** today, after the
  deliberate delete of the throwaway row (`a2d55e96` — a transaction row id, not a commit). Live is baselined
  fresh in steps 3–4 and is never compared against either number.
- `0002` **refuses to run without `app.owner_id`**.
- The rollback **refuses** while two owners share a hash.
- Per-owner uniqueness: a cross-owner duplicate hash is accepted; a same-owner duplicate is refused.
- `migrate_receipts.py` dry run reaches `legacy_rows: 0`.
- Sign-up refusal (`422`, `signup_disabled`) and the full invite flow, on staging.

**Not rehearsed:** anything against the live project. `pg_dump` needs your connection string. The custom SMTP
path has never sent a successful message **on the live project** — it has on staging (pass 8: a real message
was delivered, and `recover` returned 200 with an empty body), so only the per-project copy is unproven.
Whether the free plan offers dashboard backups is unknown, which is why step 2 uses `pg_dump`.
