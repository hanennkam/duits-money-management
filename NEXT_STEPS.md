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

**Staging row count: 29, post-`a2d55e96` delete.** The delete took the table 30 → 29, so staging reads 29
again — this time for a known reason, not the Known issue 7 mystery. The count had already drifted 29 → 30
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
   - **The server access logs do not cover the window.** They record exactly one
     `DELETE /transactions/…` across every run they cover, and it is my own throwaway `b31b4f8f`. The
     server has been restarted several times, so earlier logs are gone.
   - Row counts move continuously from phone testing and from test runs creating and deleting rows, so the
     delta is inside normal noise.
   - The migration is excluded: it provably does not delete rows (6 → 6 → 6 → 6 locally, and 30 → 30
     through `up → verify → down → up` on staging).

   **Closed as unexplained-and-accepted, and now permanently so.** The count sits at **29 because of the
   deliberate `a2d55e96` delete**, written down in Pass 9, so the number will not be re-opened as a fresh
   discrepancy. The drift is real but harmless: live counts are baselined fresh at cutover from `pg_dump`
   and `scripts/audit_live.py` (runbook steps 2–4), taken together in the same window, and staging's count
   is never compared against live.
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

Staging is complete: the migration rehearsal is done, the receipt re-homing has been applied
(`legacy_rows: 0`), SMTP delivers, the phone pass came back clean, and the household-accounts question is
closed. What is left is live-side, and yours:

1. **Live SMTP.** Per-project: staging has them, live does not. Copy `smtp.gmail.com`, 465, sender
   `hanennkam@gmail.com`, name **Duits** into the live project's Authentication → Emails → SMTP Settings,
   then **send one real test message and confirm it arrives** — a settings page that saves cleanly proves
   nothing about port, TLS or the credentials. If a reset and an invite go to the same address, leave a
   minute between them or the second is silently dropped.
2. **Close sign-up on live**, and do it **before** the cutover window opens, not during it. Verify
   `POST /auth/v1/signup` answers 422 `signup_disabled`.
3. Then cutover (`docs/CUTOVER_RUNBOOK.md`).

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
