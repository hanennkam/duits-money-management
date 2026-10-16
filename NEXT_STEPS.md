# NEXT_STEPS

Prepared after the auth-screen polish on branch `multi-user`. Read this before the next step.

## Status

| | |
| --- | --- |
| Task 1 — verify polish spec | **Done.** Every spec item is present in the code. Nothing was missing, so no code changed. |
| Task 2 — safety checks | **Done, 1 failure left** (forgot-password email delivery). |
| Task 3 — commit and push | **Done.** `multi-user` is pushed. **Not** merged to `main`, **not** deployed to live. |
| Task 5 — this file | **Done.** |
| Verification pass 2 (invite flow) | **Done.** Sign-up is now refused, and the invite flow works end to end. |
| Pass 3 — invite address, PORT, schema, rehearsal, runbook | **Done.** See the summary below. Staging SQL for the live rehearsal still needs you. |
| Pass 4 — verify the invite-address fix | **Done.** Re-ran a real invite flow: Settings now shows the address. Document repaired. |
| Pass 5 — catalog checks + receipt-path crash | **Done.** You checked `verify_after_up.sql` B–F. Fixed a 500 that made rows with a migration-leftover receipt path undeletable. |
| Pass 6 — rollback unblocked | **Done.** `0002 down` was refusing on a hash collision between two test-fixture rows. Resolved, and the fixture no longer collides. |
| Pass 7 — staging rehearsal COMPLETE | **Done.** `up → verify → down → up` all ran on staging. 30 rows at every stage, no data lost. |
| Pass 8 — SMTP fixed | **Done.** Password reset delivers, and the account-enumeration leak is closed. |
| Pass 9 — phone pass recorded + receipt paths | **Done.** The phone checklist came back clean. `migrate_receipts.py` now re-homes a path left under another owner. |
| Pass 10 — household decision, `--apply`, byte reconciliation | **Done.** The three accounts are ours; the receipt re-homing ran (`legacy_rows: 0`); both re-homed objects are identified; the isolation suite ran clean. |
| Pass 11 — runbook read-through against the tools | **Done.** Every tool-agreeing claim verified against code; four stale-prose fixes; steps 3–4 now self-report the project ref. |
| Pass 12 — live `image_hash` shape, step 3 hardened | **Files done; staging re-run is YOURS.** Production's `image_hash` uniqueness is a *partial unique index*, which step 3's text patterns could not see. Step 3 now reads the catalog. Staging must be rebuilt to the live shape and re-run before cutover. |

## Pass 12 — Production's `image_hash` shape, and the silent no-op step 3 hid

**What the live SQL editor showed changes the answer to "did step 3 do its job?".** Live carries the
uniqueness as two different kinds of object:

- `transactions_dedupe_hash_key` = **constraint** `UNIQUE (dedupe_hash)`;
- `transactions_image_hash_uidx` = **partial unique index**
  `CREATE UNIQUE INDEX ... ON public.transactions USING btree (image_hash) WHERE (image_hash IS NOT NULL)`.

The old step 3a snapshot and 3b/3c loops found these objects by matching `indexdef` **text**, with the pattern
anchored on `(dedupe_hash)` / `(image_hash)`. A partial index's definition *ends* in `WHERE (...)`, so it
matched nothing. Three consequences, all in one file:

1. the snapshot held the dedupe constraint only, so `down` could never have restored the image index;
2. the catch-all loop dropped nothing, so the index **survived** the migration;
3. guard 3c reused the same pattern, so it did not fire — and the migration ends with
   `image_hash` still **globally** unique. Two owners could not hold the same photo, and every later step
   would have looked fine. That is the serious one: it is a silent no-op, not an error.

**Reproduced before fixing.** A local PGlite rehearsal (a real Postgres, outside the repo, Supabase-only bits
shimmed) built production's exact shape and ran the then-current `0002`:

```
=== 1. after up ===
transactions_image_hash_uidx | constraint=- | uniq=true pk=false partial=true
    CREATE UNIQUE INDEX transactions_image_hash_uidx ... (image_hash) WHERE (image_hash IS NOT NULL)   <- survived
transactions_user_image_key  | constraint=transactions_user_image_key | uniq=true ...   <- the old shape
snapshot:
  constraint transactions_dedupe_hash_key: ... UNIQUE (dedupe_hash)                        <- index missing
=== 2. guard 3c with only the PARTIAL image index left ===
  old regex guard flags: []                                                                 <- does not fire
  guard 3c: NO RAISE  <- WRONG: the partial index survived and nothing stopped it
=== 5. per-owner uniqueness after up ===
  cross-owner duplicate image_hash: refused (23505)                                         <- the multi-user break
```

**The staging project independently confirms it.** Its live `public.migration_0002_saved_constraints` holds
**one** row — `constraint transactions_dedupe_hash_key` — because the old step 3a matched the constraint's
`indexdef` and nothing else. So no earlier rehearsal run, on staging or locally, could have seen this: the
index was never in the snapshot, and `00_pre_migration_schema.sql` had never created it in the first place.

**The fix, all in `migrations/0002_multi_user.up.sql` step 3 and 4 and in the `.down.sql`:**

- **3a (snapshot)** reads one row per unique index whose *only* key column is `dedupe_hash` or `image_hash`
  (`pg_index.indkey` + `pg_attribute.attname`, primary keys excluded) — partial or not, whatever its name. A
  constraint-backed index is saved as the **constraint** (`alter table ... add constraint <name> <def>`); a
  loose index is saved as `pg_get_indexdef(...)` **verbatim**, `WHERE` clause included. No text matching.
- **3b (drops)** drops the real names first — including `transactions_image_hash_uidx` — then walks the same
  catalog test and drops by kind: `drop constraint` for a constraint, `drop index if exists` for a loose
  index, because dropping the index behind a constraint fails.
- **3c (guard)** uses the same catalog test and **names the offender** in the raise, so a survivor is never
  anonymous.
- **4 (per-owner)** stays a constraint for `dedupe_hash`, and the image side becomes the **partial unique
  index** `transactions_user_image_uidx on (user_id, image_hash) where image_hash is not null`, mirroring the
  object it replaces. `transactions_user_image_key` — the constraint an earlier revision created — no longer
  exists; `down` still drops both spellings so a database migrated by that earlier revision still rolls back.
- **down step 3a (new)** re-counts what the snapshot restored against the snapshot itself and raises if they
  disagree, so a rollback cannot half-restore quietly.

**Re-ran the whole thing with the fix, on production's shape:** `up` → `verify` → `down` → `up`. The partial
index is snapshotted with its `WHERE` clause, dropped, replaced by the per-owner pair, restored **verbatim**
by the rollback, and the round trip leaves the same objects both times. Guard 3c now raises with the object
named. A cross-owner duplicate `image_hash` is now **accepted** while a same-owner one is refused, and a second
NULL `image_hash` for one owner is accepted. A variant where production's image uniqueness is a *constraint*
was run too, and it also round-trips exactly. **What this does not prove:** it runs on PGlite with shimmed
`auth`/`storage`, so RLS policies are parsed and stored, not enforced.

**The kind is not cosmetic for `down`:** the verify grids now print each restored object's **form** as well as
its definition, so a constraint coming back as an index (or vice versa) is visible rather than silently
"close enough".

**Both verify scripts are now one statement, one grid** (`migrations/staging/verify_after_up.sql`,
`verify_after_down.sql`): 12 rows and 9 rows, each row's expectation written into the row's own `check_name`.
They were executed in the rehearsal, not just written, and each reported exactly the expected value. The
global-unique rows are answered from the catalog for the same reason step 3 is — a text answer would report
"none" while the partial index was still there.

**Staging is rebuilt to the live shape, and that re-run is not done.** `migrations/staging/00_pre_migration_schema.sql`
now also creates `transactions_image_hash_uidx` (it previously created `image_hash` with no uniqueness at all,
which is exactly why the earlier rehearsal passed: the buggy pattern had nothing to miss). Rebuilding staging
and re-running `up → verify → isolation suite → down` is the owner's step, because only the SQL editor can run
the DDL — there is no DB credential or `psql` in this environment. The isolation suite needs the migrated
staging state, so it is re-run after that, not before.

**Read out of staging before recommending that order** (API, read-only, counts only — not DDL): **29 rows, one
owner**, that owner being `STAGING_USER_A_ID`; **14 rows carry a receipt and all 14 sit under A's folder**, none
at the legacy `2026/` path; **no `dedupe_hash` or `image_hash` value is shared by two rows at all**. So
`0002 down` will not hit its cross-owner guard, and the global partial index will create cleanly — the
data-preserving order (`down` → create the index → `up`) is safe on the staging state as it stands. It also
means the `up` must be run with **A's** id: step 2 backfills every ownerless row to the session owner, so any
other id would re-home all 29 rows and break the suite's lookup of A's receipt.

**Neither the seed nor the isolation suite needed a change, and that is a checked statement, not a guess.**
`scripts/staging_seed.py` never names the unique objects: its phase "after" inserts B rows repeating A's
`dedupe_hash` **and** `image_hash` — accepted only if the per-owner shape is right, and the exact case the old
state refused (23505 above) — and then requires a same-owner duplicate to be refused. Both hold under the new
partial index exactly as they did under the old constraint, which the rehearsal re-checked. The 15 isolation
tests assert *behaviour* (409s, RLS, folder isolation) and never the object kind, so they are
shape-independent. The one thing they cannot check is the catalog itself: they run through the API, and
`pg_index` / `pg_constraint` are not exposed there — which is why that check lives in `verify_after_up.sql`.
What they still need is to be **run** against the migrated staging, which is the re-run above.

**Not re-run, and why:** the isolation suite (needs the migrated staging), and the live SQL itself.

## Pass 11 — the runbook read-through, and the four fixes it produced

**The last pre-flight is done: `docs/CUTOVER_RUNBOOK.md` read line by line against the current tools.** Every
claim that had to agree with code was checked, and all agreed: the STOP list (`missing_source` /
`unexpected_format` are the only stops, `shared_object` is a skip that exits 0), every counter name, both
migration refusal messages, the `transactions_user_dedupe_key` / `transactions_user_image_key` names *(the
image name is now `transactions_user_image_uidx`, a partial unique index — see Pass 12)*, the 4
transaction + 3 storage policies, `GET /health`, the `no-store` + per-response CSP nonce on `/`, and the
printed output of `backup_receipts.py`, `audit_live.py` and `verify_after_up.sql`. Four things did not:

1. **The header claimed a guard that two of the three scripts do not have.** "the scripts refuse the live
   project unless `--allow-live` is passed" holds for `migrate_receipts.py` only; `backup_receipts.py` and
   `audit_live.py` take no arguments, follow `.env`, and printed no project ref — so the runbook's own
   mitigation ("check the ref in every console") could not be done from their output, and a wrong `.env`
   would have baselined the wrong project silently, poisoning every later comparison. Fixed on both sides:
   the header sentence is scoped to `migrate_receipts.py`; step 3 gained a numbered pre-check (**3a**) that
   prints the ref from `.env` and carries its own STOP line; step 4's first check is the same ref. And both
   scripts now print their project URL as their **first output line** (`scripts/backup_receipts.py`,
   `scripts/audit_live.py`), so the pre-check is verifiable from the output rather than trusted.
2. **"The custom SMTP path has never sent a successful message."** False unqualified — pass 8 delivered a
   real message on staging and `recover` returned 200 with an empty body. Qualified to **on the live
   project**, which is the only part actually unproven.
3. **The staging three accounts were still written up as intruders** in steps 1 and 6. Pass 10 confirmed they
   are the household's. One clause added in each place; the check itself stays, because live's account list
   is the real question.
4. **"Row counts: 6 → 6 → 6 → 6"** was attributed to a sentence covering both the local Postgres rehearsal
   and staging. Now labelled: **6 → 6 → 6 → 6** on the local Postgres, **30 → 30 → 30 → 30** on staging, and
   **29** today.

**How the new first line was verified without touching live.** `backup_receipts.py` was run with today's
backup folder pre-created, so it printed `project: https://viorpltdkpexswvofeul.supabase.co` and then
stopped at the folder guard: no network, no download, exit 1. The folder was removed afterwards and
`~/Backups` is back to its two entries. `audit_live.py` was run against an unresolvable host to prove the
line prints before any request; its real output against live is still unexercised. Suite: **206 passed,
15 skipped**, unchanged.

The suite's **2 warnings are pre-existing, not from this batch** — `app/main.py:115` uses
`starlette.status.HTTP_422_UNPROCESSABLE_ENTITY`, which Starlette deprecates in favour of
`HTTP_422_UNPROCESSABLE_CONTENT` (that line last changed in `aae36b0`). Noted once here so it is not
re-investigated; left alone, since it is an app change and nothing in this batch asks for one.

**One finding that is not the runbook's, now resolved and corrected in place.** `a2d55e96`, cited twice in
this file as the thing behind staging's 30 → 29 delete, turned out to be **a transaction row id, not a
commit** — which is why it resolves to no git object: it never was one. Both citations now say so, and the
runbook cites it with the same label. Chasing the other id, `b31b4f8f`, produced a real correction: it is a
**different row and a different delete event** — loopback, through the app, a row whose receipt object was
left behind (see Known issue 7, which now carries the log line verbatim). It is not the phone-test delete,
so Known issue 7 keeps its closure rather than upgrading it.

## Pass 10 — the household decision, the receipt re-homing, and the byte reconciliation

**The three accounts are ours (household).** The hold was released and the question is closed; the section
under *Next* carries the full record. Nothing is pending on staging.

**Staging `--apply` ran** — `DRY RUN → APPLY → DRY RUN`: `copied: 2`, `originals_deleted: 2`, then
`already_moved: 14`, `legacy_rows: 0`, exit 0. An independent recursive bucket listing confirms 14 objects
→ 14 with the same two file names, so the move lost nothing.

**Both re-homed objects are now identified individually.** `bytes_copied: 532,627` was 20 bytes more than
the single photo we knew about, so the second object was not a photo:

| Object (now under A) | Bytes | Row | Merchant | What it is |
| --- | --- | --- | --- | --- |
| `824a7d7a….jpg` | 532,607 | `627ff149` | Fresh Choice (Pekan) Pantai Selamat | the real receipt (household) |
| `cb0be583….jpg` | **20** | `a7db563b` | Kedai B Sendiri | the staging **seed** fixture, bytes `b"fake receipt b-own-1"` |

532,607 + 20 = 532,627, so `bytes_copied` reconciles exactly. `cb0be583`'s sha256 is
`cb0be583df89f30297f6d6c7091622db01465253ad65eb25dd8e48268fc4c699`.

**`a7db563b` is not household data, and must not join the household delete list.** It is created by
`scripts/staging_seed.py` (`fake_receipt("b-own-1", 25, "66.60", "Kedai B Sendiri")`) and is one of the
four merchants in the staging suite's `SEEDED_B_MERCHANTS`, which its cleanup deliberately preserves.
Deleting it would empty a seed the suite expects to find. The household delete list therefore stays at
**five rows**, and the arithmetic stays **29 → 24**.

**Apart from that one photo, every object in the staging bucket is a 20–22 byte fixture stub.** Two
consequences worth carrying:

- Any "the photo loads" check on staging exercised the load path against **stub bytes**. The single
  exception is the household scan — the only object uploaded and then fetched back through a signed URL as
  a real image (the phone log shows `GET /transactions/627ff149-…/receipt-url` → `200`).
- **Staging receipt counts are not a data-quality signal.** `14 receipts` means 14 rows carry a
  `receipt_path`; 13 of those point at a 20–22 byte fixture, not at a picture of anything.

**The staging isolation suite ran once more, as the last staging action before the cutover window:**

```
before: rows=29  accounts=5  objects=14  orphan_objects=0
after : rows=29  accounts=5  objects=14  orphan_objects=0
```

**15 passed**, and it returned to 29 with no orphans, as pass 6's cleanup fix promised. This is the only
suite that exercises RLS against a real Supabase project, and RLS is exactly the property the live project
inherits from the same migrations, so it was worth running while staging is still the rehearsal ground.

## Pass 9 — the phone pass, and the last receipt-path case

**The phone checklist came back clean** — sign-in, keyboard behaviour, dark mode, scan, text entry, sign-out
and Back all worked on a real iPhone. That closes the biggest unknown: everything before it had only been
checked in desktop Chrome. Three things remain reasoned about rather than measured on device — whether
`100dvh` shrinks with the keyboard open, `scrollIntoView` inside a fixed scroll container, and focus zoom at
exactly 16px — noted in Known issue 8.

**`migrate_receipts.py` now re-homes a path left under another owner's folder.** A `down`/`up` cycle
reassigns rows without moving the objects back, which leaves an object at `<other-owner>/YYYY/MM/x.jpg`. The
script used to report those as `unexpected_format` and exit 1; it now strips the foreign prefix and moves the
object to `<owner>/YYYY/MM/x.jpg`. Three things pin the behaviour:

- the foreign prefix is **stripped**, so the target is `<owner>/2026/10/x.jpg` and never
  `<owner>/<other-owner>/2026/10/x.jpg` — the naive `new = owner + "/" + old` would have produced the latter;
- a path held by **more than one row** is left alone (`shared_object`) rather than moved out from under the
  other row;
- anything that is not a real owner prefix (a UUID) is still refused (`unexpected_format`) rather than
  guessed at.

This matters on live too: the runbook's rollback path (`0002 down` then `up`) is what creates these rows, and
step 9 told you to **STOP** on `unexpected_format`. That advice would have fired after a perfectly good
rollback. The runbook is updated.

Dry run on staging after the change: `legacy_rows: 2` (was 0), `unexpected_format: 1`. The one remaining
case is my own throwaway row, described under *Next*.

**Acceptance evidence — `unexpected_format: 0`.** After that row was deleted (by explicit id), the dry run
on staging reports:

```
mode: DRY RUN
rows_with_receipt: 14
already_moved: 12
legacy_rows: 2
would_move: 2
exit=0
```

`unexpected_format` is absent, and the exit code is 0. That is the state the cutover step 9 expects before
the real run.

**Staging then ran `--apply`.** Once the household-accounts question closed and the freeze lifted, the
sequence was `DRY RUN → APPLY → DRY RUN`. The apply re-homed both foreign-prefixed objects
(`copied: 2`, `originals_deleted: 2`, exit 0); the final dry run reports `already_moved: 14`,
`legacy_rows: 0`, exit 0. An independent recursive bucket listing before and after shows **14 objects →
14**, the same two file names, so nothing was lost in the move.

**Staging row count: 29, after the `a2d55e96` delete.** `a2d55e96` is a **transaction row id, not a commit** —
the throwaway row (merchant `Throwaway Fix Check`, RM 1.00, dated 2026-10-30, `receipt_path`
`someone-else/2026/10/x.jpg`) created by a probe script whose response parse failed after the insert had
already succeeded, and deleted by explicit id. The delete took the table 30 → 29, so staging reads 29
again — this time for a known reason, not the Known issue 7 mystery. Because it was run by explicit id it
never reached the app, which is why it has no server log line. The count had already drifted 29 → 30
through ordinary phone use before that, so drift-with-use is now demonstrated twice. Live counts are
baselined fresh inside the cutover window and are never compared against this number, so the staging count
is not an expectation for live.

**The exit codes are pinned by tests now, not just by the code that happens to be there.** The runbook's
STOP reads the exit code, so `tests/test_migrate_receipts.py` gained three that hold it in place: a shared
object prints `skipped (one object, two rows) — not an error` and exits **0**; an `unexpected_format` exits
**1**; a guard refusal exits **2** without building a client. Suite: **206 passed, 15 skipped** (was 203).

## Pass 8 — SMTP is fixed

Custom SMTP is configured on staging (`smtp.gmail.com:465`, sender `hanennkam@gmail.com`, name **Duits**),
and a real email arrived. Verified at the API:

| | Before | After |
| --- | --- | --- |
| `POST /auth/v1/recover`, existing account | **400** `Email address is invalid` | **200**, empty body |
| `POST /auth/v1/recover`, unknown address | 200 | **200**, empty body |
| `POST /auth/v1/signup` | 422 `signup_disabled` | unchanged — still refused |

**The account-enumeration leak closed as a side effect.** Before, the two `recover` calls differed by status
code (400 for a known address, 200 for an unknown one), which told an attacker which addresses exist. Now
both answer `200` with no body, which is the correct anti-enumeration behaviour. So Known issue 1 is
resolved on both counts.

### Two caveats to carry into cutover

1. **Supabase flags the provider**: *"It looks like the SMTP provider you entered is designed for sending
   personal rather than transactional email messages. Email deliverability may be impacted."* Gmail has
   per-day sending limits (500 for a personal account, 2000 for Workspace) and can throttle or suspend an
   account it sees as bulk-sending. For one user inviting one or two people that is fine; if the plan is to
   invite a household or a group at once, expect limits.
2. **Minimum interval per user is 60 seconds.** Two emails to the same address inside a minute — a reset
   followed by an invite, say — have the second silently dropped. Wait a minute between them.

## Pass 7 — the staging rehearsal is complete

`0002 down` now runs (the guard cleared), and `set_config(app.owner_id, A)` + `0002 up` followed it to
`commit;` with no error. That is the full `up → verify → down → up` sequence — the same one the live run
uses.

Read back through the API afterwards:

| Check | Result |
| --- | --- |
| `user_id` column | present |
| Tables exposed | `transactions`, **`api_tokens`**, **`migration_0002_saved_constraints`** |
| **Total rows** | **30** — unchanged, nothing lost |
| **Rows without an owner** | **0** |
| Owner distribution | 30, all owner A (the backfill point) |
| `dedupe_hash` shared across owners | **0** |
| `image_hash` shared across owners | **0** |
| Rows with a receipt_path | 15 — 12 match their owner, **3 mismatches** |

Notes on that table:

- **`up` succeeding is itself proof that `down` ran**: step 4 of `up` adds `transactions_user_dedupe_key`,
  which would fail with a duplicate-object error if the constraints had still been there.
- **The 3 receipt-path mismatches** are the expected residue of a `down`/`up` cycle — the objects keep the
  owner prefix they had while the rows get reassigned. On live this does not arise, because the object move
  runs *after* the backfill. If any survive there, `migrate_receipts.py` reports them as
  `unexpected_format`, and since pass 5 the app answers 404 for the photo and still deletes the row.
- Staging suite **15 passed** and unit suite **198 passed** in this state.

## Pass 6 — the rollback guard fired, and why

`0002 down` refused with `the same dedupe_hash exists for two owners; resolve before rolling back`. **That
is the guard working**, and it was right to stop: the global `UNIQUE (dedupe_hash)` cannot be restored while
two owners hold the same key.

The collision was entirely test fixture data — none of your iPhone rows involved:

| | Owner | Created | id |
| --- | --- | --- | --- |
| stale copy | A (after the backfill) | 09:02:13 | `eb25042c` |
| fixture row | B | 14:37:25 | `a7db563b` |

Both were the same fake receipt (`Kedai B Sendiri`, RM 66.60, 2026-10-25), and **both came from
`scripts/staging_seed.py`** — `fake_receipt("b-own-1", 25, "66.60", "Kedai B Sendiri")`. `eb25042c` was
reassigned to A by the `down`/`up` backfill; `a7db563b` was not. *(Pass 10 corrected this line: it used to
say `a7db563b` came from the self-healing fixture, which the code does not support — that fixture's identity
is `Kedai B <token>`, so a bare `Kedai B Sendiri` carrying the `b-own-1` photo is the seed.)* Resolved as you
approved: **`eb25042c` and its own receipt object were deleted** (they were not shared — each row had its
own object).

Three fixes follow from it:

1. **The fixture no longer collides.** Its identity (`Kedai B <token>`, and the photo) is unique per run, so
   it can never share a hash with a copy a previous `down`/`up` left under another owner. The tests read
   those values instead of hardcoding them. `cleanup_test_rows` removes it at the end of the module.
2. **Object cleanup actually works now.** It was sending `Content-Type: application/json` with an empty
   body, which Supabase Storage answers **400** to — so every test object was silently left behind. Without
   the header it deletes correctly. Verified: **0 orphan objects** after a full suite run.
3. Confirmed clean before handing back: 30 rows, **0** `dedupe_hash` or `image_hash` values shared across
   owners, 0 orphan objects.

## Current branch + last commit

- Branch: `multi-user`, tracking `origin/multi-user`, pushed.
- `main` is untouched and was **not** pushed.
- `pytest`: **198 passed, 15 skipped**. Staging suite: **15 passed**.

## Pass 5 — what changed

**You checked `verify_after_up.sql` sections B–F** against staging, so the catalog side of the migration is
confirmed: `user_id` NOT NULL, the two per-owner unique keys present with no global `UNIQUE (dedupe_hash)`,
RLS on, the expected policy counts, and the rollback snapshot in place.

**Fixed: rows with an unreachable `receipt_path` were crashing.** Proven on staging before touching anything:

| | Before | After |
| --- | --- | --- |
| `GET /transactions/{id}/receipt-url` | **500** `Internal Server Error` | **404** "This transaction has no receipt image." |
| `DELETE /transactions/{id}` | **500**, and the row survived | **204**, the row goes |
| A well-formed row | 200, signed URL | unchanged |

Root cause: `db._owned_path()` correctly refuses a path outside the owner's folder, but its `ValueError`
escaped to the route and became a 500. Since `delete_receipt` runs before `delete_transaction`, the row
could not be deleted at all.

Why it matters beyond staging: the cutover runbook's **rollback path** (`0002 down` then `up`) reassigns
owners without moving the objects back, which is exactly how these rows are produced. So the runbook's own
recovery procedure could have left live rows that neither open nor delete.

The guard itself is unchanged — a foreign object is still never signed, moved or deleted. What changed is
that a path the owner cannot reach now reads as "no receipt", and the row is still deletable with a logged
warning that the object was left in place.

Added tests: `404 not 500` for a foreign path, `DELETE` still works and never touches a foreign object, and
the `owned_receipt_path()` rule (own folder, null, empty, other owner's folder, legacy un-prefixed form).

**Also made the staging isolation suite survive a rollback cycle.** Your `down`/`up` run broke it: the
backfill gives every row to one owner, so B owned nothing and three tests failed on missing fixture data
rather than on isolation. `b_own_row` now re-creates B's row when it is gone, and the fixtures that depend
on it are ordered accordingly. Expect the suite to stay green through the `down` → `up` runs still to come.

## Pass 3 — what changed

| Item | Result |
| --- | --- |
| "Not signed in" after an invite | **Fixed.** The address now comes from the token's own claims (`emailFromToken`), with a `/auth/v1/user` call as the fallback. Pinned by a page test. |
| `PORT` | **Fixed.** `render.yaml` pins `PORT=10000`; the Dockerfile default stays `8000` and the start command already honours `$PORT`. Verified locally: `PORT=10000` binds 10000, `/health` 200, nothing on 8000. |
| Schema drift | **Fixed.** `schema.sql` now carries `image_hash`, so a fresh database matches production (all 15 columns). |
| Migration rehearsal | **Done on a real Postgres** with the exact files. Row counts **6 → 6 → 6 → 6** across up → verify → down → up; no rows lost. `0002` **refuses without `app.owner_id`**; the rollback **refuses** while two owners share a hash; per-owner uniqueness proven both ways. |
| `migrate_receipts.py` dry run | **`legacy_rows: 0`** as required. One leftover rehearsal row reports `unexpected_format` (its `receipt_path` prefix is not its owner) and is correctly left alone. |
| Cutover runbook | **`docs/CUTOVER_RUNBOOK.md`** — 14 numbered steps, each with the command or click, the expected result, a STOP line and a rollback. Marked MINE (dashboard) or YOURS (command). |

## Staging URL (iPhone, same Wi-Fi)

```
http://192.168.1.6:8765/
```

If the Mac's address has changed, run `ipconfig getifaddr en0`, or restart the server and read the URL
it prints: `./.venv/bin/python scripts/serve_staging.py`. Stop it with Ctrl-C (or
`lsof -nP -iTCP:8765 -sTCP:LISTEN -t | xargs kill`). This is the **staging** project only.

Test accounts: `duits-staging-a@example.com` and `duits-staging-b@example.com`. The password is
`STAGING_TEST_PASSWORD` in `.env.staging`. A owns 21 rows, B owns 4.

---

## 1. What changed

The polish itself is commit `f33651a`. No files changed in this verification session.

| File | Change |
| --- | --- |
| `app/static/index.html` | The auth screens: 45% centred column, `min-height: 100dvh`, `safe center`, 340px column, and the full size set (logo 72/16, title 24/700, labels 12, inputs 48/12/16px, Sign in 48/24/17px, Forgot 15px, note 13px clamped to 2 lines). |
| `tests/test_page_auth.py` | Pins for the layout, every size and gap, the keyboard behaviour and the kept iOS rules. |
| `README.md` | The sign-in paragraph rewritten for the new layout and its scrolling behaviour. |

## 2. What passed / failed in the safety checks

### Passed

- **`/health`** → 200.
- **Sign in** with a correct password → 200, access token issued.
- **Wrong password** → 400 `Invalid login credentials`. No session created, button re-enabled, user stays
  on the sign-in screen. The same message is returned for an unknown address, so sign-in does not leak
  which accounts exist.
- **Set password** → `PUT /auth/v1/user` returns 200; the new password then signs in (200) and the old one
  is rejected (400); restored afterwards. The screen shows the confirm field, locks the email (the link
  already proved identity) and **clears the token out of the URL**.
- **Secrets.** 77 tracked files scanned against the real values of `SUPABASE_SERVICE_KEY`,
  `ANTHROPIC_API_KEY`, `API_KEY`, `SUPABASE_PUBLISHABLE_KEY` and `STAGING_TEST_PASSWORD`: **no hits**.
  None of them appear in `index.html`. `.env` and `.env.staging` are untracked and gitignored.
  The publishable key is injected at serve time, never stored in the page source.
- **RLS and isolation** — 15/15 staging tests with two real accounts: cross-user list/read/patch/delete
  and receipt URLs all answer 404, dedupe is per owner, creates stamp the caller, and RLS is enforced
  through PostgREST **and** Storage (B cannot read A's receipt object).
- **No sign-up in the UI.** The page has no registration screen and never calls `/auth/v1/signup`.
- **`redirect_to` on recovery** is `window.location.origin + "/"` (commit `59a8018`), pinned by two page
  tests. It was previously built from `pathname`, which would break the allow-list if the page were opened
  as `/index.html`.
- **Sign-up is now refused** (staging). `POST /auth/v1/signup` → **HTTP 422**, message
  **`Signups not allowed for this instance`**, `error_code: signup_disabled`, for both a weak and a valid
  password. No account is created. `disable_signup` now reports `true`.
- **Invite flow works end to end** (staging, real link from `generate_link`):
  - the link lands on the app's **Set a new password** screen;
  - the confirm field is shown and the email field is locked (the link proved identity);
  - **the token is cleared from the URL** immediately (`#...` is gone, address bar is `/`);
  - after saving, the new user is signed in and **Home is empty**: 0 rows, `RM 0.00`,
    "Nothing recorded this month yet.", and no row from A or B anywhere on the page.
  - Confirmed in the database too: the new account owns **0** rows.

### Failed / gaps

1. **Forgot password did not deliver.** Supabase answered `400 Email address "…" is invalid` for both
   existing test accounts, while unknown addresses returned `200`. Two consequences:
   - **Reset emails never arrived**, so the "Forgot password" flow could not complete.
   - **Account enumeration at the Supabase level**: the status code differed for a known and an unknown
     address. Our UI hides this behind one message, but the API itself leaked it.
   The cause was the project's email provider rejecting `example.com` recipients. A Supabase setting, not
   app code. — **RESOLVED in pass 8** (custom SMTP). Both calls now answer `200` with no body.
2. **Settings showed "Not signed in" after an invite sign-in.** — **Fixed in pass 3 and verified end to
   end.** The session now carries the address read from the token, and Settings shows it. See the
   verification table below.
3. **Three unexpected accounts exist on staging** — `suhaib@gmail.com`, `adeeb@gmail.com`,
   `madsu04@gmail.com` — created while sign-up was open (10:14–13:15 UTC on 2026-10-16). They own 5 rows
   between them (4 manual, 1 receipt scan) and the evidence read as **real spending**, so they were held
   rather than deleted. **Confirmed ours (household) on 2026-10-17**; kept, with deletion scheduled by the
   owner. See Known issue 4 and *Next* for the attribution record.

Resolves the earlier "Sign-up is not invite-only" gap (item 2 of the previous pass).

---

## 3. Phone test checklist

Open `http://192.168.1.6:8765/` in Safari.

**Sign-in screen**
- [ ] Splash shows, then hands over to the sign-in screen.
- [ ] The block sits around the middle, slightly above centre, with the logo and title clear of the status bar.
- [ ] Tap Email: the field scrolls to the middle of the visible area after the keyboard opens. No page jump.
- [ ] The keyboard's return key shows **Next** on Email and **Go** on Password.
- [ ] Tap Password: it scrolls into view. The title stays reachable (scroll up to see it).
- [ ] Enter a wrong password: an error appears, the button works again, no data is shown.
- [ ] Sign in correctly: you land on Home with your own rows.
- [ ] Fold the keyboard away (blur): the screen scrolls back to the top and the logo and title return.
- [ ] Dark mode: switch in iOS Settings → Display, reload. The screen follows, no white flash on launch.
- [ ] "Forgot password?" opens the Reset view; "Back to sign in" returns.

**After sign-in**
- [ ] Home shows only your rows. Switch month with the pill.
- [ ] Transactions: search, filter, tap a row to open detail, edit it, delete it.
- [ ] Insights: Week / Month, the donut and the highlights.
- [ ] Settings shows your email and **Sign out**.
- [ ] Sign out: the login screen returns and no rows are visible behind it. Press Back: still no data.

**Transactions**
- [ ] Add a text transaction from the `+` sheet (Smart Entry) and confirm the row appears.
- [ ] Scan a receipt (camera or photo roll) and confirm the toast and the row.
- [ ] Open a row with a receipt and confirm the photo loads.
  *(Pass 10: this check used `627ff149`, the only real photo in staging. The other thirteen objects are
  20–22 byte fixture stubs, so this is the one row on which the load path was exercised with real bytes —
  see Pass 10.)*

**Keyboard / layout**
- [ ] With the keyboard open on the sign-in screen, everything is reachable by scrolling and nothing is
      clipped under the status bar.
- [ ] No zoom when focusing any field (16px floor).
- [ ] No sideways scroll anywhere.

---

## 4. Cutover checklist (going live)

**The full linear runbook is `docs/CUTOVER_RUNBOOK.md`** — 14 steps, each with the exact command or
dashboard click, the expected result, a STOP line and a rollback, marked MINE (you, dashboard) or
YOURS (assistant, command). Read that instead of this summary.

**Before anything is written to live.** Nothing below has been run. `docs/migration-runbook.md` has the
full detail; this is the summary.

**A. Configuration (Supabase dashboard, live project `viorpltdkpexswvofeul`)**
- [ ] **Close sign-up**: Authentication → Providers → Email → "Allow new users to sign up" = off. Then
      verify `POST /auth/v1/signup` is refused. **Done and verified on staging** (422
      `Signups not allowed for this instance`); repeat the same check on the live project.
- [ ] **Fix the email sender** so invite and reset links actually send, and confirm a reset link arrives.
- [ ] Add the live URL to **Redirect URLs** (and the LAN URL if you test from a phone):
      `https://duits-money-tracking.onrender.com/`.
- [ ] Verify the model IDs in `config.py` / `.env.example` against Anthropic's docs.

**B. Environment variables (Render dashboard)**
- [ ] `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `ANTHROPIC_API_KEY`, `API_KEY`
- [ ] `ENVIRONMENT=production`
- [ ] `ALLOW_LEGACY_API_KEY=true` and `LEGACY_USER_ID=<your auth.users id>` — only while the iOS Shortcut
      still uses the shared key. Remove both once personal access tokens exist.
- [ ] Check `PORT` in the dashboard. The `Dockerfile` defaults to `8000`; Render's default is `10000`.
      **Do not change the Dockerfile default** — set `PORT` in the dashboard instead.

**C. Database (order matters)**
- [ ] Take a fresh backup: dashboard backup **and** `pg_dump --data-only --table=public.transactions`.
- [ ] Back up the receipts bucket: `./.venv/bin/python scripts/backup_receipts.py` (read-only; refuses to
      overwrite an existing folder).
- [ ] Record the baseline counts with `scripts/audit_live.py` (read-only).
- [ ] Run `migrations/0002_multi_user.up.sql` in the live SQL editor, preceded by
      `select set_config('app.owner_id', '<your auth.users id>', false);` **in the same run**.
      - This is the step that assigns **all existing rows to your user id** (the backfill). That is the
        "existing data -> my user" step. Review the row count before and after.
- [ ] Verify with `migrations/staging/verify_after_up.sql` (read-only). Expect: rows without owner = 0,
      per-owner unique constraints, RLS on, 4 transaction policies, 3 storage policies.
- [ ] Move the receipt objects: `scripts/migrate_receipts.py --env-file .env --project-ref
      viorpltdkpexswvofeul --allow-live` (dry run first, then `--apply`, then dry run again to confirm
      `legacy_rows: 0`).

**D. Deploy**
- [ ] Merge `multi-user` to `main` when you are ready (Render auto-deploys from `main`).
- [ ] Smoke test: `/health` 200, `/` 200 with `no-store`, sign in on the phone, one scan, one edit.
- [ ] Re-check the **Build** row in Settings matches the deployed commit.
- [ ] Keep `migrations/0002_saved_constraints` until the rollback window is closed, then drop it.

**E. Rollback plan**
- [ ] Code: redeploy the previous commit on `main`. The old code never reads `user_id`, so it works with
      the restored schema.
- [ ] Schema: run `migrations/0002_multi_user.down.sql`. It drops the policies, `api_tokens` and the new
      indexes, restores the **original** global unique constraints from the snapshot, and drops `user_id`.
      Rows are kept. It **refuses to run** if two owners share a hash, and changes nothing in that case.
- [ ] Receipts do not need to be moved back: each row's `receipt_path` is the source of truth.
- [ ] Re-running the up migration after a rollback is supported and was rehearsed.

---

## 5. Known issues

1. **Forgot-password emails do not send** for the staging accounts (Supabase: `400 Email address is
   invalid`). The UI is correct; the delivery is not. Also leaks account existence by status code.
   — **RESOLVED in pass 8** by configuring custom SMTP. Both `recover` calls now answer `200` with no
   body, so the enumeration leak went with it. See Pass 8 for the two caveats to carry to cutover.
2. **Sign-up is closed on staging** (`disable_signup: true`, `/auth/v1/signup` → 422 `signup_disabled`).
   It was open earlier today, and three accounts were created through it — later confirmed as household
   (Known issue 4). **The same setting must still be turned off on the live project** before cutover — see
   the checklist.
3. **Settings shows "Not signed in"** after signing in through an invite link. — **FIXED in pass 3 and
   verified end to end** (the address is read from the token; see the verification table below).
4. **Three accounts on staging — OURS, KEPT** (`suhaib@gmail.com`, `adeeb@gmail.com`, `madsu04@gmail.com`),
   owning 5 rows. Confirmed as household on 2026-10-17; deletion is scheduled by the owner for later. The
   rows read as real spending and the scan came from the LAN, which is what made the hold worth taking. My
   two throwaway accounts `duits-invite-test@example.com` and `duits-invite-verify@example.com` are deleted
   (0 rows each, accounts 7 → 5). See *Next* for the attribution record.
5. **`migrate_receipts.py` and the leftover receipt paths.** A `down`/`up` cycle leaves objects under the
   old owner's folder. **Fixed in pass 9**: the script re-homes them (foreign prefix stripped) instead of
   reporting `unexpected_format`, so the runbook's rollback path no longer trips its own STOP condition.
   Two such rows are handled; one `unexpected_format` case remains and it is my own throwaway row — see
   *Next*.
6. **The live run has not been done.** The full sequence is now proven three times over: locally on a real
   Postgres (6 rows through up/verify/down/up), and on staging end to end (30 rows through
   `up → verify → down → up`, with `verify` B–F checked). What remains is the same sequence against **live**,
   which is `docs/CUTOVER_RUNBOOK.md` step 7 and needs the SQL editor.

7. **The 29-vs-30 row count on staging — CLOSED.** Could not be reconciled at the time, and this is the
   record of why:
   - **No row-level artefact exists.** The step-2 backup was `scripts/backup_receipts.py`, which backs up
     the **live** bucket's objects, not staging rows. `pg_dump` was never run against staging — it needs a
     connection string that only you hold.
   - **The server access logs do not cover the window.** Across every run they cover there is exactly one
     `DELETE /transactions/…`, and it is **not a phone request**. The line, verbatim:

     ```
     INFO:     127.0.0.1:62235 - "GET /transactions/b31b4f8f-7901-4e94-a9b0-8d16c2280457/receipt-url HTTP/1.1" 404 Not Found
     Leaving a receipt object in place: its path is outside the owner's folder
     INFO:     127.0.0.1:62235 - "DELETE /transactions/b31b4f8f-7901-4e94-a9b0-8d16c2280457 HTTP/1.1" 204 No Content
     ```

     Source is `127.0.0.1` — loopback, the Mac — where the iPhone's own traffic in the same log reads
     `192.168.1.4`. So this is **not** the phone-test delete, and the closure below is not upgraded to
     "explained — phone delete". What it removed: the row `b31b4f8f-…`, through the app, immediately after a
     `receipt-url` GET for that same row from the same local port returned `404` — and the app's line between
     them says the receipt object was **left in place** because its path sits outside the owner's folder. So
     the row had an unreachable receipt and its object was orphaned: pass 5's shape (row deletes, object
     untouched). uvicorn does not timestamp access lines, so it cannot be dated; the only anchor is that it
     is the first request logged by that server process. The server has been restarted several times, so
     earlier logs are gone. (The export's own log scan missed this line by construction — it filtered to
     phone writes, `192.168.1.4` only — and the shell-directory copy of that process's log is now gone too,
     so the export copy under `~/Backups/duits-staging-2026-10-16/logs/` is the only surviving one.)
   - Row counts move continuously from phone testing and from test runs creating and deleting rows, so the
     delta is inside normal noise.
   - The migration is excluded: it provably does not delete rows (6 → 6 → 6 → 6 locally, and 30 → 30
     through `up → verify → down → up` on staging).

   **Closed as unexplained-and-accepted, and now permanently so.** The count sits at **29 because of the
   deliberate delete of `a2d55e96`** — a **transaction row id, not a commit** — written down in Pass 9, so the
   number will not be re-opened as a fresh discrepancy. The two ids in this file are **two different rows and
   two different delete events, not two ids for one delete**: `a2d55e96` was deleted by explicit id and never
   reached the app, so it has no log line; `b31b4f8f` was deleted *through* the app, from loopback, and is
   the one logged line above. What stays unresolved about that second one is only which pass it belongs to
   and what the row held — the log line does not say, and no other artefact names it. The drift is real but
   harmless: live counts are baselined fresh at cutover from `pg_dump` and `scripts/audit_live.py` (runbook
   steps 2–4), taken together in the same window, and staging's count is never compared against live.
8. **Verified on a real iPhone** in the phone pass: sign-in, keyboard behaviour, dark mode, scan, text
   entry, sign-out and Back all worked. What that pass cannot settle remains unverified: whether `100dvh`
   shrinks when the keyboard opens, `scrollIntoView` inside a fixed scroll container, and focus zoom at
   exactly 16px — these are reasoned about, not measured on device.
9. **The sign-in form is taller than the keyboard strip** on a small phone (456px of content against 300px
   at 375×667), so it scrolls rather than fitting in one glance. Every control is reachable; confirmed
   acceptable on the phone.

**Resolved since the earlier passes** (kept so they are not re-opened): `image_hash` is now in
`schema.sql`; `PORT` is pinned to `10000` by `render.yaml`; the Build stamp is injected per request and
needs no manual bump; forgot-password delivers and the enumeration leak is closed (pass 8).

## Next

Staging was complete, then Pass 12 reopened one step of it: production's `image_hash` uniqueness turned out to
be a **partial unique index**, which the old step 3 could not see, so the migration that was rehearsed is not
the migration that will run. The **files are fixed**; the **staging re-run is yours**, because only the SQL
editor can run DDL from here. What is left is live-side, and yours:

1. **Rebuild staging to the live shape and re-run the rehearsal** (Pass 12). In the staging SQL editor, in
   this order:

   ```sql
   -- 1. Take staging back to the pre-migration shape. Data-preserving. Refuses if two owners share a hash.
   --    (paste migrations/0002_multi_user.down.sql)

   -- 2. Give it production's shape: the partial unique index the rebuild has to exercise.
   create unique index if not exists transactions_image_hash_uidx
     on public.transactions (image_hash) where image_hash is not null;

   -- 3. The migration under test. One run. Use A's id (STAGING_USER_A_ID): the `up` backfills EVERY row
   --    that has no owner to this id, and staging's 29 rows are all A's today. Any other id silently
   --    re-homes the lot, and `a_receipt_row` in the isolation suite looks rows up by A.
   select set_config('app.owner_id', '<your auth.users id>', false);
   --    (paste migrations/0002_multi_user.up.sql)

   -- 4. One statement, one grid. Every row must match its own expectation.
   --    (paste migrations/staging/verify_after_up.sql)
   ```

   Step 1 refusing on a cross-owner duplicate and step 2 refusing on the same duplicate are **the same
   condition** (`down`'s guard covers non-null `image_hash`), so if step 1 passes, step 2 will. Then **tell
   me** and I will run the isolation suite against the migrated staging. Then `0002 down` +
   `verify_after_down.sql`, which must show the `transactions_dedupe_hash_key` **constraint** and the
   `transactions_image_hash_uidx` **partial index** back verbatim. The rehearsal is data-preserving, so
   whatever staging holds before the `up` must still be there after the `down`; take the count once at the
   start rather than trusting a number written here.
2. **Live SMTP.** Per-project: staging has them, live does not. Copy `smtp.gmail.com`, 465, sender
   `hanennkam@gmail.com`, name **Duits** into the live project's Authentication → Emails → SMTP Settings,
   then **send one real test message and confirm it arrives** — a settings page that saves cleanly proves
   nothing about port, TLS or the credentials. If a reset and an invite go to the same address, leave a
   minute between them or the second is silently dropped.
3. **Close sign-up on live**, and do it **before** the cutover window opens, not during it. Verify
   `POST /auth/v1/signup` answers 422 `signup_disabled`.
4. Then cutover (`docs/CUTOVER_RUNBOOK.md`). The runbook was read through against the tools in Pass 11 and is
   trusted: every claim that had to agree with code does, the four stale-prose fixes it produced are in, and
   Pass 12 updated its step 7/8 expectations to the real live shape.

**Deferred by choice, not blocking:** deleting the household rows, whenever you want — and the three
accounts too, if you decide they go. Staging's `--apply` has already run, so an app delete now takes each
row and its object together — no orphans. See the section below. When it happens, **update the recorded
count in the same breath** — rows **29 → 24** (settled), and accounts **5 → 2 only if the accounts are
deleted as well** (that half is still the owner's call) — so a stale number cannot seed the next mystery the
way the old 29-vs-30 did. The `Kedai B Sendiri` seed row is *not* on that list (see Pass 10).

### The three non-ours accounts: OURS, KEPT — deletion scheduled by the owner

**Decision landed 2026-10-17: they are ours (household).** The rows and the three accounts stay. Deletion
is scheduled by the owner for a later time of their choosing; nothing here is pending, and this closes the
question so it is not re-litigated at cutover. The evidence below is why it was held — it never needed to
identify anyone, only to warn that the rows read as real spending.

**The `--apply` gate is RELEASED, and the release has been executed: staging `DRY RUN → APPLY → DRY RUN`.**
The apply re-homed the two foreign-prefixed objects (`copied: 2`, `originals_deleted: 2`, exit 0) and the
final dry run reports `already_moved: 14`, `legacy_rows: 0`, exit 0. The bucket went 14 objects → 14, the
same two file names, no net loss.

**Recommended order for the later delete, and why it matters:** staging `--apply` first, rows second. The
Fresh Choice row is owned by A but its object sat at `47ac06a8-…/2026/10/824a7d7a….jpg`; deleting the row
first would make `owned_receipt_path()` refuse that foreign path. The row would still delete — pass 5
behaviour, 404 for the photo, row gone — but the object would be left behind as an orphan needing separate
cleanup. With `--apply` first the object sits at `<owner>/2026/10/…` and matches its row, so an app delete
takes both together: no orphans, no follow-up. Tidiness rather than safety, since the bytes are in the
export either way — and it has now been done, so the tidy path is the one left.

The evidence that made this worth holding — the rows are not mine (mine are `duits-staging-a/b@example.com`):

- **The rows read as real spending**, not probe junk: four manual entries (RM 550.00, 46.00, 23.00, 10.00)
  and a scanned receipt from `Fresh Choice (Pekan) Pantai Selamat` dated 2026-10-11.
- **The scan came from your own LAN.** The server log shows `POST /transactions/scan` → `201 Created` from
  `192.168.1.4`, then `GET /transactions/627ff149-…/receipt-url` for that exact row.

**The attribution survived the backfill, and for one row it is hard.** Objects are stored at
`<uploader-user-id>/YYYY/MM/<file>`, and `0002`'s backfill rewrote `user_id` without touching
`receipt_path`. The scanned row's path is still `47ac06a8-…/2026/10/824a7d7a…jpg`, and `47ac06a8-…` is
**`adeeb@gmail.com`'s user id** — written when the object was uploaded, before any reassignment. So that
row is attributed by data, not by recollection. The four manual rows have no object, so their link is the
pre-backfill pass log (suhaib's four) plus the timeline:

| UTC, 2026-10-16 | |
| --- | --- |
| 10:14:33 | `suhaib@gmail.com` created |
| 10:14:53 – 10:15:07 | the four manual rows (RM 550 / 46 / 23 / 10) |
| 10:15:20 | `adeeb@gmail.com` created |
| 10:23:51 | the scanned receipt, from `192.168.1.4` |
| 13:15:57 | `madsu04@gmail.com` created (no rows) |

**Exported before anything was touched.** The five rows (every column, timestamps included), the three
accounts, the whole account list at export time, the receipt object's bytes, and every surviving
phone-origin server log line are in:

```
~/Backups/duits-staging-2026-10-16/
├── open-signup-attribution.json      accounts, rows, objects, log lines, timeline
├── deleted-throwaway-accounts.json   the two of mine, removed below
├── objects/627ff149-….jpg            532,607 bytes, sha256 recorded in the JSON
└── logs/                             four shell logs, all phone-origin request lines
```

It is outside the repo on purpose: it holds a real receipt photo and real transaction amounts. Now that
the accounts are confirmed ours, it is an **archive, not load-bearing** — nothing in it is needed to
decide or verify anything further.

**My two throwaway accounts are deleted** — `duits-invite-test@example.com` and
`duits-invite-verify@example.com`, by explicit id, each asserted to hold **0** rows first. Accounts went
**7 → 5**; the row count stayed **29**.

**The not-ours branch was not taken, and is closed.** The inventory work it would have needed was done
regardless and sits in the export: the account list plus the rows are the complete inventory the data
shows, over the window `10:14:33`–`13:15:57` UTC (first and last account created).

## Staging migration rehearsal — run, with results

Ran on staging (`down` → `set_config(app.owner_id, A)` + `up` → `verify_after_up.sql`). Read back through
the API afterwards:

| Check | Result |
| --- | --- |
| `user_id` column present | yes (all 15 columns, `image_hash` included) |
| **Total rows** | **29** — see the note below |
| **Rows without an owner** | **0** ✓ |
| Owner distribution | 29 rows, owner A (the backfill point) |
| Hashes shared across owners | 0 |
| Rows with a receipt_path | 14 (12 prefixed with their owner, **2 mismatches**) |
| Receipt objects in the bucket | 15 |

The critical invariant holds: **no row is without an owner**, and the backfill assigned everything to A as
designed. The rollback guard would have refused `down` had two owners shared a hash, so that path is clear.

**Why 29 and not 30.** My last count was 30, taken before the staging test suite ran and before continued
phone testing. The migration does **not** delete rows — that is proven locally (6 → 6 → 6 → 6 across
up/verify/down/up). So the missing row is not the migration's doing: most likely a delete from the phone
(the log shows live use at 192.168.1.4) or test cleanup. If you want certainty, compare against the step-2
`pg_dump` / `backup_receipts.py` artefacts.

**The 2 receipt-path mismatches** are the expected consequence of a `down`/`up` cycle: the objects keep the
old owner-prefixed paths while the rows are reassigned to A. Not a live-cutover problem, where the move runs
after the backfill and paths and owners agree.

### `verify_after_up.sql` sections B–F — CHECKED

Checked on staging. The catalog matches expectations: `user_id` NOT NULL, per-owner unique keys in place
with no global `UNIQUE (dedupe_hash)`, RLS on, the expected policy counts, and the rollback snapshot
present. This closes the migration verification on staging.

### Pass 3 verification — the invite address fix, re-run end to end

The "Not signed in" fix was written and pinned by a static test in pass 3 but never exercised in a real
invite flow. Re-run on staging with a fresh invite link:

| Check | Result |
| --- | --- |
| Session after following the invite link | `duits-invite-verify@example.com` (was empty) |
| Token cleared from the URL | yes |
| **Settings → Account row** | **`duits-invite-verify@example.com`** (was "Not signed in") |
| After saving the password | signed in, Home empty (`RM 0.00`, 0 rows) |

So the fix holds on the path it was written for.
