# Handoff — Duits

Current state only. Rules for agents are in `AGENTS.md`. Older session logs (with their now-removed
features and unreproducible `/tmp` measurements) are in `docs/handoff-archive.md`.

**Status: this file is secondary.** Where it conflicts with `NEXT_STEPS.md`, `NEXT_STEPS.md` is
authoritative — parts of this file were written before the multi-user work and have not been re-checked.

Update this file after each coding task: keep it factual, don't paste source, and don't claim a test
passed unless you ran it in that session.

---

## 1. Status

- **Phase 1 is built and in use.** FastAPI API, Supabase storage, Claude extraction, and a single-file
  iPhone-first web UI at `/` built from the five Stitch screens in `design/`.
- **Deploy target: Render** (free web service, Docker, auto-deploy from GitHub `main`), URL
  `https://duits-money-tracking.onrender.com`. Render's free instance sleeps when idle; the first
  request after a sleep is slow (see the splash's "Waking up the server…" line).
- Last verified commit: `8f39d7e` (working tree clean before the housekeeping pass on 2026-10-16).
- **Multi-user steps 1-3 are on branch `multi-user`, not merged. The migration is rehearsed on STAGING, and NOT
  applied to live.** The live run is `docs/migration-runbook.md`; staging results are in its section 9.
  Step 2 detail follows. Every route is scoped to the caller's id from the verified Supabase JWT (`sub`). Every db helper
  requires `user_id`. The 409 duplicate path only sees the caller's rows. Receipts live under `user_id/YYYY/MM/`,
  and the owner is checked before any sign or delete. Before deploying to Render:
  1. **Migration first.** The code writes `user_id`, and the live table has no such column, so every insert fails
     until `migrations/0002_multi_user.up.sql` has run. Rehearse it on staging.
  2. **Move existing receipts.** Old objects sit at `YYYY/MM/...`. Owner checks now refuse those paths, so
     `receipt-url` and `DELETE` on the 16 existing receipt rows return 500 until a storage move (not written yet)
     has run. Nothing is lost, because the delete fails before the row is removed.
  3. **The browser has no sign-in screen yet.** `index.html` still sends `X-API-Key`. Until a login UI exists, the
     app needs `ALLOW_LEGACY_API_KEY=true` and `LEGACY_USER_ID=<owner's id>`, and the iOS Shortcut depends on the
     same flag. Personal access tokens for the Shortcut are not built.
  4. **Sign-up is still open** in the live project. Close it in the Supabase dashboard before any second user exists.
- `./.venv/bin/python -m pytest -q` — the full suite must pass; read the count from the summary it prints,
  never from a number written in a doc (this one included).
- **No automated UI test exists in the repo.** `tests/test_static.py` pins strings in the page; it does not
  run the page. See §5.

## 2. Architecture (current)

```
app/main.py         routes, error mapping, security headers, icon routes, no-store on / and API data
app/extractor.py    Claude calls: image or text -> Extraction (tool use, validated, one retry/fallback)
app/db.py           Supabase client, dedupe_hash / dedupe_hashes, insert/query/update/delete, storage
app/models.py       Pydantic models; Extraction.to_row(); account-number mask for raw_extraction
app/auth.py         X-API-Key dependency; per-IP throttle on failed attempts (10/min, 429 + Retry-After)
app/config.py       settings from env only; fails fast naming missing NAMEs, never values
app/static/index.html  the whole UI: HTML + CSS + vanilla JS, served at GET / (no-store)
app/static/logo.png, apple-touch-icon*.png  opaque white, square; served publicly
schema.sql          transactions table, (mode, txn_date) index, dedupe index, private receipts bucket
Dockerfile          python:3.11-slim, non-root uid 10001, CMD binds ${PORT:-8000}
ctl.sh              local start/stop/restart/status/logs (no --reload; reports stale process)
tests/              pytest: dedupe, models, auth, extractor, endpoints, bank screenshots, production, static
docs/               handoff-archive.md (old session logs)
```

**API** (all but `/health` and the icons need `X-API-Key`): `POST /transactions/scan`,
`POST /transactions/text`, `POST /transactions`, `GET /transactions?month&mode`, `GET|PATCH|DELETE
/transactions/{id}`, `GET /transactions/{id}/receipt-url`, `GET /summary?month&mode`, `GET /health`.
Status codes: 400 bad file/month, 401, 409 duplicate (`{"error":"duplicate","message":"Already recorded.",...}`),
413 over `MAX_UPLOAD_BYTES`, 422 extraction failed or bad body, 502 Claude/Storage failure.

**Scan flow** (`/transactions/scan`): type check → size check → sha256 of the bytes → if seen, 409 (no
Claude call) → Claude extraction → if `document_kind == "bank_screenshot"`: **no upload**, `source =
bank_screenshot`, `receipt_path = NULL`; else upload to `receipts` (`source = receipt_scan`) → insert →
on any insert failure or duplicate, the uploaded object is deleted.

**Dedupe** (only scans dedupe; text and merchant-less rows store `dedupe_hash = NULL`, so they always insert):
- receipt: sha256 of `txn_date|amount(2dp)|lowercased merchant`;
- screenshot with a reference: `ref|<REFERENCE>` (uppercased, whitespace stripped), ignoring amount and time;
- screenshot without a reference: day key plus a ten-minute window; the lookup also probes the
  neighbouring windows (`dedupe_hashes` / `find_by_dedupe_hashes`), so 14:29 and 14:33 collide.
- Manual `POST /transactions` goes through the same `_insert` guard, but manual rows carry no hash, so
  two identical manual entries both insert.

**Edits**: `PATCH` sets `raw_extraction.needs_review = false` and recomputes `dedupe_hash`.

**Caching**: `/transactions*` and `/summary` → `Cache-Control: no-store`. `GET /` → `no-store`
(the page is the only asset and carries its CSS/JS inline; a stale copy would be a stale app).
Icons → `public, max-age=600` (deliberately not `immutable`). Every response: `nosniff`, `Referrer-Policy: no-referrer`.

**UI structure** (`index.html`):
- Pre-paint script in `<head>` sets `data-theme` (System/Light/Dark from `localStorage.duitstheme`), the
  `theme-color` meta, and the status-bar style (`black-translucent` dark, `default` light).
- Splash (first thing in `<body>`): `SPLASH_MIN_MS 1200`, "Waking up" line after `SPLASH_WAKING_MS 4000`,
  hard backstop `SPLASH_MAX_MS 60000`, WAAPI fade `SPLASH_FADE_MS 300`. One-way per page load.
- Shared header `screenHeaderHtml()` on Home / Transactions / Insights: title, `Oct 2026 ⌄` month pill
  (opens our own wheel, not `<input type="month">`), Personal/Business toggle.
- Tabs: Home, Transactions, raised `+` (Add sheet), Insights, Settings. Insights computes everything in the
  browser from `GET /transactions` rows; Week = stitched from whole months, filtered client-side.
- Sheets: Add, detail/edit, month wheel, key dialog. Mounted permanently, each with a `.scrim` child layer.
  `openOverlay`/`closeOverlay` use WAAPI, a close token and a 500ms fallback. `attachSheetDrag` does swipe-to-dismiss.
- Add sheet: header → Smart Entry card (`POST /transactions/text`) → Expense/Income → amount → pills → chips →
  Scan Receipt → keypad. Fixed bottom sheet, never resizes for the keyboard, never scrolls. Shrink order via
  container queries: amount font, key height, gaps.
- Save: `afterAdd()` waits for the sheet's close and both lists, then `flashRow(id)` highlights the row.
- Scan Receipt: the browser downscales to 1600px, re-encodes JPEG q0.85 (strips EXIF/GPS, HEIC → JPEG), then uploads.
- Settings → About → **Build** row: the git short hash stamped by `GET /` (`dev` locally), plus status-bar
  style and standalone flag.

## 3. Decisions that still hold

- **Sheets never fade.** The dim is the `.scrim` layer; the only opacity animation inside an overlay is on
  that layer. Animate `transform` on the sheet.
- **Animations use WAAPI, and `replay(el, className)` restarts CSS animations.** iOS plays CSS transitions on
  `display` changes only once.
- **Tap guards are target-based.** A chip tap re-renders the chips row, which detaches the tapped node; a
  `closest(".sheet")` check then wrongly reads "outside" and closes the sheet.
- **Drag thresholds:** claim after >8px and `|dy| > |dx|`; `setPointerCapture` only at claim time; close on
  `dy > 120px` or velocity > 0.5 px/ms; otherwise spring back in 250ms. Allow list `DRAG_SURFACES`, deny list
  `DRAG_BLOCKERS` (inputs, buttons, chips, keypad, `.kv`, `.no-drag`…). A sheet that is scrolled keeps its gesture.
- **One Save in the Add sheet (header).** The thumb-reach Save pill was reverted in `8f39d7e`.
- **No `visualViewport`, no `--vvh`, no scroll-into-view in the Add sheet.** The keypad stays where it is, and
  the keyboard covers its lower half while typing. This is a deliberate trade: keys are unreachable until the
  keyboard is dismissed. `focus({ preventScroll: true })` everywhere.
- **Text inputs are ≥16px** so iOS does not zoom on focus. `touch-action: manipulation` on `html`, `body`,
  `button`, date label. Swipe surfaces use `touch-action: none`.
- **`--sat/--sab/--sal/--sar`** are the only `env(safe-area-inset-*)` reads.
- **Status bar:** `black-translucent` for dark (white glyphs), `default` for light (black glyphs). Both values are
  set before first paint. Whether iOS re-reads the meta on relaunch is unverified (§6).
- **Icons:** `logo.png` is the flattened 180×180 master (opaque white). The original 1254px image is not in the
  repo. Public routes; links carry `?v=2`. **Bump `?v=` when the icon art changes**, or the phone keeps the old tile.
- **Every colour is a CSS variable**; no colour literals outside the two palette blocks.
- **Insights Year is not built.** The API has only `?month=`; it needs a `?from=&to=` endpoint first.
- **Unreadable amount → 422**, not a saved row with `needs_review`, because `amount` is `NOT NULL`.
- **Screenshot images are not kept**, but `image_hash` is still stored for them. Review this if unwanted.
- **Account-like numbers** (8+ digits, optionally grouped) in `raw_extraction` are masked before insert.

## 4. Verification status

| Area | Status |
| --- | --- |
| API, dedupe, models, auth, extractor, production switches, bank-screenshot plumbing | `pytest` green (96) with Claude and Supabase stubbed |
| Static page pins (strings and ordering in `index.html`) | `tests/test_static.py`, 12 tests, in pytest |
| Layout at 375×667, 390×844, 430×932; sheet geometry; overflow; dark-mode contrast | **Measured in earlier sessions in headless Chrome.** Not reproducible now: the scripts were in `/tmp`, which is gone |
| Taps, drag, animations, splash timing, save flash | Same: measured over CDP in earlier sessions; not reproducible from the repo |
| Real Claude output on real receipts and bank screenshots | **Not verified.** Needs a real key and real images, which are deliberately not in the repo |
| Anything on a real iPhone | **Not verified** (see §5) |

## 5. Open issues

**Could not be verified on a real iPhone** (everything above was desktop Chrome, emulated touch, or stubbed):
- Safari's own Web Animations timing, the feel of the curve, 60fps.
- The keyboard: whether iOS leaves `100dvh` alone; the keypad being covered while typing; a double tap on keys.
- `env(safe-area-inset-*)` values (the probes simulate 47/59/34px); the real Reduce Motion switch.
- Whether iOS honours `maximum-scale=1` and the 16px floor (no focus zoom).
- Pointer gestures: whether iOS delivers `pointermove` or `pointercancel` over `pan-y` regions, and whether the
  chips row still scrolls while the sheet listens for pointers.
- Status-bar style after a standalone relaunch; the camera/HEIC path; the native date picker inside the sheet.
- The page-behind scale (`.app` at 0.96) on frosted bars: possible jank.

**Known bugs / gaps:**
- **A swipe that starts on a `.kv` row returns `pointercancel` in Chrome.** Cause not found. Title, amount and
  empty space work. Candidates: a Chrome `touch-action` quirk inside an `overflow: auto` ancestor, or iOS behaviour.
- **375×667 is a tight fit.** The sheet fits exactly after all shrink steps and has no slack; a longer label
  would clip. The amount has a `.85em` floor, so its glyphs can paint slightly outside their box.
- `isOutsideTap` depends on the `.scrim` element existing. Removing it silently narrows the outside-tap area.
- Home ring: slices under ~2% draw as a minimum dot; `Other` and `Others` can both appear; a 6-figure total
  crowds the hole.

**Not verified against the real model:** the bank-screenshot prompt (direction, merchant choice, `type` null
when unclear, account masking) has only been tested with stubbed extractions.

**Config and ops:**
- **The Build stamp is automatic.** `GET /` fills the `{{BUILD}}` placeholder in `index.html` with the git
  short hash injected by the server, or `dev` locally. Read `RENDER_GIT_COMMIT`; a 40-character SHA is
  required. Do not edit the stamp by hand.
- **`CLAUDE_FALLBACK_MODEL` default `claude-sonnet-5-5`** and **`CLAUDE_MODEL` default `claude-sonnet-4-5`**
  are in `config.py`. Check both IDs against Anthropic's model docs (`.env.example` says the same).
- **Render:** there is no `render.yaml`, so the service settings (Docker, branch, env vars, health check
  `/health`) live only in the Render dashboard. Render auto-deploys on push to `main` without waiting for tests.
- **Free instance sleep:** the first request after idle is slow. The splash shows "Waking up the server…" after
  4s. A cold start can exceed the 4s line.
- `X-Forwarded-For` is trusted for its first hop only (rate limit). Confirm the Render proxy's header behaviour
  before relying on per-IP throttling.

**Product decisions still open:** where notes live (`raw_extraction.note` vs a column); whether users can add
custom categories.

## 6. Next steps (priority order)

1. **Add automated UI tests inside the repo** (plan in §7). Until then, every UI claim is unverified by CI.
2. **Gate deploys on tests.** Run pytest in GitHub Actions on push to `main`. Render deploys do not wait for tests.
3. **iPhone pass** on `https://duits-money-tracking.onrender.com/` (hard refresh once, then delete and re-add the
   Home Screen shortcut so it loads the current page). Check: no zoom on the Smart Entry field; Add reachable
   on the real keyboard; keypad double tap; chips momentum; date picker inside the sheet; safe areas; one
   receipt scan end to end; Build row stamp matches the deployed commit.
4. **Real-model check** of the screenshot prompt with real screenshots, kept out of the repo.
5. **Verify the model IDs** in `config.py` and `.env.example` against Anthropic's docs.
6. Insights Year: needs a `?from=&to=` API endpoint first (an API change; ask before starting).
7. Optional polish: donut minimum slice, `Other`/`Others` clash, ring hole for 6-figure totals.

## 7. Test coverage gap and proposed Playwright plan

**No automated test runs the page's behaviour.** `tests/test_static.py` only checks strings and ordering in
the HTML. These behaviours have **no automated test** today:

- Sheets: open/close, close token, no stuck overlay after rapid open/close, hidden state when closed.
- Tap guards: a chip or Edit tap does not close the sheet; a scrim tap does.
- Swipe-to-dismiss: threshold, close vs spring-back, velocity, `pointercancel`, allow/deny lists, scroll gate.
- Animations: no ancestor opacity during a close; reduced motion stops movement; ring draw; save flash.
- Add sheet: keypad entry, Save disabled at zero, one POST on triple tap, 409 "Already recorded." display,
  Smart Entry post, chip toggle.
- Edit and delete: Edit → Save → one PATCH; Delete → confirm → one DELETE.
- Tabs, month change and wheel, Insights math, theme switching, splash timing, 401 re-prompt, error toasts.
- Layout: no horizontal overflow; sheet bottom at viewport; keypad visible at 375×667, 390×844, 430×932.

**Proposed plan, not implemented:**

- Use **Python Playwright** under `tests/ui/`, so the repo keeps one toolchain. Add `playwright` to
  `requirements-dev.txt`, and mark the tests (e.g. `@pytest.mark.ui`) so `pytest -m "not ui"` stays fast.
- Run the real app (`uvicorn` on a random port) and **stub the network with `page.route()`** for `/transactions*`
  and `/summary`. The stubs live in `tests/` as clearly fake fixtures, which AGENTS.md allows, and never reach the app.
- Browsers: Chromium for the main run, and **WebKit** (`playwright install webkit`) as the nearest local stand-in
  for iOS Safari. WebKit is still not an iPhone.
- Device profiles: `iPhone SE`-like 375×667, `iPhone 12`-like 390×844, 430×932. Use `reduced_motion="reduce"`
  for the reduced-motion path.
- Touch: use CDP `Input.dispatchTouchEvent` in Chromium for swipe tests. WebKit mouse events are not touch, so
  swipe tests there would be partial.
- Animation: sample `getAnimations()` and `getComputedStyle` in `requestAnimationFrame` to assert "no ancestor opacity
  below 1", and to wait for animations to finish instead of sleeping.
- Start with the sheets, tap guards and save path (highest risk), then drag, then layout. Keep the suite under ~60s.

## 8. Build stamp (implemented)

`GET /` reads `index.html` and replaces the `{{BUILD}}` placeholder with `<short sha> · fullscreen`, using
Render's `RENDER_GIT_COMMIT` (full SHA, confirmed in Render's docs). When the variable is absent, or is not a
full 40-character hex SHA, the stamp is `dev · fullscreen`. `Cache-Control: no-store` is kept. Two tests in
`tests/test_static.py` cover both cases; a value that is not a SHA is never written into the page.
Opening `index.html` from disk shows the raw `{{BUILD}}`; only the served page is filled in.

## 9. For the orchestrator

- **Build stamp automation** is done (§8): the git short hash is injected by `GET /`, `dev` locally.
- **Approve the test plan** (§7), and decide whether pytest-in-CI is wanted before the next UI change.
- **Keypad covered while typing** is a product trade-off. Revisit only if the iPhone pass says it is unusable.
- **Model IDs** in `config.py` and `.env.example` need a check against Anthropic's docs before the next scan.
