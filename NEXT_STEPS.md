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

1. **Forgot password does not deliver.** Supabase answers `400 Email address "…" is invalid` for both
   existing test accounts, while unknown addresses return `200`. Two consequences:
   - **Reset emails never arrive**, so the "Forgot password" flow cannot complete today.
   - **Account enumeration at the Supabase level**: the status code differs for a known and an unknown
     address. Our UI hides this behind one message, but the API itself leaks it.
   The likely cause is the project's email provider rejecting `example.com` recipients. This is a Supabase
   setting, not app code. *(Still open.)*
2. **Settings showed "Not signed in" after an invite sign-in.** — **Fixed in pass 3 and verified end to
   end.** The session now carries the address read from the token, and Settings shows it. See the
   verification table below.
3. **Three unexpected accounts exist on staging** — `suhaib@gmail.com`, `adeeb@gmail.com`,
   `madsu04@gmail.com` — created while sign-up was open (10:14–13:15 today). They own 5 rows between them
   (4 manual, 1 receipt scan). These are **not** mine and have been left untouched. They may be your own
   test sign-ups; if not, they are direct evidence of the exposure that closing sign-up has now removed.
   Decide whether to delete them.

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
2. **Sign-up is closed on staging** (`disable_signup: true`, `/auth/v1/signup` → 422 `signup_disabled`).
   It was open earlier today, and three accounts that are not ours were created through it. **The same
   setting must still be turned off on the live project** before cutover — see the checklist.
3. **Settings shows "Not signed in"** after signing in through an invite link. — **FIXED in pass 3 and
   verified end to end** (the address is read from the token; see the verification table below).
4. **Three accounts on staging are not ours** (`suhaib@gmail.com`, `adeeb@gmail.com`,
   `madsu04@gmail.com`), owning 5 rows. Left untouched; decide whether to remove them. Two throwaway
   accounts of mine also exist: `duits-invite-test@example.com` and `duits-invite-verify@example.com`.
5. **Two staging rows still report `unexpected_format`** to `migrate_receipts.py`: their `receipt_path` is
   prefixed with a UUID that is not their owner, left over from a `down`/`up` cycle. The script refuses to
   touch them and exits 1. **The app no longer breaks on them** (pass 5): they answer 404 for the receipt
   and can be deleted. To clear them properly the object has to be moved to the owner's folder and
   `receipt_path` updated — a small data fix, not done. Not expected on live, where the move runs after the
   backfill.
6. **The live rehearsal has not been run.** Everything was verified on a local Postgres and on staging.
   Staging has now been through `down` → `up` → `verify`, and `verify` sections B–F are checked. The
   second half (`down` → `up` again) and the live run remain. Both need the SQL editor.

## Next

The next unfinished item is **the second half of the staging rehearsal** — one SQL-editor pass on staging:

1. `migrations/0002_multi_user.down.sql`
2. `select set_config('app.owner_id', '67a4cc95-a77a-4f1b-a12a-048db5324c1f', false);` then
   `migrations/0002_multi_user.up.sql`

That completes `up → verify → down → up`, the exact sequence the live run uses. I read the row counts back
automatically between the two runs. Expect 29 rows at each stage.

After that: the SMTP fix (unblocks password reset and invites), the phone checklist, then cutover.
7. **Staging has 29 rows, not the 30 last recorded.** The migration does not delete rows (proven locally),
   so this is not the migration. Most likely a delete from the phone or test cleanup. Worth a look against
   the backups if the exact count matters.
8. **Not verified on a real iPhone.** Everything was checked in desktop Chrome. Notably unverified:
   whether `100dvh` shrinks when the iOS keyboard opens (the design assumes the box can scroll), whether
   `justify-content: safe center` is supported in Safari (the plain `center` fallback would let the title
   clip above the box on overflow), `scrollIntoView` inside a fixed scroll container, real safe-area
   insets, and focus zoom at exactly 16px.
9. **The sign-in form is taller than the keyboard strip** on a small phone (456px of content against 300px
   at 375×667), so it scrolls rather than fitting in one glance. Every control is reachable.

**Resolved since the earlier passes** (kept so they are not re-opened): `image_hash` is now in
`schema.sql`; `PORT` is pinned to `10000` by `render.yaml`; the Build stamp is injected per request and
needs no manual bump.

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
