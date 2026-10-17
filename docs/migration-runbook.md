# Migration runbook: multi-user (0002) on the LIVE project

> **Superseded — use `docs/CUTOVER_RUNBOOK.md`.** That is the runbook the cutover is actually following, and it
> is the one kept current. This file is kept for the pre-flight detail and the "What staging proved" record. It
> differs on one step that matters: §1 puts the merge to `main` **first**, with Render auto-deploy paused, while
> `docs/CUTOVER_RUNBOOK.md` merges at its step 11, **after** the migration and the env vars. The owner chose the
> latter. Do not follow this file's merge order on a database that has not had `0002` applied: the branch selects
> `user_id`, so deploying against the old schema answers 42703 for every request.

**Status: written, not run.** *(Historical: since this was written, `0002` **has** run on live and the receipt
objects have been migrated — see `NEXT_STEPS.md`, Pass 13.)* Do not start this on live until every item in
"Go / no-go" is ticked. Everything
here was rehearsed on the staging project first (see "What staging proved"). Each step names the expected
result, and a deviation is a stop, not a judgement call.

*(Added 2026-10-17: §10 records the **0003** rehearsal — budget, balance and monthly commitments. That migration
is new, **nothing in it has been run anywhere**, and §10 is the sequence to run. It does not touch
`public.transactions`, so it does not re-open anything in §1–§8.)*

Live project ref: `viorpltdkpexswvofeul`. Staging ref: `tddigsmukmhkjrwiqdec`. Check the ref in every
console and env file before a write. The scripts refuse live unless `--allow-live` is given, and only this
runbook passes it.

## 0. Roles and rules

- One operator runs the SQL in the live SQL editor, and a second person reads each result before the next step.
- Live SQL is run **by the operator in the Supabase SQL editor**. No connection string or service key is
  pasted into chat, a file or a commit.
- Stop on any unexpected count, error or output. Do not fix forward on live.

## 1. Go / no-go

Tick all of these before step 2.

- [ ] Branch `multi-user` is merged to `main` **but Render auto-deploy is paused** (Render service → Settings →
      Auto-Deploy: off). A merge alone must not deploy.
- [ ] A **fresh backup of the live database exists** and its time is recorded. Check the Supabase dashboard
      (Database → Backups). A point-in-time restore must be available for this window.
- [ ] A **backup of the receipts bucket** is taken (step 2), and its file count equals the live object count.
- [ ] **Sign-up is closed** in the live project (Authentication → Providers → Email → "Allow new users to sign up"
      off). The audit found it open. The owner account already exists, so closing it does not block anything.
- [ ] The owner's `auth.users` id is known (the value for `app.owner_id`). Confirm it in the Authentication
      dashboard. It is not a secret, but do not commit it.
- [ ] The staging rehearsal results below are reviewed, and no finding is open.
- [ ] The operator has the down file (`migrations/0002_multi_user.down.sql`) open and ready.
- [ ] A quiet time is chosen. Writes from the current app fail for the window between step 4 and step 7.

## 2. Backups and baseline (read-only)

1. **Database.** Confirm the dashboard backup from step 1. Also export the table as a backup you control, with a
   read-only tool such as `pg_dump --data-only --table=public.transactions` against the direct connection string
   from the dashboard. Store the file outside the repo, and do not commit it.
2. **Receipts.** `./.venv/bin/python scripts/backup_receipts.py` writes to `~/Backups/duits-<date>/receipts/`
   (it refuses to overwrite an existing folder). Check the file count against the live object count
   (step 3).
3. **Baseline counts.** Run `./.venv/bin/python scripts/audit_live.py` (read-only) and record:
   - transaction rows: **N**
   - the number of object files in `receipts`: **O**
   - Then run `scripts/audit_queries.sql` in the SQL editor (SELECT only) and keep the output.

Expected: the `receipts` file count from `backup_receipts.py` equals **O**. If it does not, stop.

## 3. Pre-migration state

In the live SQL editor, run `select count(*) from public.transactions;` (expect **N**) and
`select count(*) from public.transactions where receipt_path is not null;` (expect **R**). Record R.

The live table was confirmed in the SQL editor (2026-10-17): it has `image_hash`, `dedupe_hash` carries the
**constraint** `transactions_dedupe_hash_key = UNIQUE (dedupe_hash)`, and `image_hash` carries a **partial
unique index** `transactions_image_hash_uidx ... (image_hash) WHERE (image_hash IS NOT NULL)` — an index, not
a constraint. If live shows anything else, **stop**. The up file drops both by catalog (partial or not,
whatever they are called) and refuses to continue if a global unique on those columns survives; a different
starting state still needs a new review.

## 4. Run the up migration (the first live write)

In the live SQL editor, in **one run**, paste:

1. `select set_config('app.owner_id', '<owner auth.users id>', false);`
2. the full contents of `migrations/0002_multi_user.up.sql`

Expected: the run completes with no error. Any error rolls the whole run back, so the table is unchanged.

Then run `migrations/staging/verify_after_up.sql`: one statement, one grid, and every row must match the
expectation written in its own name.

| Grid row | Expected |
| --- | --- |
| 1. rows total | **N** |
| 2. rows without owner | **0** |
| 3. owners | **1** (the owner) |
| 4. `user_id` column | `uuid / NO` |
| 5. global unique on `dedupe_hash` | **none** |
| 6. global unique on `image_hash` | **none** — production's `transactions_image_hash_uidx` must be gone |
| 7. per-owner dedupe uniqueness | `transactions_user_dedupe_key UNIQUE (user_id, dedupe_hash)` |
| 8. per-owner image uniqueness | `CREATE UNIQUE INDEX transactions_user_image_uidx ... WHERE (image_hash IS NOT NULL)` |
| 9. per-owner listing index | `transactions_user_mode_txn_date_idx` |
| 10. RLS on `transactions` / `api_tokens` | `true / true` |
| 11. policies: transactions / storage receipts / api_tokens | `4 / 3 / 0` |
| 12. snapshot | **2 rows**: `constraint transactions_dedupe_hash_key` and `index transactions_image_hash_uidx`, the second one **with** its `WHERE` clause |

If any row differs, **stop** and run the rollback (section 7). The snapshot in row 12 is what makes the
rollback exact.

## 5. Move the receipt objects

The migration does not move files. The old paths still work until this step is verified.

1. Dry run (read-only, the default):
   ```
   ./.venv/bin/python scripts/migrate_receipts.py --env-file .env --project-ref viorpltdkpexswvofeul --allow-live
   ```
   Expected: `legacy_rows` = **R** minus the rows already under an owner folder (after step 4, that is every
   row with a receipt, so **R**), `missing_source: 0`, `unexpected_format: 0`. Exit code 0.
   If `missing_source` or `unexpected_format` is not 0, **stop**.
2. Apply, after the dry run is as expected:
   ```
   ./.venv/bin/python scripts/migrate_receipts.py --env-file .env --project-ref viorpltdkpexswvofeul --allow-live --apply
   ```
   Expected: `copied` = **R**, `rows_updated` = **R**, `originals_deleted` = **R**, every failure counter 0.
   Exit code 0. A non-zero counter means some rows were left on their old path and are safe there. Investigate
   before continuing.
3. Run the dry run again. Expected: `legacy_rows: 0`, `already_moved` = **R**. This is the idempotence check.
4. Check the bucket: no object outside the owner's folder (`receipts/<owner>/...` only).

**Note:** `--env-file .env` is the live env file. The script refuses if its ref is not `--project-ref`, so the
two must match. Pass `--allow-live` only in this step.

## 6. Deploy the step-2 code

1. In Render, set the environment variables **before** the deploy:
   - `ALLOW_LEGACY_API_KEY=true`
   - `LEGACY_USER_ID=<owner auth.users id>`
   Without these, the current page and the iOS Shortcut get 401 (the sign-in screen does not exist yet).
2. Trigger the deploy of `main` (manual deploy). Wait for it to go live.
3. Smoke test, **read-only**: `GET /health` → 200; `GET /` → 200 with `no-store`; `GET /transactions?month=<a month with data>`
   with `X-API-Key` → 200, and the count matches the expected owner count. **Do not** scan, create, edit or delete
   on live as a test.
4. Re-enable Render auto-deploy.

## 7. Roll back (if needed, before or after step 6)

Rollback is data-preserving: rows are kept, and receipts can stay where they are, because each row's
`receipt_path` is the source of truth.

1. Pause writes if possible. Pause Render auto-deploy.
2. Run `migrations/0002_multi_user.down.sql` in the live SQL editor, in one run. It refuses if two owners share a
   dedupe hash or an image hash, and nothing changes in that case. Resolving such rows is a human decision (which copy to keep). Do
   not delete rows to make the rollback pass without that decision.
3. Run `migrations/staging/verify_after_down.sql`: one statement, one grid. Expected: row count **N** (or the
   count at that time), no `user_id` column, the original global uniqueness back **as it was** — the
   `transactions_dedupe_hash_key` constraint and the partial index `transactions_image_hash_uidx` with its
   `WHERE` clause — no per-owner objects left, no owner policies, no `api_tokens`, and no snapshot table.
4. Deploy the previous commit (the one before step 2) with `X-API-Key` as before. The pre-step-2 code never reads
   `user_id`, so it works with the restored schema.

Re-running step 4 after a rollback is supported: the up file creates the snapshot again. This was rehearsed on
PGlite (up, down, up).

## 8. Expected final state

- Rows: **N**, all owned by the owner. Receipts: **R**, all under `<owner>/YYYY/MM/`.
- Constraints: per-owner unique uniqueness only — the constraint `transactions_user_dedupe_key` on
  `(user_id, dedupe_hash)` and the partial unique index `transactions_user_image_uidx` on
  `(user_id, image_hash) WHERE image_hash IS NOT NULL`.
- RLS and storage policies on.
- Sign-up closed.
- Render: step-2 code, the two legacy variables set, auto-deploy on.
- The snapshot table kept until the rollback window is closed. Drop it only after the operator signs off:
  `drop table public.migration_0002_saved_constraints;`

## 9. What staging proved (and what it did not)

Rehearsed on the staging project (`tddigsmukmhkjrwiqdec`), with fake data for two users.

- **A bug in the up migration was found and fixed.** Step 3 matched the wrong pattern (`\m` at the end of a
  word instead of `\M`), dropped nothing, and still reported success. The fix drops by name, saves the originals
  to the snapshot, and refuses to continue if a global unique survives. Staging was repaired with
  `migrations/staging/02_repair_after_bad_up.sql`, which refuses to run twice.
- **A second bug in the up migration was found and fixed (2026-10-17).** Step 3 found the global unique
  objects by matching `indexdef` text, and its pattern was anchored on `(dedupe_hash)` / `(image_hash)`. Live's
  `image_hash` uniqueness is a **partial** index, whose definition ends in `WHERE (image_hash IS NOT NULL)`,
  so nothing matched: the index survived, guard 3c did not fire either, and the migration would have reported
  success while leaving `image_hash` globally unique — a second owner could never scan a photo the first owner
  had. Step 3a/3b/3c now work from the catalog (`pg_index.indkey`), so partial or not and whatever the name,
  the object is snapshotted verbatim, dropped, and the guard raises if any survives.
- **Per-owner uniqueness works.** A cross-owner duplicate is accepted, and a same-owner duplicate is refused.
- **Receipt move.** 12 legacy objects were copied, verified by SHA-256, and their rows updated. The originals were
  then deleted. A second run found nothing to do.
- **Real isolation.** 15 tests run against the real project, with real sign-in, real JWKS verification, real
  Postgres and Storage, and PostgREST and Storage RLS as each user. They include the 409 case in both directions.
  All passed. (The 409 test first failed because the seed had given B a copy of A's key. That was a test error,
  and the test was corrected.)
- **Rollback.** The down file refused while cross-owner duplicates existed, which is the guard working. After the
  duplicates were removed, it succeeded and the verification matched.

**Not verified by staging:**

- Real Postgres under concurrent live traffic.
- Real Render behaviour, and the env-var change at deploy.
- The iOS Shortcut and the UI against the new code.
- Live sign-up being closed (it was open on staging too; the dashboard setting was not changed by this work).
- The live schema beyond the audit's findings: unique constraint names and index definitions. These are no
  longer inferred — the live SQL editor confirmed them on 2026-10-17 (`transactions_dedupe_hash_key` as a
  constraint, `transactions_image_hash_uidx` as a partial unique index), and step 3 and step 4's verification
  re-check the same facts on the day.

**Open finding (not fixed in this step):** `GET /transactions/{id}/receipt-url` returns Supabase's **relative**
signed path (`/object/sign/...`). A client cannot use it as a URL. The fix is to join it to
`<SUPABASE_URL>/storage/v1`, and it needs a decision because it changes the response.

## 10. 0003 — budget, balance and monthly commitments (staging rehearsal, NOT run)

`migrations/0003_budget_commitments.up.sql` adds `public.user_finance_settings`, `public.monthly_commitments`,
`public.commitment_payments` and the view `public.transaction_totals`. It touches **nothing** in
`public.transactions`: no column, no row, no index, so it does not re-open anything in §1–§8. The down file drops
the four objects, and because that destroys rows the owner typed in, it first copies every row into
`public.migration_0003_saved_rows` (RLS enabled **and** forced, 0 policies) and refuses to start until the
operator acknowledges the loss.

Run all of this on the **staging** project (`tddigsmukmhkjrwiqdec`). Only the two migration files write; the
verification script is `SELECT`-only and names no project. `.env.staging` drives the app, and
`scripts/run_staging_tests.py` refuses to run if that file points at live.

1. **Up.** In the staging SQL editor, in **one run**, paste the whole of
   `migrations/0003_budget_commitments.up.sql`. It opens with `begin;` and ends with `commit;`, and its final
   `do $$` block names whatever is missing.
   - Expected: no error. **STOP** on any error — the run rolls back as a whole, so the project is unchanged.
2. **Verify.** Run `migrations/staging/verify_after_0003.sql`: one statement, one grid. Compare every row with the
   expectation written in that row's own name.
   - Row 4 must read `true/true, true/true, true/true` — ENABLE **and** FORCE, per table.
   - Row 5 must read `4 / 4 / 4`, and row 6 must read `6` (insert and update policies carry a `WITH CHECK`).
   - Row 7 must name **both** columns:
     `FOREIGN KEY (commitment_id, user_id) REFERENCES monthly_commitments(id, user_id) ON DELETE CASCADE`.
   - Row 12 must read `v / true` (a view, `security_invoker`), and row 13 must read `false / false` — neither
     `anon` nor `authenticated` has `SELECT` on the view, because the revoke is the whole gate for it.
   - Row 16 (`transactions` rows) must equal what it was before step 1. 0003 must not move a transaction.
   - **STOP** on any other value, and go to step 4.
3. **The isolation suite.** `./.venv/bin/python scripts/run_staging_tests.py`
   - Expected: all green, including the six 0003 tests. Those are the evidence that the service-key API still
     reads and writes its own rows with the policies **forced** on, that anon/publishable is refused, that one
     owner cannot see, change or delete another's commitment through PostgREST, and that a paid mark naming
     another owner's commitment is refused by the composite foreign key.
   - If 0003 is not applied, those six skip with that reason; the rest of the suite still runs.
   - **STOP** if any test fails. A refusal on the API's own path would mean FORCE is stopping the service key,
     and that is a decision, not a patch.
4. **Down (the destructive half).** In the staging SQL editor, in one run: first
   `select set_config('app.allow_0003_data_loss', 'yes', false);` and then the whole of
   `migrations/0003_budget_commitments.down.sql`.
   - The guard refuses without that `set_config`. That is the point: the step destroys the opening balance and
     every commitment and paid mark that was typed in.
   - Expected: no error, and `public.migration_0003_saved_rows` holds **3** rows.
5. **Verify the rollback.** Run `verify_after_0003.sql` again. Expected: rows 1–3 report `MISSING`, row 12
   reports `MISSING`, row 17 reports `3 row(s), rls true/true, policies 0`, and the `transactions` row count is
   unchanged.
6. **Up again.** Repeat steps 1 and 2. This is the idempotence check: the `if not exists` statements plus the
   named-constraint guard must land on the same grid, and the snapshot table is left where it is.
7. **Live, later, and only by the owner.** Live follows §0's roles and §1's discipline, and it needs its own
   `pg_dump` (step 2) taken first. 0003 is smaller than 0002 — no backfill — but it is not reversible without
   the snapshot, so the snapshot stays until the owner signs off.

**What is verified today: nothing.** No part of 0003 has been executed by anyone. The up file's `do` blocks, the
view's `security_invoker`, FORCE row level security and the revoke are argued from the PostgreSQL and Supabase
documentation and from 0002's conventions; steps 1–6 are what turn that into evidence. The staging tests in step 3
are written but have never been run.

**One dependency worth knowing before step 2.** The up file's guard calls `has_table_privilege('anon', ...)`, and
the down file's closing block asserts on `pg_class` and `pg_policies`. Both rely on the `anon`, `authenticated`
and `service_role` roles existing, as they do in any Supabase project. A database without them fails the guard
loudly rather than silently.

**Rollback window.** Keep `public.migration_0003_saved_rows` until the owner signs off, exactly like
`public.migration_0002_saved_constraints`. Dropping it is a separate, owner-approved step:
`drop table public.migration_0003_saved_rows;`
