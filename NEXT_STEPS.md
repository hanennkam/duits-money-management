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
| Pass 12 — live `image_hash` shape, step 3 hardened | **Done except the staging rollback.** Production's `image_hash` uniqueness is a *partial unique index*, which step 3's text patterns could not see; step 3 now reads the catalog. Staging rebuilt to that shape and re-run: `up`, `verify_after_up.sql` and the 15 isolation tests all clean. `0002 down` on staging is the one rehearsal step left. *(Rollback since run — see Pass 13.)* |
| Pass 13 — live cutover, steps 3–4 and 9 | **Done and verified.** Live was found already migrated, with the **fixed** `0002` (snapshot 2 rows, partial index with its `WHERE`). Receipts backed up (16 files / 10.8 MB), baseline audit 75 rows / 16 objects, and the 2 receipt objects moved into the owner's folder with a sha256 match against the backup. **Live is now in an open write window: the deployed code cannot insert until step 11.** |
| Phase 1 — Add Transaction chooser (UI only) | **Done and measured in a desktop browser; not measured on a real iPhone, and no write was made.** The "+" now opens a two-option chooser — a compact sheet hugging two square cards, which expands to full height once Manual or AI is chosen; each flow has its own Back. See the Phase 1 section — it lists every number that was measured and everything that was not. |
| Live's `0002` state, re-read by the owner | **Confirmed, 2026-10-17: `0002` is applied on live** — `public.transactions.user_id` exists on `viorpltdkpexswvofeul`. This line is the **owner's read-only check**, not something the assistant verified in this session. **Staging is behind live:** it is pre-0002 and needs `docs/migration-runbook.md` §2–§5. |
| Phase 2, step 2a — budget, balance, commitments (SQL + API) | **Done; staging run reported clean by the owner** (up → verify → isolation suite → down → verify → up). Not observed by the assistant. See the 2a section. |
| Phase 2, step 2b — the money UI | **Done, measured in desktop Chromium with the network stubbed; nothing has been on a phone or against staging.** The suite printed `296 passed, 21 skipped` then and prints `300 / 21` now. See the 2b section and the phone checklist at the end of this file. |
| Phase 2, step 2b — Home reworked to the reference layout | **Done, measured in desktop Chromium at 390px and 375px in both themes; no phone and no real touch.** `300 passed, 21 skipped`. The four money states, the deleted card and where its breakdown still lives are recorded in the "Home reworked" section at the end. |
| Phase 2, step 2c — the balance card: anchor, breakdown, budget offer (UI only) | **Done, measured in desktop Chromium at 390px in both themes; no phone and no real touch.** `306 passed, 21 skipped`. The five money states, the two new sheets and the anchor's round trip are recorded in the 2c section at the end. |

## Phase 1 — the Add Transaction chooser (UI only)

**Branch `feat/add-transaction-chooser`, cut from `origin/main` = `52e7a75`; nothing pushed, nothing merged, no
schema or database change.** Files: `app/static/index.html` (the change), `tests/test_static.py` (five new page
tests), `NEXT_STEPS.md` (this section). `app/*.py`, `schema.sql`, `migrations/`, `docs/` untouched — Phase 1 is
the UI only.

**What the sheet is now.** The header is unchanged (Cancel / title / Save), and under it sit three views:
`#screen-chooser` (the two options, as two square cards side by side on a sheet that hugs them),
`#screen-add` (Manual: the amount, the keypad, the date and mode pills, Details, the chips) and `#screen-ai`
(AI: the Smart Entry card and Scan Receipt). While the chooser is up the sheet is **compact** — `height: auto`,
growing from the bottom edge to fit the two 176px cards and nothing else — and it expands to its full height the
moment Manual or AI is chosen. The `is-compact` class that says so is set by the same `showAddView()` call that
switches the view and the chrome, so the height cannot disagree with what is on screen. The keypad is the sheet's
last row and, with Save in the header, exists **only** in Manual — there is no amount to type and nothing to save
in the other two. One function, `showAddView()`, moves the three views and that chrome together; `openAddSheet()`
asks for the chooser on every open, so a second open cannot land on the view the last one used. Each flow has its
own Back (`reverseAddView`, which blurs first so the chooser cannot return under a raised keyboard); Cancel, the
scrim tap and the swipe-down drag are unchanged, so the sheet can still be dismissed from any view. Both flows
submit exactly what they submitted before: `POST /transactions` (keypad Save), `POST /transactions/text` and
`POST /transactions/scan`, with the same fields, the same payload keys and the same duplicate handling — only the
entry point moved. The notice slot is now two slots (one above the keys, one in the AI view), because the manual
slot lives inside the keypad and would be invisible in a view that has no keypad.

**Measured, this session, in desktop Chromium — nothing below is an inference.** The behaviour walk was run twice:
once against the **real served page** (`uvicorn` on `127.0.0.1:8000`, `GET` only) and once on a copy of that same
response served on a second port so it could be framed at exact sizes, in both themes, at 375x667, 390x844 and
320x568. The layout below is the **refined** one — a compact chooser sheet with two square cards; this branch's
first pass had two full-width rows on a full-height sheet, and those numbers are superseded here rather than kept.

- **The walk, identical in every viewport and both themes:** closed → `+` → chooser on screen, Manual and AI
  hidden, keypad hidden, Save hidden, title **Add Transaction**, and **zero `input`/`select`/`textarea` inside the
  sheet**; → Manual → form + keypad + Save on screen, title **New Transaction**, three inputs (date, merchant,
  note), the amount line reading **RM 0.00** with Save still greyed (no digits were typed this session — the keys
  themselves are unchanged by this work); → Back → chooser, keypad gone and the sheet back to its compact height
  (251px); → AI → Smart Entry card and Scan Receipt on screen, title **Smart Entry**, keypad and Save hidden, one
  input; → Back → chooser; → Cancel → the overlay is closed (`.open` gone, `aria-hidden="true"`, the sheet parked
  at `translateY(251px)`). A second open lands on the chooser again, never on the last view.
- **The sheet is compact in the chooser and full height in both flows.** Chooser: **251px** at all three sizes —
  `height: auto` hugging two 176px cards (grab 17 + head 38 + grid margin 4 + card 176 + 16 bottom), flush to the
  bottom edge (0px gap), `container-type: normal`. That last part is the subtle one: this is the only state where
  `#addSheet` is **not** a size container, because `container-type: size` applies `contain: size`, which collapses
  a box whose height is auto. The cards are therefore sized by their own rules, and the sheet's
  `@container (max-height: 640px)` block simply does not apply while the chooser is up. Manual and AI:
  **600.3px** at 375x667 (that block applies again), **759.6px** at 390x844, **511.2px** at 320x568 — the same
  heights the sheet had before this change. The bottom padding is `calc(16px + var(--sab))`, so the cards clear a
  home indicator; `--sab` is 0 in the harness.
- **The chooser grid, from `getBoundingClientRect()`:** two cards on one row — `display: grid`,
  `grid-template-columns: 1fr 1fr`, `gap: 12px` — 165.5x176 at 375 (w/h 0.94), 173x176 at 390 (0.98), 138x176 at
  320 (0.78). Each card is one `<button>` (no chevron: there is nowhere to go sideways) carrying a 40x40 badge, a
  16px/700 label and a 13px help line that **wraps** (2 lines at 375 and 390, 3 at 320) rather than ellipsising;
  `scrollWidth == clientWidth` and `scrollHeight == clientHeight` on every card and every text node, so **nothing
  is clipped and nothing is ellipsised**. `document.documentElement.scrollWidth - innerWidth` was **0** at every
  size and every theme, and so was the sheet's own overflow. (The only horizontal scroller the sweep finds is
  `#addChips`, the chips row in Manual, which pans sideways by design — 539px of content at 375.)
- **Contrast, computed from the painted colours with alpha compositing** (foreground over the background it sits
  on, light / dark): card label **15.59 / 13.94**; card help line **8.44 / 5.27**; sheet title **17.21 / 17.01**;
  Cancel **4.02 / 4.66** (unchanged). Two new numbers worth stating rather than burying, because this refinement
  added the elements they belong to: the badge icon (`--accent` on `--accent-soft` over `--card-2`) is
  **3.14 / 3.11** — above the 3:1 floor for a graphic, but with little to spare, and it is decorative (the label
  names the option); and the card's own surface is only **1.10 / 1.22** against the sheet's white / `#1c1c1e`,
  with its hairline border at **1.36 / 1.44** — the same "surface + hairline, not a 3:1 ring" posture every other
  `--card-2` control in this sheet already has (Back chip, pills, chips). The help line deliberately uses
  `--text-2` and not the `--muted` the sheet's other secondary text uses: `--muted` measured **2.97:1** on
  `--card-2` in light mode, under 4.5:1 for 13px text. `.add-hint` still uses `--muted` — pre-existing and left
  alone. The Back chip (**15.59 / 13.94** text, **3.64 / 3.82** chevron) and the Smart Entry field
  (**17.21 / 13.94**) were measured in this branch's first pass; those elements did not change.
- **The AI failure path renders where it can be seen** (measured in this branch's first pass, not re-run since; the
  AI view and both notice slots are untouched by the refinement): with a typed note and the framed copy's request
  answered as unauthorised (no session there), the error card appeared **inside the AI view** (`#addNoticeAi` on
  screen, the manual slot off screen because its keypad is hidden), sheet overflow still 0, and Back returned to a
  clean chooser. No write was issued at any point.
- **Console: no JavaScript errors in any run.** The real served page reported **0 messages**; the framed copies
  reported only 18 x `404 /logo.png`, which have no file to load there — a harness artefact, not the app.
- **Three screenshots were taken this session** (the browser tool could capture the harness page, unlike the first
  pass of this branch): the chooser at 375x667, 390x844 and 320x568 in **light** and in **dark**, and Manual/AI
  opened from it. They are **not in the repo** — `chooser-light-375-390-320.png`,
  `chooser-dark-375-390-320.png` and `flows-manual-ai-manual.png` sit beside `page.html` and `harness.html` (the
  framed copy and its wrapper) under `$TMPDIR/opencode/phase1-measure/`. The two chooser shots were taken with the
  copy's sign-in screen hidden — see (5) below for why that was necessary.

**NOT measured, and recorded as not measured.** (1) **No real iPhone and no iOS keyboard.** Nothing here was
touched by a finger; the three device-specific questions this change raises are open — Back while the AI field has
focus and the keyboard is up, focus zoom in the two flows, and how much of the AI view the iOS keyboard covers.
Every iOS trap the file relies on is unchanged and pinned by test, but that is not the same as measured. (2) **No
write was made, anywhere.** The three endpoints are asserted unchanged by the page test and by reading the calls,
not exercised end to end; the acceptance for Phase 1 is the entry point, so nothing was posted. (3) The framed runs
had `--sat`/`--sab` = 0 and no keyboard, and `dvh` inside a frame is the frame's height; a real 375x667 iPhone
Safari box is not this 600.3px box, and none of the above saw a notch or a home indicator. (4) The framed copy and
the real page are both **signed out** (no session is available to an agent), so the page behind the overlay was the
app's sign-in screen and not a real transaction list — the sheet's geometry does not depend on what is behind it,
but that is an assumption, not a measurement. (5) That sign-in screen sits at `z-index: 40`, above `#addOverlay`
(20) and the tab bar (10) — **pre-existing, untouched by Phase 1**, and irrelevant on a signed-in phone, but it is
why the visual evidence required hiding `#authScreen` first. (6) The theme was set by writing `data-theme` on
`<html>` rather than by the OS preference, and the harness copy's own theme choice resolved to dark on this desktop
— worth knowing before reading any single-pass number out of context.

**Branch and docs, stated because they do not line up.** This branch was cut from **`origin/main` = `52e7a75`**,
because local `main` is a **stale ref 43 commits behind** it. `multi-user` carries **Pass 14 and Pass 15**
(`f881b67`, `19179ef`), which record PR #1's merge and the deployed commit; they are **still unmerged**, so this
branch's copy of this file is two docs commits behind them and the `## Next` below is Pass 13's list, not the
current one.

## Pass 13 — the live cutover: what live actually was, and steps 3–4 and 9

**Live turned out to be further along than this file said.** `scripts/audit_live.py` against
`viorpltdkpexswvofeul` shows `transactions.user_id` **`uuid, NOT NULL`**, plus `api_tokens` and
`migration_0002_saved_constraints` — the `up` migration is applied. Live's snapshot table holds **2 rows**:

```
constraint transactions_dedupe_hash_key: alter table … add constraint … UNIQUE (dedupe_hash)
index      transactions_image_hash_uidx: CREATE UNIQUE INDEX … (image_hash) WHERE (image_hash IS NOT NULL)
```

The partial index is there **with its `WHERE` clause**, so the **fixed** `0002 up` is what ran on live — the
silent no-op did not happen there, and the 2-row snapshot is the evidence, read out of the project rather than
taken on trust. `disable_signup` is **true**, so sign-up is already closed.

**Steps 3–4.** `.env` → live (checked, step 3a). `backup_receipts.py` downloaded **16 files, 11294015 bytes
(10.8 MB), exit 0** into `~/Backups/duits-2026-10-17/receipts/`. `audit_live.py`: **75 rows**, **16 receipts
objects**, 2 folders, JWKS 200 with 1 `EC/ES256/P-256` key, `mailer_autoconfirm` false. Step 4 is a *baseline*,
and it ran **after** the migration, so 75 rows / 16 objects are the **current** counts, not pre-migration ones —
that is the pair every later step is compared against.

**Step 9, the receipt objects.** Dry run `legacy_rows: 2`, `would_move: 2`, no `missing_source`, no
`unexpected_format`, no `shared_object`, exit 0. Apply: `copied: 2`, `bytes_copied: 1246707`,
`rows_updated: 2`, `originals_deleted: 2`, no failure counter, exit 0. Confirm: `already_moved: 2`,
`legacy_rows: 0`. **Verified independently of the script's own counters:** both rows now sit under
`<owner>/2026/10/…`, both objects download **sha256-identical** to the pre-move backup (572574 + 674133 =
1246707 bytes, matching `bytes_copied`), and both legacy originals are gone. The rows are 2 of 75 — the other
73 are 72 `manual` and 1 `text`, so 2 is the correct scope.

**Open, and it is time-sensitive: live is in a write window.** The deployed code is `main`, which never sets
`user_id` (`app/db.py` and `app/main.py` on `main` contain no reference to it), and live's `user_id` is now
`NOT NULL`. So the live app can still **read** (and still serves the re-homed receipts, whose paths it signs
as-is), but **every new scan, text or manual entry fails** with a not-null violation until step 11 deploys the
branch. Steps 10 (Render env vars) and 11 (merge → deploy) are therefore not optional follow-ups — they close
this window. Until then the household should not expect the app to accept new entries.

**Open finding: 14 orphan objects on live.** The bucket holds **16 objects and only 2 are referenced by any
row**; all 14 extras sit at the same legacy `2026/10/<uuid>.jpg` shape, and **no row points at a missing
object**. So they are pure orphans — about 9 MB with nothing referring to them. The app deletes its upload when
the insert fails, so this is not the design; it is not explained, and it does not block anything (step 9 touches
only the 2 referenced objects; all 16 are in today's backup). Worth a look after the deploy, not during it.

**Opened for review, and deliberately not merged: PR #1** (`multi-user` → `main`, 43 commits) —
https://github.com/hanennkam/duits-money-management/pull/1. Its summary states live's schema is already
migrated and verified, so the order is schema-then-code, and that `docs/migration-runbook.md`'s merge-first
order is superseded. `main` has not been touched; the merge fires only on the owner's "env vars set".

**Step 2's `pg_dump`: it does not exist on this Mac, and that is recorded rather than assumed.** A search of
`~/Backups` (every file, not just the expected names), the repo working tree including ignored files, and a
shallow sweep of `$HOME` found no dump — and there is no `pg_dump` binary installed here at all. Whether the
Supabase dashboard holds a backup can only be seen in the dashboard. What *is* covered: live's receipts, twice
over — `~/Backups/duits-2026-10-16/receipts` and `~/Backups/duits-2026-10-17/receipts`, **16 files each**, and
the 16 Oct copy holds the pre-move originals of both re-homed objects. The database's recovery paths are
`0002 down` plus redeploying the previous `main` commit. The merge is not blocked on this.

**Writes lost while the window is open — record, do not fix.** Every scan, text and manual entry attempted
against live since step 7 was refused by the `NOT NULL` `user_id`, so nothing was saved. Those entries need
re-entry by hand once the deploy is up. Ask the household what they tried to add; do not guess, and do not try
to reconstruct rows from the log.

**Not done:** step 10 (Render env vars — yours), step 11 (merge → deploy, on your "env vars set"), step 12
(smoke test — mine, immediately after the deploy; a **real write** is the acceptance criterion, not `/health`),
steps 13–14, and the post-deploy items (the 14 orphans, the `schema.sql` sync, Known issue 8's device pass).
Nothing has been rolled back anywhere, `main` is untouched, and no live SQL has been run by me — that is not
possible here, which is why step 7 was yours.

**Keep `public.migration_0002_saved_constraints` until the rollback window closes** (steps 13–14). It is the
only record of the two objects' original forms; dropping it early costs the `down` its verbatim restore.

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

**Staging now carries the live shape, and the re-run is done** (2026-10-17, by the owner in the SQL editor):
`0002 down` → `create unique index transactions_image_hash_uidx … where image_hash is not null` → `0002 up`
with A's id → `verify_after_up.sql`. Every grid row came back as expected, and — read straight out of
staging — its `public.migration_0002_saved_constraints` now holds **2** rows: the dedupe constraint **and**
`index transactions_image_hash_uidx` *with its `WHERE` clause*. That is the new step 3a doing on the real
project what the old one could not, and it is the artifact the rollback depends on. The migration was
data-preserving: **29 rows / one owner** before and after.

**The isolation suite passed against it: 15 passed, 4 warnings** (library deprecation warnings from the
`supabase` client, not test failures). It ran after the `up`, against the per-owner partial index, with the
real project — real sign-in, real JWKS, real Postgres, real Storage, and PostgREST/Storage RLS as each user,
including the 409 case in both directions. Afterwards staging is exactly as it was: 29 rows, one owner, 14
receipt objects under `A/2026/10`, nothing under B's folder, no duplicate hashes.

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
They have now been run against the migrated staging, and they pass.

**Only the staging rollback is left, and the live SQL.** *(Both have since happened — the staging `down` +
`verify_after_down.sql` on 2026-10-17, and the live `up`; see Pass 13.)* The remaining rehearsal step is `0002 down` +
`verify_after_down.sql` on staging — the rollback path is still proven only locally (PGlite), where it
restores the constraint and the partial index verbatim. Nothing has been run against live.

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

- `main` and `origin/main`: `52e7a75`, "Merge pull request #1 from hanennkam/multi-user". **PR #1 is merged and
  deployed**, which is what closed the Pass 13 write window: step 11 has happened. The previous `main` commit is
  the rollback target, and the local `main` ref was once 43 commits stale — it has since been fast-forwarded in
  place to `52e7a75` (`git fetch origin && git branch -f main origin/main`, authorised, nothing pushed), so branch
  from `origin/main` if you are re-cutting this work.
- `multi-user`: `19179ef` (Pass 15), pushed to `origin/multi-user`, **2 commits ahead of `main`** — `f881b67`
  (Pass 14: "merged, deployed, and step 12's HTTP half") and `19179ef` (Pass 15: the orphan dates and the
  citations). Both are notes/docs commits, and the branch is not merged into `main`.
- Phase 1 UI branch: `feat/add-transaction-chooser` at `58110bf`, cut from `origin/main` = `52e7a75`, **1 commit
  ahead of it** and **unpushed** (`git ls-remote origin` lists `main` and `multi-user` only). It adds the
  Manual / AI chooser to the Add sheet; it is approved but **unmeasured on a real iPhone**. Its `pytest` is
  **211 passed, 15 skipped, 2 warnings** — the 206 of Pass 13 plus five new page tests (page harness alone: 41).
- Phase 2 branch: `feat/budget-balance-commitments`, cut from `52e7a75` and **rebased onto Phase 1's `58110bf`**,
  so step 2b builds on the chooser instead of colliding with `openAddSheet`/`showAddView`. Step 2a — the 0003 SQL,
  `app/finance.py`, the models, the db helpers, the nine routes and the tests, with **no change to
  `app/static/index.html`** — is committed there. It is **not** merged and **not** pushed.
- `pytest` on this branch after 2a: **282 passed, 21 skipped, 2 warnings**. Read the count from the run you make —
  this line is a checkpoint, not a constant. (15 of the 21 skips are pre-existing; 6 are the new staging tests.)
- **Live's `0002` state, re-read by the owner (2026-10-17): applied.** `public.transactions.user_id` exists on
  `viorpltdkpexswvofeul`, so the schema half of the cutover is already behind us. Attributed to the owner's
  read-only check, **not** to this session — no SQL and no audit was run by the assistant here. **Staging is
  behind live:** it is pre-0002 (the 0003 up's failure was its view reading the missing `transactions.user_id`),
  and `docs/migration-runbook.md` §2–§5 is the sequence that brings it forward.

## Phase 2, step 2a — budget, account balance and monthly commitments (code only)

**What it adds.** Three tables plus a view (`migrations/0003_budget_commitments.up.sql`), all with ENABLE **and**
FORCE row level security and four owner policies each: `user_finance_settings` (one row per user: opening balance,
optional monthly budget, currency pinned to MYR), `monthly_commitments`, and `commitment_payments` (one paid mark
per commitment per month — this is what stops a paid commitment being subtracted twice). A composite foreign key
`(commitment_id, user_id)` makes "a payment points at a commitment of the same owner" a database rule.
`public.transaction_totals` is a `security_invoker` view (owner + mode + month totals) so the all-time balance is
summed in Postgres instead of a Python loop that PostgREST's `max-rows` would truncate; its `anon`/`authenticated`
grants are revoked, because the view has no policy of its own and the API is its only reader.

**The figures, and where they come from.** Nothing is stored: `app/finance.py` derives everything from the rows on
every read. `current_balance = opening_balance + total_income − total_expense` (the wire field is `total_expense`,
singular — step 2b's UI reads that name), all-time and **every mode**.
`unpaid_commitments` = the active commitments with no paid mark for the month being viewed.
`safe_to_spend = current_balance − unpaid_commitments`. `remaining_budget = monthly_budget − unpaid_commitments −
this month's spend **for the requested mode**`, and `null` when `monthly_budget` is `0` ("no budget set"). The one
rule the tests pin hardest: paying a commitment is two writes — the expense, and the paid mark — and together they
leave safe-to-spend exactly where it was, so the money is never taken twice.

**Status: 2a is complete.** `pytest` after each commit. **The staging sequence has since been run**, by the owner
and not by this assistant: up → `verify_after_0003.sql` → the isolation suite → down → verify → up, all clean, no
data lost. That run is what closes the "never parsed or run" note below; nothing in it was observed by the assistant.
Step 2b — the Home card, the commitments sheet and the Settings "Money" section in `app/static/index.html` — is
**done**; see the 2b section directly after this one.

**Two prerequisites are now guards, not footnotes.** The up file checks that `0002` is applied before it creates
anything (`run 0002 first: public.transactions.user_id is missing`, or `public.api_tokens`), because its view reads
the column `0002` adds; the down file refuses with `nothing to roll back: 0003 is not applied` when none of the four
objects exist, and cleans up a half-applied 0003 by snapshotting only the tables that are there.
`verify_after_0003.sql` reports `transactions.user_id` as its first row (row 0), and `docs/migration-runbook.md` §10
states the `0002` prerequisite and points at `verify_after_up.sql` first.

**Not verified by the assistant:** the SQL was never parsed or run here, so `security_invoker`, FORCE RLS, the
composite FK and the view's revoke are argued from the documentation and from 0002's conventions, not observed on
this project. The staging run (owner's, above) is what gates the claims in this section; this session only read the
files.

## Phase 2, step 2b — the money UI (UI only)

**Branch `feat/budget-balance-commitments`, on top of 2a; nothing pushed, nothing merged, no schema or database
change, no live write.** Files: `app/static/index.html` (the change), `tests/test_static.py` (eight new page tests
plus two guards re-counted from three overlays to four), `tests/test_page_auth.py` (the commitment name joins the
escaped-field pins), `NEXT_STEPS.md` (this section). `app/*.py`, `schema.sql` and `migrations/` are untouched.

**What it adds.** Three surfaces, all reading the 2a routes and nothing else:

- **Home, "Safe to spend"** — one compact card **above** the "Spent this month" hero: the figure, and one line
  saying what it is made of (`RM 54.90 still due this month · RM 700.00 of budget left`; over budget reads
  `RM 50.00 over budget`). A negative figure is the only coloured state on the page and it uses `--danger`, with
  the minus put back by hand because `money()` drops the sign. With no opening balance and no budget saved, the
  card asks for the opening balance instead of drawing a total that would only mean "minus your spending", and a
  tap on the card goes to Settings → Money. **Details** opens the commitments sheet. The read is a third call in
  `loadHome()`'s existing `Promise.all`, with the same `monthQuery()` (month + mode) as `/summary`.
- **The commitments sheet** (`#commitOverlay` / `#commitSheet`) — the viewed month's commitments, each with
  `RM amount · due Nth` (proper ordinal suffixes), a two-way **Paid** toggle (POST to mark, DELETE to undo, both
  carrying the month) and a **Pay** button. Paused commitments show greyed with `· paused` and no Pay. An inline
  form adds one (name, amount, day 1–31) and validates all three before posting. The list comes from
  `GET /commitments?month=`, which is required by the API; committing a month change resets the cache, so one
  month can never show another's rows.
- **Settings, "Money"** (above Account) — Opening balance and Monthly budget as text fields with
  `inputmode="decimal"` at 16px, saving one field at a time on `change` (the API keeps what a request omits), a
  Commitments row that opens the same sheet and shows how many are active, and Currency MYR as info only. The
  Currency row moved here out of About rather than being duplicated.

**Pay is two writes, and the order is the feature.** Pay opens the Add sheet prefilled (`merchant = name`,
`amount`, `category = "bills"`, `type = "expense"`) on its Manual view, with Details expanded so the merchant is
visible but no keyboard raised. The paid mark is posted **only after** `POST /transactions` answers, and it is
posted for the month captured when Pay was tapped — not `state.month` at save time, because `afterAdd()` may move
the view to the transaction's own month. If the mark fails, the transaction stays saved and the toast says
`Transaction saved, but marking it paid failed.` A cancelled or failed save clears the pending mark, so nothing is
ever marked paid without its expense.

**One API-shape limitation, stated rather than worked around.** The summary has no "settings saved" flag, so "no
opening balance yet" is read as `opening_balance == 0 && monthly_budget == 0` — exactly what a user who has never
saved a row gets back (the defaults are not stored). A genuine RM 0.00 opening balance with no budget is
indistinguishable from "not set" and keeps seeing the prompt. That is honest rather than wrong (there is still
nothing to subtract from), and fixing it properly needs a response field — which is an API change this step was not
allowed to make.

**Measured, this session, in desktop Chromium — with the network stubbed, not on a phone, not on staging.** The
real page was served from the working tree on `127.0.0.1:8771` with `fetch` replaced by a harness that answered the
money routes; every call it received was recorded. `pytest` at the end: **295 passed, 21 skipped** (287 before this
step, i.e. eight new tests). What the walk showed:

- boot → `safeAmount` `RM 945.10`, meta `RM 54.90 still due this month · RM 700.00 of budget left`, and the only
  three reads `GET /summary`, `GET /transactions`, `GET /finance/summary` — the third carries `month=2026-10&mode=personal`;
- a negative figure → text `−RM 120.50`, class `neg`, computed colour `rgb(255, 69, 58)` = `--danger`;
- opening 0 / budget 0 → `Set your opening balance`, class `is-setup`, and a tap on the card lands on Settings with
  the Money fields filled;
- **Details** → sheet open (aria-hidden `false`), sub-line `October 2026 · RM 54.90 still due`, rows
  `Netflix … due 12th` / `Spotify … due 3rd` / `Gym … due 28th · paused` (no Pay on Gym), and a name sent as
  `Netflix <b>` reached the DOM as `Netflix &lt;b&gt;` — the raw tag was **not** there;
- the Paid toggle → `DELETE /commitments/c2/paid?month=2026-10` unmarks, `POST /commitments/c1/paid
  {"month":"2026-10"}` marks, each followed by a fresh `GET /commitments` and `GET /finance/summary`; the sub-line
  moved 54.90 → 74.80 → 19.90;
- **Pay** → Add sheet on top of the still-open sheet, `RM 54.90`, merchant `Netflix <b>`, bills chip on, Expense
  active, Details expanded, Save enabled; Save fired `POST /transactions` (bills/expense/54.9/today) **then**
  `POST /commitments/c1/paid {"month":"2026-10"}`, toast `Paid · Netflix <b>`, the Add sheet closed and the row
  behind it went paid;
- the same flow with the mark forced to 500 → toast `Transaction saved, but marking it paid failed.`, row still
  unpaid, sub-line still counting it;
- the inline form → day 32 rejected with no request; `Astro / 1,299.90 / 31` posted
  `{"name":"Astro","amount":1299.9,"day_of_month":31}`, cleared the fields and rendered `RM 1,299.90 · due 31st`;
- Settings → inputs `1000.00` / `2000.00`, Commitments `2 monthly`; `2,500.5` posted
  `{"opening_balance":2500.5}` (one field, commas stripped), tidied to `2500.50`, toast `Saved.`; `-5` budget and
  `abc` were both refused with a toast and **zero** requests, the field restored;
- Done and the scrim each closed the sheet (`class="overlay"`, aria-hidden `true`, sheet translated fully down);
- the console held no messages and no uncaught errors through the whole walk.

**Not verified, and what would verify it.** No iPhone, no Safari, no real touch: the sheet's drag-to-dismiss, the
`touch-action`, the 16px no-zoom rule, the safe-area insets and the visual feel are **not** measured here — desktop
Chromium with a mouse proves none of them. No staging and no real data: every figure above came from the harness,
so the wire shapes are trusted from 2a's tests (`total_expense`, nullable `remaining_budget`, `paid` per month)
rather than observed. The two things to check on a phone against **staging** are listed at the end of this file.



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

> **Phase 1 (the Add Transaction chooser) is on `feat/add-transaction-chooser`** — the section at the top of this
> file has the facts and the not-measured list. **Everything below is Pass 13's list, written while PR #1 was
> open, and is superseded:** PR #1 has been merged (`main` = `52e7a75`), Render deployed it, and Passes 14–15
> record that — they live on `multi-user` (`f881b67`, `19179ef`) and are **still unmerged**, which is why this
> branch's copy of this file is behind them. Fold those in (direct merge, no PR) before treating the list below
> as current, and do not merge this branch to `main` until the branch's own copy of this file has them.

**The write window decides the schedule.** Every scan, text and manual entry against live has been failing since
step 7 (`main` never sets `user_id`; live's `user_id` is `NOT NULL`), so closing it is the priority and the
order below is fixed. Step 1 is done — **PR #1 is open and unmerged**.

1. **DONE — PR opened.** `multi-user` → `main`, PR #1, no merge.
2. **Step 10 — the Render environment variables (yours).** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   `SUPABASE_PUBLISHABLE_KEY`, `ANTHROPIC_API_KEY`, `API_KEY`, `ENVIRONMENT=production`, and
   `ALLOW_LEGACY_API_KEY=true` + `LEGACY_USER_ID=<your auth.users id>` while the Shortcut still uses the shared
   key. Confirm `PORT=10000` is set **in the dashboard** — do not change the Dockerfile's 8000 default. Your
   "env vars set" is the merge trigger.
3. **Merge (authorised) + step 12 smoke test, immediately.** Render auto-deploys from `main`. Acceptance is a
   **real write**, not `/health`: one scan and one manual entry → 201 and the rows appear; edit one; delete one
   test row; open one of the two re-homed receipts (photo loads, 200 signed URL); Settings → **Build** matches
   the deployed commit. `/health` 200 with `no-store` + a CSP nonce is the cheap half.
4. **Live SMTP, same session (yours).** Confirm `smtp.gmail.com`, 465, sender `hanennkam@gmail.com`, name
   **Duits** are in on **live** — the per-project copy is the unproven part — then send **one** real test
   message and confirm it arrives. If a reset and an invite go to the same address, leave a minute between them
   or the second is silently dropped. Sign-up is already closed on live (`disable_signup: true`, audit).
5. **After the deploy, in the next docs touch:** the 14-orphan decision (investigate only once step 12 has
   passed — no bucket cleanup before then; if they are debris from failed inserts, decide keep-as-archive vs.
   delete with the same explicit-method discipline as the household rows), the `schema.sql` sync (per-owner
   comment + the global partial index live carries) as a **separate** change, the `a2d55e96` (row id, Pass 9
   throwaway) and `b31b4f8f` citations, and one focused phone pass for Known issue 8's three device items.

**Rollback, stated once so it is ready and unneeded:** redeploy the previous `main` commit (the old code never
reads `user_id`), and `0002 down` if the schema must go back — rows are kept, and it refuses if two owners share
a hash. Receipts do not move back; each row's `receipt_path` is the source of truth.

**Two runbooks, two orders.** `docs/migration-runbook.md` §1 merges to `main` *first* with auto-deploy paused;
`docs/CUTOVER_RUNBOOK.md` merges at step 11, *after* the migration. The owner chose the second, which is what
live is now doing, and the older file carries a note saying so. Why it matters: deploying before the migration
would have shipped code that selects `user_id` against a schema without it — every request a 42703.

**The staging rehearsal is now closed, rollback included.** The `up` and the verification did: staging's
snapshot held **2** rows, so step 3a captures a partial index *with its `WHERE` clause* on the real project, and
the 15 isolation tests pass against the per-owner partial index. The **rollback has now run** (2026-10-17) and
was checked independently of the grid, through the API: still **29 rows**, and `user_id` gone
(`42703 column transactions.user_id does not exist`), `api_tokens` gone, snapshot table gone (`PGRST205` both),
14 receipts all under A's folder and none left at the legacy path. **Live's `up` is likewise verified from the
project, not from the grid alone** — its snapshot's 2 rows are what proves the fixed step 3a ran there.

**Two figures that move, so they are checkpoints and not constants.** Live's audit in Pass 13 read **75 rows /
16 objects**; staging's settled state is **29 rows / 14 objects**. Both change the moment anyone uses either
app — the row counts immediately, and live's object count as soon as the write window closes — so compare later
runs to the run you took, not to these strings.

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

## Phase 2, step 2b — the phone pass, against STAGING

Nothing below has been done. It is the checklist for the one environment a desktop browser cannot stand in for.
**Staging only: no live account, no real money, no write anywhere else.**

**Setup.** Staging's API (`https://<staging-service>.onrender.com`, the Render service that points at the staging
Supabase project) must first be brought to schema 0003 (`docs/migration-runbook.md` §10) and seeded with the two
`--phase after` fixtures (`scripts/staging_seed.py`, which needs a `user_id` after the 0002 up). Then, on the
iPhone, open the staging URL in **Safari** (not the Home Screen copy — that can be an old build; check
Settings → About → Build matches the deploy) and sign in as **the staging test account**, the same one
`scripts/run_staging_tests.py` uses. Personal mode, current month.

**What to look at, and what "right" is:**

1. **The balance card.** Home opens with **Balance** (all time, every mode) — the largest figure on the screen, a
   quarter larger than it was — with the month named only by the picker in the header above, and under it a
   tappable pill reading **Safe to spend**: the opening balance plus everything in,
   minus everything out, minus the unpaid commitments of the month being viewed. Set Opening balance in
   Settings → Money to a number you can check by hand (e.g. 1000), add one commitment of RM 50 due this month, and
   the pill must drop by exactly 50 against the same pill before the commitment existed. Overspend on purpose and
   the **pill** must go **red with a minus sign** (light theme `#ba1a1a`, dark `#ff453a`), not just red — the
   balance above it keeps the body colour and only grows a minus sign.
2. **Fresh account.** With the settings row deleted (or a brand-new staging user), the balance reads **—** and the
   pill reads **Set your opening balance** (no "Safe to spend" label beside it); tapping the pill lands on Settings
   with the Money section on screen; saving an opening balance and coming back to Home replaces both with figures.
   Then the budget card below: absent until a Monthly budget is saved, and absent again when you browse to an
   earlier month, because "days remaining" only means something in the month you are in.
3. **The sheet, by touch.** Details opens the commitments sheet and it comes up from the bottom with the page dimmed
   behind it, **not see-through at any point**. The title stays put while the list scrolls. Swipe down on the drag
   handle or the header closes it and nothing else moves; a swipe that starts on a row at the top of the list closes
   it too (by design), and one that starts mid-list scrolls. The dim is not reachable while the sheet is animating.
4. **Paid.** Tapping **Paid** marks it (green) and the line under the title drops by that amount; tapping again
   unmarks it. The card behind updates without closing the sheet. Kill the network mid-tap: the row must come back
   to where it was, with a toast, not stay half-toggled.
5. **Pay, and the month trap.** Tap **Pay** on an unpaid bill: the Add sheet must open **on Manual**, prefilled with
   the name as merchant, the amount, bills, Expense, Details already open, and **no keyboard covering the amount**.
   Save: the transaction lands, the sheet closes back to the commitments list, the row is paid and the toast names
   it. **Then view last month (month pill) with an unpaid bill from last month, tap Pay, and save.** The
   transaction is dated today but the *last* month's bill must be the one marked paid — that is the whole point of
   capturing the month at tap time.
6. **The mark failing.** Hard to force on staging; if you can pull the network between the save and the mark, the
   toast must say the transaction was saved and the mark failed, and the bill must stay unpaid.
7. **The inline form.** Add a commitment by touch: name, `1,299.90`, day `31`. It must accept the comma, reject day
   `32` and an empty name with a toast, and the new row must appear in the list without a reload. A long name must
   ellipsize, not push the buttons off the row.
8. **The fields.** Opening balance and Monthly budget must **never zoom the page** when focused (that is the 16px
   floor), the numeric keyboard must come up (a `,` and `.` must both work — `NaN` is rejected with a toast), and
   flipping the phone to dark must keep every field and the dim readable.
9. **Sign out.** Settings → Sign out, then sign in as the other staging user: the card must not show the first
   user's figure for even a frame, and the commitments list must be empty rather than the other account's.

Record what is seen; anything that fails belongs in a new section here, not in a silent fix.

## 2026-10-18 — the money UI against live (`0003` is not on it)

Ran the app locally against the live project (what `.env` holds) to look at 2b. **Home is fine; every money read
500s**, because live is at `0002` and 2b reads the `0003` tables — `PGRST205` on `public.user_finance_settings`,
then on `public.monthly_commitments` and `public.commitment_payments`. That is the schema being one migration
behind the UI, not a UI fault, and **no write landed** (the one `POST /commitments` attempt answered 500).

Looking at it turned up two real UI faults of the same kind — a value that was never read, painted as a fact:

| Fixed in | Was | Now |
| --- | --- | --- |
| `b5ef265` | a 500 from `/finance/summary` rode in the same `Promise.all` as `/summary` and `/transactions`, so Home rendered `RM 0.00`, "0 items" and a server error *while `/transactions` had answered 200 with rows* | the card's read is guarded on its own; its failure costs the card and nothing else |
| `f0b9a8f` | the sheet read "October 2026 · nothing still due" directly over its own error card, and Settings → Money → Commitments read "None" | "could not be read" in both, and the sub claims nothing about a month before that month has been read |

Seen on the owner's **iPhone** (the Home half only): with the finance read failing, the hero, the ring and the rows
render and the card reads "—" / "Not available right now." — so `b5ef265` is confirmed on a real device. The
sheet's copy was captured afterwards in the desktop harness and has **not** been re-checked on the phone.

**To see 2b work, the database it points at needs `0003`.** Nothing in the UI changes that.

## 2026-10-18 — Home reworked to the reference layout (UI only)

**Branch `feat/budget-balance-commitments`; UI only — no API, no SQL, no schema, no migration, nothing pushed.**
Files: `app/static/index.html` (the layout), `tests/test_static.py` and `tests/test_page_auth.py` (the pins),
`NEXT_STEPS.md` (this section).

**The order now** (top to bottom): the header as it was (title, month pill, Personal/Business); the **Balance**
card — the label, a month pill on its right, `current_balance` big, and under it the **Safe to spend** pill you tap
to open the commitments sheet; **Income** and **Expenses** as two half-width cards, both from the existing
`/summary`; the **Monthly budget limit** card — percentage of the budget, a progressbar, "left to spend" (or "over
budget"), and the days remaining computed client-side; then **Recent Transactions** unchanged at three rows plus
See All. The old "Spent this month" hero and its Income/Net split are gone, along with the item-count pill. The
balance still comes from the one guarded `/finance/summary` inside `loadHome`'s existing `Promise.all`: this pass
added no request.

**The category card is deleted from Home and nothing was orphaned by it.** It was never a sheet — a tap anywhere on
it called `showScreen("insights")` — so the breakdown it pointed at is Insights' own "Spending by category" card
(`donutSvg` + `insightCategoryList`), reachable from the tab bar and untouched. Everything that existed only to draw
the Home ring went with it: `renderHomeCategories`, `homeCategoryGroups`, `legendRowHtml`, `HOME_DONUT_ROWS`, the
`small` option in `donutSvg`, and the `.cat-split*`, `.legend-*`, `.donut-sm` and `.card-tap` rules.

**Measured, this session, in desktop Chromium, offline, with every network call answered by a local stub** (the
harness is not in the repo). The page was framed at exact sizes — an iframe of 390x844 and one of 375x812 — and read
back through `getBoundingClientRect` and `getComputedStyle`, in both themes. Four states, all eight combinations:

| | budget set, under | budget set, over | budget 0 | `/finance/summary` 500 |
| --- | --- | --- | --- | --- |
| balance | `RM 1,400.00`, 50px | `−RM 50.00`, 50px | `RM 900.00`, 50px | `—`, 50px |
| safe pill | `RM 945.10`, 44px | `−RM 325.00`, `#ba1a1a` / `#ff453a` | `RM 845.10` | `—` |
| budget card | `65% of RM 2,000.00`, `RM 700.00 left to spend`, `13 days remaining`, bar 65% `#007aff` / `#0a84ff`, `progressbar now=65` | `100% of RM 1,000.00`, `RM 250.00 over budget` red, bar full red, `now=100` | absent | absent |
| month cards | `+RM 1,200.00` green, `−RM 800.00` | same | same | same (`/summary` answered) |
| recent rows | 3 | 3 | 3 | 3 |
| sideways overflow | 0 px | 0 px | 0 px | 0 px |

- **The pill is the tap target**: 321x44 at 390px, 306x44 at 375px, with the same 14px `--chevron` the settings rows
  use. The budget card's bar is 8px on `--card-2`, its fill `--accent` (or `--danger` when over).
- **Browsing to September**, driven through the real month picker (open, `monthCol.scrollTop`, Done): the budget
  card hides, its bar resets to `0%` / `now=0`, the hero pill follows to `Sep 2026`, and the three reads re-ran once
  each for `2026-09`. **The balance does not move with the month** — `RM 1,400.00` in both — because it is all time
  and every mode.
- **A five-figure month does not fit half of a 375px phone** at the 19px the design asked for: `+RM 12,345.67` is
  139px in a 135px box, measured rather than guessed. The figure now steps its own font down until it fits
  (`fitText`: 19→14px for the two month cards, 40→22px for the balance, 17→12px for the pill). `123,456.78` lands
  at 17px with its right edge exactly on the card's padding, at both widths, and ordinary figures are left at
  19px / 40px / 17px. The fit skips an element with no layout, so a screen painted while hidden is fitted when its
  tab is next shown (checked by leaving Home and coming back).
- **Nothing removed is left behind**: `categoryCard`, `categoryList`, `itemsPill`, `totalSpent`, `netTotal`,
  `heroSplit` and `safeCard` are absent from the served DOM in every state above.

**Two judgement calls, either of which is one line to change:**
- **Expenses are not red.** Only Income carries a token (green); the expense figure keeps the body colour with a
  leading minus, because colouring an ordinary month red would read as a warning. The budget card is where
  `--danger` is earned.
- **A negative balance is not red either** — it grows a minus sign. Only Safe to spend turns red, as asked.

**Follow-up tweaks, same day, same branch (one commit, UI only).** Three changes on the owner's instruction:
1. **The hero has no month pill.** This section first recorded it as kept — one `Oct 2026` under another, because
   the shared `paintMonth()` paints every `.js-month-label`. It is gone; the header picker is the only place the
   month is named (elements carrying `.js-month-label` on a loaded page: 4 → 3, one per screen header). The
   now-single-child `.hero-top` wrapper went with it.
2. **The budget card gained one line**: `<p class="budget-note">Monthly limit, separate from your balance.</p>`, in
   the secondary token (`--text-2`, 13px — dark `rgba(235, 235, 245, .6)`), inside the card, so it appears and
   disappears with it. The card is 133px tall with it at 390px.
3. **The balance is the largest number on Home**: `.hero-balance { font-size: 50px }` — 1.25x `.hero-amount`'s 40px,
   same 800 weight and letter-spacing, applied only to Home (`Insights`' own `.hero-amount` total stays 40px). The
   fit pass now starts at 50: `RM 1,400.00` stays at 50px at both 390px and 375px, and `RM 1,234,567.89` steps to
   47px at 375px.

Re-measured after the tweaks, 390px and 375px, both themes, same four states: nothing else moved — Safe to spend
still 17px, the month cards 19px, the budget card unchanged apart from the extra line, no sideways overflow, and no
console errors.

**Not verified:** no iPhone and no real touch (no swipe, no keyboard, no zoom, no safe-area behaviour — the 44px
floor, the target-based guards and the sheet's opacity rule are pinned in the page tests, not felt); **no
screenshot**, because this machine had no visible browser window for `browser.screenshot` to capture; no staging and
no live database, so every figure above is the stub's; nothing saved through Settings in this pass; and the two
rewritten items in the phone checklist above are still unrun.

## 2026-10-19 — the balance card: the anchor, the breakdown, the budget offer (UI only)

**Branch `feat/budget-balance-commitments`, UI only: `app/static/index.html`, `tests/test_static.py`,
`tests/test_page_auth.py`.** No `app/*.py`, no `schema.sql`, no `migrations/`, no `.env*`, no API and no SQL
change, nothing pushed, nothing touched on live or staging. This section replaces the first-run checklist that was
proposed for this screen: that idea is dropped, and the card now asks for one figure instead.

**The problem it answers.** The Balance is the all-time figure across every month and both modes, while the two
cards under it are this month and one mode, so the three numbers never reconciled on their own. And with
`opening_balance` still 0 the card showed a large negative number that read like a fact about the owner's money.

**What the card is now.**
1. **No opening balance yet (`opening_balance == 0`):** the card is titled `Set your balance`, carries one line
   (`Tell us how much money you have right now. We keep track from there.`) and one primary button. No figure, no
   Safe to spend — the whole figure area is `hidden`, so nothing on the card can be misread as a balance.
2. **The anchor sheet** asks exactly one question (`How much money do you have right now?`, `type="text"`
   `inputmode="decimal"`, 16px, comma and sign tolerant) and shows what will be stored before it is stored:
   `Starting balance will be RM x`, where `x = typed − total_income + total_expense`, computed in **integer cents**
   (`toCents`/`openingFor`), so the preview and the save cannot disagree. The save is the existing
   `PUT /finance/settings { opening_balance: x }`.
3. **With a balance set, the whole figure area is one real `<button id="balanceTap">`** (≥44px, accessible name
   `Balance RM 1,400.00. How this is calculated`) opening the **breakdown sheet**: `Starting balance`,
   `+ Income (all months, all modes)`, `− Expenses (all months, all modes)`, `= Balance`, `Bills still due this
   month`, `= Safe to spend`, the one line that explains why they differ from the month cards, `Edit my balance`
   (the anchor again, stacked over the list) and `Settings · Money`. Every figure is the API's own.
4. **The two half cards say which month they are:** `Income · this month` and `Expenses · this month` (the mode is
   still the header's toggle).
5. **No budget yet (`monthly_budget == 0`):** the same slot offers one — a dashed card, `Set a monthly budget
   (optional)`, a button to the one-field sheet (`PUT /finance/settings { monthly_budget }`), and the same caption,
   `Monthly limit, separate from your balance.` With a budget the real card is unchanged.
6. **Read failure:** `—` in the hero, `Not available right now.` and a **`Try again`** row that re-runs only
   `/finance/summary`. The figure area is present but `disabled` (there is no breakdown to draw), and the
   not-set prompt is not shown: unreachable is a different thing to unset.
7. **Settings → Money** gained one helper line under Opening balance:
   `Tip: use 'Set your balance' on Home if you are not sure what to enter.`

**Measured, desktop Chromium, harness `http://127.0.0.1:8771/frame/390x844?state=…`, 390px wide, both themes,
no sideways overflow in any state (0px).**

| state (URL suffix) | what it is | measured |
| --- | --- | --- |
| `?state=setup` (a) | brand new: no balance, no budget | `Set your balance` card, no figure (the tap area is `hidden`, 0×0), button 321×50 @17px; the dashed budget offer with its 321×50 button and the caption; the real budget card `hidden`; both labels read `… · this month` |
| `?state=zero` (b) | balance set, no budget | `RM 900.00` @50px, Safe to spend `RM 845.10`, `RM 54.90 still due this month`, tap area 321×134; the offer is dashed in both themes (`rgba(60, 60, 67, .18)` light, `rgba(84, 84, 88, .6)` dark) |
| `?state=under` (c) | everything set, under budget | breakdown opens with six rows from the reply — `RM 500.00`, `RM 1,200.00`, `−RM 800.00`, `= RM 900.00`, `−RM 54.90`, `= RM 845.10` — the note, and both links at 326×44 |
| `?state=over` (d) | over budget | `−RM 50.00`, pill `−RM 325.00`, draw at `--danger` (dark `rgb(255, 69, 58)`, light `rgb(186, 26, 26)`), `100% of RM 1,000.00`, `RM 250.00 over budget`, bar `aria-valuenow="100"` |
| `?state=fail` (e) | `/finance/summary` answers 500 | `—` in the hero, `Not available right now.`, `Try again` 64×44, the tap area `disabled`, no budget card and no offer; the month cards, the rows and the list are untouched |

**The three destinations inside the breakdown sheet (state `under`), one click each:**
- **`Edit my balance`** opens the anchor sheet *over* the breakdown (breakdown still open underneath; **0 requests**).
  `Cancel` closes the anchor and leaves the breakdown in place (settles in ~500ms, the usual close animation).
- **`Settings · Money`** closes the breakdown, shows Settings with the Money section in view, both fields filled
  (`1000.00` / `2000.00`). The only requests are that screen's own two: `GET /finance/settings` and
  `GET /commitments?month=2026-10`.
- **The `Bills still due this month` row** closes the breakdown and opens the commitments sheet (one request,
  `GET /commitments?month=2026-10`; 3 rows; `October 2026 · RM 54.90 still due`). That row is the commitments
  sheet's way in now that the card itself opens the breakdown.

**`Try again` (state `fail`), requests per click: exactly 1 — `GET /finance/summary?month=2026-10&mode=personal`
and nothing else.** With the API answering again the card repaints in place: `RM 1,400.00`, `RM 945.10`,
`RM 54.90 still due this month`, the retry row hides again, the tap area is re-enabled, and the budget card comes
back at `65% of RM 2,000.00`. (Harness caveat: the `fail` state has no finance object at all, so the first retry
was answered with a `null` body — one request, and the page stayed in its error state rather than crashing visibly.
The second retry, against a real-shaped body, is the one recorded above.)

**The anchor's round trip, measured in state `setup`:** typing `1250.00` previewed `Starting balance will be
RM 850.00`; `Save` sent `PUT /finance/settings {"opening_balance": 850}`, then one `GET /finance/summary` — and the
card read **`RM 1,250.00`**, the figure the owner typed. Preview cases: `1,250 → RM 850.00`, `-80 → −RM 480.00`,
`0.10 → −RM 399.90` (the drift case, exact), `abc`/empty → the hint line instead of a figure. The field computes
**16px** (a bare `.money-field-input` rule lost to `.field`'s later `font: inherit` and computed 17px; the selector
is now `.sheet .money-field-input`, and 17px would still be above the 16px zoom floor, so nothing ever zoomed).

**The edge case, stated rather than hidden:** an anchor that computes to **exactly 0** is saved as computed and
never nudged (no `x − 0.01`). `opening_balance == 0` is also the only signal for "not set", so the card then goes
back to asking for the balance. That is honest — the prompt is one tap from being redone — and it is very unlikely
to be reached, because the figure the owner types gets the month's income and spending added back out of it.

**Tests.** `306 passed, 21 skipped` (baseline was `304 passed, 21 skipped`). The seven pins that went stale with
the redesign were rewritten, not added; two tests are new: the anchor maths (a **Python mirror** of the JS
`toCents`/`openingFor` — the page's JS is neither exported nor executed by the suite, so the mirror is kept honest
by three string pins on the formula; cases: negative typed, `0.1 + 0.2`, `12,345,678.90`, exactly zero, comma
tolerance, unreadable input) and the registration of the two new sheets (`openOverlay`/`attachSheetDrag`/
`isOutsideTap`, the 16px field, the six breakdown rows).

**One fragile pin was repaired, not a regression.** `test_sign_out_clears_the_session_and_the_cached_rows` read
`clearCaches` through a fixed 1400-character slice; the six lines this pass added pushed `hideBudget();` past it
and the test failed while nothing about sign-out changed. It now takes the whole function with a brace-matching
helper (`function_body`), and pins the balance card's three reset nodes too.

**Not verified:** **no iPhone and no real touch** — every interaction above is a DOM `click`/`input` event
dispatched inside the harness iframe in desktop Chromium, so nothing here is a swipe, a keyboard, a zoom or a
safe-area measurement; no real API, no staging and no live database (every figure is the stub's); nothing saved
through the real backend; the anchor maths test mirrors the JS rather than running it; and `showMoneySettings`'
smooth scroll settles with the Money section 6px above the viewport top (pre-existing, unrelated to this pass, and
it leaves the helper line fully visible).

**For the phone pass (unrun, on a real iPhone):**
1. **The anchor.** Fresh account (or Settings → Money, empty the opening balance): tap `Set your balance`, type
   `1250`, check the preview says `Starting balance will be RM 850.00` and that the keyboard does not zoom the
   page (16px field), then `Save` — the card should read `RM 1,250.00` and the sheet should be gone.
2. **The breakdown.** Tap the Balance figure: the sheet must open with a tap anywhere on the area (label, number,
   pill or the line under it), drag down from the header must dismiss it, and `Edit my balance` must stack the
   anchor over it and come back.
3. **The budget offer and the retry.** With no budget, check the dashed card and that the button opens the
   one-field sheet; kill the connection (or leave the tab offline) and reopen Home to see `Try again` — tapping it
   once must repaint the card without a full reload.

## 2026-10-19 — Smart Entry as a row, shorter income/expense labels (UI only)

- **Smart Entry** is one row (bolt, label, chevron), the same `.add-row` as Scan Receipt. Its field and Add open
  under it. Collapsed card **100.95px → 48px** (375 and 390, clone measure). Open card **128px**.
- **Income / Expenses** cards lost "· this month". Both are **92.74px → 75.2px** (clone, 375 and 390), labels on one
  line, amounts aligned at 35.55px from the top. Real desktop page: 72.19px in both themes.
- **Autocomplete:** the commitment name, Merchant and Note already carried `autocomplete="off"`; now pinned, not added.
  Smart Entry's field (`textInput`) does not have it.
- **Not done, found on the way:** the commitment name, Merchant and Note inputs are still 38px (`.add-field`), under
  the 44px touch floor. They share the class with the Manual sheet, which is not decided yet.
- **Not verified:** iPhone, touch, keyboard, safe-area. Harness: DOM clicks in desktop Chromium.

## 2026-10-19 — Manual in two steps, a 65% sheet, and the iOS keyboard (UI only)

**Branch `feat/budget-balance-commitments`, UI only — `app/static/index.html` (the change),
`tests/test_static.py` (the pins).** No `app/*.py`, no `schema.sql`, no `migrations/`, no `.env*`, no API, no
SQL; nothing pushed, and nothing touched on staging or live. Three commits: the Manual split + `65dvh`, the
keyboard lift + centring, and this docs pass.

- **Manual is two steps.** Step 1 is *Expense/Income*, the amount and the three pills, with the keypad as the
  sheet's last row; **Details** switches to step 2 — Merchant, Note and the category chips — which rises in
  place (step 1 is hidden, not overlaid) and carries its own Back to step 1. Only one step is in the sheet at a
  time, and every open starts on step 1. The keypad is derived from state, never remembered: it is on screen
  only in step 1 and only while neither text field holds the caret.
- **Manual is `65dvh`** (dvh, not vh). Because 65% of a phone is under the 640px container-query threshold, the
  keypad keys are 44px and the amount font 44px at both target sizes, and step 1 fits with no scroll.
- **Merchant and Note are 44px** (16px text). The commitment name/amount/day fields are still 38px
  (`.add-field`) and the pills/Back are 34px: raising those breaks step 1 at 375×667 (measured: 29px of
  overflow), so they keep the sizes the sheet was tuned with.
- **The keyboard now moves the sheet.** `--kb` = `innerHeight - visualViewport.height -
  visualViewport.offsetTop`, clamped to `0` below 80px. It sets each sheet's `bottom` (and every overlay's
  bottom padding) and clamps `max-height`, so the sheet sits above the keys with its top still at
  `--sheet-top-gap`. Focusing a sheet field (Merchant, Note, the commitment fields, the edit form's rows)
  centres it about 300ms later by moving the sheet's own `scrollTop`; the window and the page behind stay
  scroll-locked. `--kb` resets when the keyboard closes and when a sheet closes.

**Measured, this session, in desktop Chromium with `fetch` stubbed** — a clone of `#addSheet` in a fixed-size
wrapper, because the tool cannot change the real viewport; DOM clicks, not touches. Step 1 with `RM 12,345.67`
in both themes, `scrollHeight == clientHeight` (no overflow):

| size | sheet (`65dvh`) | step 1 | amount | keys |
| --- | --- | --- | --- | --- |
| 375×667 | **433.55px** | 152px, no overflow | 42.05px, 44px font | 44px |
| 390×844 | **548.59px** | 267px, no overflow | 157.09px, 44px font (slack) | 44px |

Step 2 at both sizes: 44px fields at 16px, `scrollHeight == clientHeight`, no overflow. Live page (a 939px
desktop viewport): chooser **251px**, Manual **610.34px**, AI **845.09px**.

**The keyboard was simulated, not real.** `visualViewport.height` was overridden to `innerHeight - 320` and a
`resize` dispatched. Add sheet on step 2 (Merchant focused): `--kb: 320px`, the sheet's bottom 320px above the
viewport bottom, height clamped to 525.09px, top at 93.91px (the gap). The txn edit sheet lifted the same way
and its own `scrollTop` moved 0 → 31, so `#editMerchant` ended up centred (0.2px off) with `window.scrollY`
still 0. The commitments sheet's bottom moved 927 → 607 (exactly 320px) and its name field stayed visible above
the keys. Closing a sheet dropped `--kb` back to `0px`. `pytest`: `317 passed, 21 skipped`.

**NOT verified — `belum disahkan pada peranti`.** (1) **No iPhone and no real iOS keyboard**: the height above
is a faked `visualViewport`, so the real inset, the keyboard's own animation, whether `dvh` really stays put
with the keyboard up, and whether the sheet lands where the keys actually are are all unmeasured. (2) **No real
touch** — the step switch, the keypad hiding on focus and the drag-to-dismiss were DOM events. (3) **No
safe-area insets** (`--sat`/`--sab` were 0, as on a desktop). (4) No staging, no live, no write anywhere. (5)
`pytest` is the only automated check; the UI numbers come from a scratch harness that is not in the repo.


## 2026-10-19 — Manual as one Stitch-style screen, and the category sheet (UI only)

**Branch `feat/budget-balance-commitments`; UI only.** Files: `app/static/index.html` (the change), `tests/test_static.py`
and `tests/test_page_auth.py` (the pins), and these docs. No `app/*.py`, no `schema.sql`, no migration, no API or SQL
change; nothing pushed, nothing touched on staging or live.

- **Manual is one screen.** The two steps and the Details pill are gone: every field Details held sits on the screen
  (Merchant, Date, Mode, Note as the four rows of the card, the categories as the chip row). Order: Back and
  Expense/Income, the amount (`RM`, caret) and the *Malaysian Ringgit* pill, CATEGORY with **View All**, the chips,
  the card, the keypad.
- **The 65% decision is superseded.** The reference stack does not fit in 65dvh. Manual is the full sheet now.
- **Only Manual's middle scrolls, and only on a short phone.** The keypad is pinned and its keys are 44px everywhere
  (the 56px keys of a tall screen are overridden for Manual). The card is one `.add-card` of four 48px label rows.
- **Back** moved to a 44px chevron beside the type control. **Cancel** is unchanged.
- **View All** opens a plain category sheet (`#catOverlay`) over the Add sheet. A tap picks and closes the list only.
- **Note** is still `raw_extraction.note`. The payload keys did not change: the same seven keys with or without a note
  (`note` is `null` when blank). The Add sheet is never used for editing, and the edit sheet does not show the note,
  so there is no read path to reuse. Adding one is a separate decision.

**Measured in desktop Chromium** — the app's own page in a `srcdoc` iframe at the real layout size (375×667 and
390×844), both themes, `fetch` stubbed with a fake session, DOM clicks. Keypad pinned at the bottom in every case.

| size | theme | sheet | body (visible / needed) | keypad | keys |
| --- | --- | --- | --- | --- | --- |
| 375×667 | light, dark | 600.3px | 317 / 450 — scrolls 133px | 456.5–667 (210.5px) | 44px |
| 390×844 | light, dark | 759.59px | 468 / 468 — no scroll | 625.5–844 (218.5px) | 44px |

Both sizes: no horizontal page overflow, nothing off-screen outside the chip row, Save disabled until an amount, the
chip row overflows (9 chips, 1097px) with the last chip cut at the edge, inputs 16px, Back / segmented / View All 44px.

Payloads, from the stub: with a note `{amount, category, merchant, mode, note, txn_date, type}`; without one the same
keys with `null`s. Pay posts `POST /transactions` (1200, bills, "Sewa rumah"), then `POST /commitments/c1/paid` with
`{month}`, in that order.

**Simulated, not real.** The harness window had no focus, so native focus never fired; the merchant/note keypad rule
was exercised with dispatched `focus`/`blur` events on the fields. The keyboard lift is not part of this run.

**NOT verified — `belum disahkan pada peranti`.**
1. No iPhone. No real iOS keyboard: the keypad hiding on a real focus, the lift, the centring, and whether the body
   stays put with the keyboard up.
2. No real touch: Manual's body scroll against the sheet's swipe-to-dismiss (the `scrolledInside` gate) is untested.
3. Safe-area insets were 0 (a desktop); the keypad's bottom padding under the home indicator is unmeasured.
4. The caret blink, the native date picker over the row, and the input's ellipsis for a long merchant or note
   on iOS Safari.
5. The View All list at 375×667 (587px, fits) was measured only in the desktop harness.

**Open, for the owner's call.** At 375×667 the card's lower rows (Date, Mode, Note) sit below the fold and scroll
inside the sheet. The reference stack needs about 140px more than that screen has while the keys stay at 44px. Options
are a smaller amount on short screens, dropping the currency pill below a height, or 40px keys. None is made here.

**Same-day follow-up — the cramped screen, resolved.** View All (and its category sheet) and the Malaysian Ringgit
pill came out; the card rows are 44px; the Mode toggle paints 32px inside its 44px box; the keypad's chrome tightened
around the same 44px keys; the chosen chip now scrolls into view with the previous chip peeking. The whole form fits
375×667 (card bottom 466.4px against a keypad top of 467.5px) and 390×844 with nothing scrolling. Currency still
stamps `MYR` server-side; the client payload keys are unchanged. Merchant carries `spellcheck="false"
autocorrect="off"`.
