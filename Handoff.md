After completing each coding task, generate or update `HANDOFF.md` for the next AI orchestrator.

Keep it concise and factual. Include:

1. **Task:** Original objective and current status.
2. **Changes:** Files modified, key implementation decisions, and why.
3. **Validation:** Tests executed and their actual results.
4. **Unresolved issues:** Errors, incomplete work, risks, and blockers.
5. **Next steps:** Recommended next actions in priority order.
6. **Instructions for the orchestrator:** Decisions requiring review and questions that must be answered before further implementation.

Do not paste entire source files, repeat unchanged project documentation, or claim that tests passed unless they were actually executed.

Preserve relevant technical details and exact error messages. Update the existing handoff rather than creating a new report after every task.

---

# HANDOFF — 2026-10-14

## 1. Task

Phase 1 of `duits-money-management`: FastAPI + Supabase backend, plus a single-file, iPhone-first web UI
(`app/static/index.html`) built from the five Stitch screens in `design/` (HOME, TRANSACTION, INSIGHT,
SETTINGS, ADD NEW TRANSACTION). **All five screens are built and in use.**

Completed since the last handoff (all verified, see §3):

- **Add sheet save path + one-screen layout.** "Save does nothing" traced to a *stale server process*:
  the listener on `:8000` predated the route, answering `405` (while `GET /transactions` and
  `POST /transactions/text` answered `401`, proving the routes existed). Client code was already
  correct. The real bug was positional: the error card rendered below the fold behind the keypad, so
  every failure now also raises a red toast and a card floating above the keys (`#addNotice`).
- **Home "By category"** replaced with a compact donut; Home and Insights share one `donutSvg()` and one
  `expenseSummary()`, so their totals and colours cannot drift.
- **Dark mode**: Settings → *Appearance* (System / Light / Dark), stored in `localStorage.duitstheme`,
  applied live with no reload; System follows the phone and reacts to `prefers-color-scheme` changes.
- **Add sheet reordered** to: header → Expense/Income → amount → pills → Details → chips →
  **Smart Entry row → Scan Receipt row** → keypad. The old side-by-side button row is gone.
- **Real app icon.** The canvas-drawn touch icon is gone. `app/static/logo.png` (the saved 3D frosted
  wallet, flattened to opaque white) plus three `apple-touch-icon*` copies at 180/152/120 are served
  publicly from four routes, linked from `<head>` with a `?v=` cache-buster, and the same artwork is
  the 24px mark beside the `Duits` wordmark in the sticky top bar.
- **Home Screen icon cache busted.** Re-adding the shortcut still showed the old tile: the icon had
  **no `Cache-Control` at all** (Safari heuristic-cached it), the links had no version query (iOS keys
  its cached icon on the URL), and `GET /` was heuristically cacheable too, so the shortcut could be
  built from old markup. Icons now send `public, max-age=600` (never `immutable`), every icon href
  carries `?v=2`, and `GET /` sends `no-cache`.
- **iOS zoom + Smart Entry row.** The "field and Add button cut off on the right" was not a layout bug:
  the Smart Entry input was **15px**, and iOS zooms the whole page in when a focused control is under
  16px, which is what pushed the right-hand edge off screen. Measured first: `overflow=0` on every
  screen and the input's right edge at 345 of 375. Fixed by a 16px floor on every focusable control, a
  `touch-action: manipulation` / no-text-select pass, and turning Smart Entry into one card.

## 2. Changes

Files touched (this task: `app/static/index.html` and the docs only — no backend, no API):
`app/static/index.html` (HTML + CSS + vanilla JS, no build step, served by the API at
`GET /`), `app/main.py` (one `_icon()` helper + four public icon routes, and `no-cache` on `GET /`),
`app/static/logo.png` and the three `app/static/apple-touch-icon*.png` files, `tests/test_static.py`,
`README.md`, and this `Handoff.md`.

Decisions worth knowing:

- **Theme**: every colour is a CSS variable — light on `:root`, dark on `[data-theme="dark"]`, set on
  `<html>` by a tiny inline `<head>` script *before* first paint (no white flash) and mirrored into
  `<meta name="theme-color">`, the iOS status-bar style and `color-scheme`. Category hues are unchanged by
  design and arrive via an inline `--cat`; `tint()` reads its alpha from CSS (`--tint-alpha`, .14 light /
  .18 dark) so the palette has one home. Tint boxes and donut slices take colour from `--cat`, never a
  literal.
- **Add sheet**: fills the screen (`100dvh` minus safe areas, `overflow: hidden`, `max-height: none`
  forced on `#addSheet` because the later `.sheet` rule would otherwise win) and never scrolls at the two
  target sizes **except in the named states below**. The **amount is the only flexible row** (`flex: 1`,
  centred, `min-height: 1.4em` — `overflow: hidden` alone lets a flex item collapse and hide the number).
  When height runs short the layout gives way in a fixed order: amount font
  (`clamp(40px, 8.8vh, 56px)`) → key height (48 → 44px below 620px) → and only below 660px may the
  content column scroll. Four things may scroll, each for a reason: the expanded **Details** block, that
  sub-660px escape, the keyboard state (`html[data-keyboard]`, capped to `--vvh`), and the Smart Entry
  card open while the keyboard is dismissed (32px taller than the old row, so at 375×667 the column
  scrolls instead of hiding Scan Receipt behind the keys). Smart Entry is **one card** — 48px header row,
  12px, then field + fixed-width `Add` (10px gap, field `flex: 1; min-width: 0`), the card carrying 14px
  of padding while the row inside goes transparent. Both action rows sit 12px apart. Any focused text
  field hides the keypad, re-derived from `document.activeElement` by one `paintKeypad()` rather than
  remembered from focus events. The Scan privacy hint appears only after tapping Scan Receipt.
- **Icon**: the file the user saved had **no white background** — 1254×1254 RGBA with `alpha=0` at all
  four corners, which iOS paints black on the Home Screen. It was composited onto solid `#FFFFFF` and
  downscaled to **180×180** (the size iOS asks for) in place: 575,869 bytes → 10,045. `logo.png` is now
  the committed master; `apple-touch-icon.png` is a byte-identical copy of it, and the 152 and 120 files
  are Lanczos downscales of it (8,117 and 5,355 bytes) — all RGB, square, corners `255,255,255`.
  Every route is `include_in_schema=False` and public like `GET /` (public is what makes the icon load
  for a shortcut that has no API key yet), and the middleware keeps adding `nosniff` + `Referrer-Policy`.
  The old data-URI SVG favicon and the `buildAppIcon()` canvas (which had been drawing "RM" on a blue
  squircle from `--accent`) are deleted — `getContext` remains only in the receipt downscaler.
- **Cache headers**: `Cache-Control: public, max-age=600` on the four icons, `no-cache` on `GET /`.
  Measured on the running server: `GET /` → `cache-control: no-cache` + ETag, `/apple-touch-icon.png?v=2`
  → 200 `image/png` with `max-age=600` and the hardening headers. Note Starlette 1.7's `FileResponse`
  emits an ETag but **does not answer `If-None-Match` with 304** (verified in-process and over HTTP), so a
  page load re-sends all 134 KB. Accepted: freshness is what fixes the icon, and the payload is small.
- **Brand mark**: `.brand-mark` is 24px/radius 6px with a `.5px` hairline (`--line`) so its white tile
  stays defined on the dark bar. Measured: the bar is 52px with *and* without the mark (the refresh
  button is 34px, the mark shorter), no overflow at 375 or 390 — nothing downstream can shift.
- **iOS touch/zoom rules**: a **16px floor on every control a finger can focus** (`.add-field`,
  `.search-field input`, and the invisible `font-size: 16px` date input — `.field` inherits the 17px
  body), `maximum-scale=1` in the viewport meta (belt, not braces: iOS has ignored it for pinch since
  iOS 10, so pinch still works), `touch-action: manipulation` on `html`/`body`/`button`/the date
  `<label>` (the drag handle keeps `none`), `user-select: none` + `-webkit-touch-callout: none` on keys
  and buttons only, and `html, body { overflow-x: hidden; max-width: 100vw }`. No transform is used to
  shrink anything.
- **Keyboard reveal**: `revealFocusedField()` is the one new bit of behaviour. It hangs off
  `window.visualViewport` (`resize` + `scroll`), treats `innerHeight - viewport.height > 120` as "the
  keyboard is up", sets `html[data-keyboard]` + `--vvh` so the sheet caps itself to the visible strip,
  and then scrolls the focused field the remaining pixels into view (`scroller.scrollTop += hidden`, or
  `window.scrollBy`). Scroll only — no zoom, no transform. Both are torn down when the keyboard closes.
  `paintKeypad()`, `toggleSmartEntry()` and every handler/id are unchanged.
- **No logic changed by the last four tasks** — every element id (`#smartRow`, `#smartEntry`, `#scanBtn`,
  `#scanHint`, `#addDetails`, `#addAmount`, …) was preserved, so the existing handlers, the `addSaving`
  re-entry guard and the "Save disabled until amount > 0" rule are untouched.

## 3. Validation (all executed this session)

- `pytest -q` → **83 passed** (0.31s) — the 75 original tests plus 8 in `tests/test_static.py`
  (four icon URLs public + `image/png` + `max-age=600` + byte-identical to disk; not in the schema;
  `GET /` `no-cache` with an ETag; each file alpha-free and square at 180/180/152/120; and every icon
  link in the page versioned and really served).
- `/tmp/duits-ui-check.js` (Node harness that evals the extracted `<script>`) → **671 assertions pass**,
  including: no colour literal anywhere in the stylesheet or script outside the two palette blocks and the
  two hue constants; the pre-paint script's position and `try/catch`; the exact dark palette values; the
  Add sheet order; 12/8/12px gaps and 48px rows; the four states that may scroll (`.add-details`, the
  sub-660px escape, `html[data-keyboard]`, `html:has(.add-row.is-open)`); the 44px key step; threshold
  derivations (amount still 56px at 667, keys still 48px at 667); the 16px floor on every focusable
  control; `touch-action: manipulation`; and that `revealFocusedField()` scrolls and never zooms.
- Real-browser fit probe (iframe = exact viewport) at **375×667** and **390×844**, five states each:
  `orderOk=true`, `sheetScroll=false`, clipped elements `[]`, amount 56px, gaps 12/8/12, rows 48/48, keys
  48/48 (667) and 56/56 (844), keypad bottom == sheet bottom, Save disabled at RM 0.00 and enabled at
  RM 12.50. Nothing is clipped in any state; the one state with overflow is the Smart Entry card open
  with the keyboard dismissed at 667, and there the column scrolls (`contentClips=false`).
- Touch probe at 375×667 (screens + sheet states): `overflow=0` and nothing crossing the viewport edge
  except the category chips, which scroll horizontally by design. Computed control fonts: `addDate 16,
  addMerchant 16, addNote 16, textInput 16, txnSearch 16, keyInput 17` (the only sub-16 is the hidden
  file input, which cannot be focused). Computed `touch-action=manipulation` on `html`, `body`, `.key`,
  `.cat-chip`, `.tab`, `.add-row`, `.icon-btn`; `user-select: none` on keys and rows, `auto` on inputs.
  Smart Entry card: `padTop 14 padX 14 radius 16 bg --card-2`, header→field 12, field|button 10,
  card→Scan 12, field 239px + button 66px inside a 359px-wide card.
- Simulated keyboard (real browser, `visualViewport.height` faked to 380 with `innerHeight` left at 667,
  as iOS does): `attr=true`, `--vvh=380px`, sheet capped 602→380, `overflowY=auto`, `scrollTop` moved 23px,
  focused field bottom 368 ≤ 380 (visible), Add button right edge 345 ≤ 375 (visible). Closing it removes
  the attribute and `--vvh` and restores the sheet to 602px with `overflowY=visible`.
- Both-theme screen audit (17 states each: Home, Transactions, Insights week/month, Settings, Add sheet
  keypad/chips/Details/Smart Entry/warn toast/error card, edit sheet, month wheel, three empty states,
  error card, key dialog): dark → **0 light boxes, 0 low-contrast text (worst 3.6:1)**; light → only the
  pre-existing `#8E8E93`-on-page-background 2.9:1 items. The detector is calibrated: two deliberately
  invisible samples are always flagged (worst 1.1:1) — before that check it silently reported `NaN` as a
  pass. Re-run after the top-bar/icon change (Home, both themes): dark → 0 light boxes, 0 low-contrast
  (worst 4.7:1); light → only the same pre-existing items; calibration still flags 2. Re-run again
  after the Smart Entry card change (all 17 states): dark → 0/0 in every Add-sheet state (worst 3.6:1),
  light → the same six pre-existing 2.9:1 `#8E8E93` items, no new ones.
- Served app (after `./ctl.sh restart`, so the new routes are live): all four icons → **200, `image/png`,
  `public, max-age=600`, no `X-API-Key`**, with `nosniff` + `Referrer-Policy` (`/logo.png` 10,045 b,
  `apple-touch-icon.png` 10,045 b, `-152x152` 8,117 b, `-120x120` 5,355 b; the `?v=2` form serves the same
  bytes with the same headers, and the served 180×180 is byte-identical to disk). `GET /` → 200 (134,624 b)
  with `cache-control: no-cache` and all four versioned `<link>` tags. `uvicorn` running; LAN IP
  **192.168.1.12** (phone URL `http://192.168.1.12:8000/`).
- In-browser brand check (375×667 and 390×844): `mark=24x24 radius=6px loaded=180x180`, bar height 52px
  with and without the mark (`barHeightMoved=false`), `barOverflow=no`, refresh button still 34px.

## 4. Unresolved issues / risks

- **iOS Home Screen icon caching cannot be verified from here** (no device). The `?v=` link is the
  standard cure because iOS keys the cached icon on the URL, but if a phone still shows the old tile
  after a hard refresh and a re-add, the next thing to try is deleting the shortcut, force-quitting
  Safari, then re-adding — iOS keeps icon caches outside the page cache.
- **`app/static/logo.png` was rewritten in place** (opaque white + 180×180). If the 1254×1254 master is
  only on the developer's machine, the high-resolution original no longer exists in the repo — keep a
  master elsewhere if it will be re-exported.
- **Never tested on the real iPhone** (no device access from the sandbox): iOS keyboard vs the built-in
  keypad, the native date picker inside the sheet, real `env(safe-area-inset-*)`, the camera path, HEIC.
  From this task specifically: whether Safari really stops zooming on a focused field now that every
  control is 16px, whether it honours `maximum-scale=1`, whether a double tap on the keypad does
  anything, and how `revealFocusedField()` behaves against a real keyboard — its geometry could only
  be simulated by faking `visualViewport.height` (380px) while leaving `innerHeight` at 667.
- **The verification harness lives in `/tmp`** (`duits-ui-check.js`, `build-preview.py`, `mkfit3.py`,
  `mk*.py`, all screenshots) — **not in the repo**, lost on reboot.
- **Insights `Year` is blocked on the API**: `/transactions/summary` accepts only `month`
  (`app/main.py:281`); there is no `?from=&to=` range endpoint, so a Year segment or a true range total
  cannot be built client-side without faking it. The markup carries a comment saying exactly this.
- **`.env.example` is missing `CLAUDE_FALLBACK_MODEL`** even though `app/config.py:17,86` defaults it
  (`claude-sonnet-5-5`) and `app/extractor.py:114` uses it — a deployment copying `.env.example` silently
  gets the default.
- **Add-sheet shortcut below the targets**: a 320×568-class screen with Details open cannot fit two 48px
  rows + chips + 44px keys + a legible number, so below 660px the content column may scroll. Both target
  sizes are clear of it, but it is a conscious deviation from a literal "never scroll". New in this
  task: at 375×667 the same column scrolls when the Smart Entry card is open while the keyboard is
  dismissed (keypad back on screen) — the card is 32px taller than the row it replaced, and scrolling
  beats hiding Scan Receipt behind the keys.
- Cosmetic ceilings accepted on Home's donut: a slice under ~2% renders as the minimum round dot; the
  legend folds the tail into a grey `Others`, so a month with both a real `other` category and a grouped
  tail shows `Other` *and* `Others`; a 6-figure total would touch the ring (hole sized for ~10 chars).

## 5. Next steps (priority order)

1. Move the UI harness and probes into the repo (e.g. `tools/ui-check.js`, `tools/preview.py`) so the
   regression suite survives, and document how to run them in the README.
2. iPhone pass on `http://192.168.1.12:8000/` (hard refresh once): no zoom when the Smart Entry field is
   tapped and nothing shifting sideways, no double-tap zoom on the keypad, the Add button reachable on
   the real keyboard, then keyboard vs keypad collapse, chips momentum, the date picker inside the sheet,
   safe areas, one receipt scan end to end.
3. Add `CLAUDE_FALLBACK_MODEL` to `.env.example` (one line, matching `config.py`).
4. API work to unlock the deferred UI: a summary/list range endpoint (`?from=&to=`) → Insights `Year`,
   true cross-month range totals, Home-vs-ring count alignment for ranges.
5. Product decisions still open: where notes live (column vs `raw_extraction.note`) and whether users can
   add custom categories.
6. Optional polish: donut slice minimum, `Others`/`Other` collision, ring hole sizing for 6-figure totals.

## 6. Instructions for the orchestrator — settle these before more UI work

- **`:has()` is now load-bearing for two rules** (`html:has(.add-row.is-open) #screen-add` and the Smart
  Entry card). It needs Safari 15.4+ / iOS 15.4+; on anything older the field still works, it just does
  not get the shared card or the scroll escape. Is iOS 15.4 an acceptable floor, or should the card get
  a class toggled from JS instead?
- **Is a 16px floor on `.add-field` the right call visually?** It is what stops the focus zoom; the
  alternative is `maximum-scale=1`, which iOS may ignore, and which would also block the user's own
  pinch-zoom.

- **Icon master**: was overwriting `logo.png` with the flattened 180×180 acceptable, or should the repo
  keep the original (e.g. `logo-master.png`) alongside the processed icon? It is one file today by design.
- **Is the ≤660px content-column scroll acceptable?** It is the only way to avoid painting over the pinned
  keys on very short screens, but it contradicts a literal "never scroll".
- **Keep the chevron on Scan Receipt?** It was requested explicitly, but that row opens a file/camera
  picker rather than navigating to a screen, so the affordance may mislead.
- **Should Details keep auto-focusing Merchant** (which hides the keypad, so the amount cannot be typed
  without dismissing the keyboard)? The behaviour is deliberate, but easy to reconsider.
- **Confirm the `--tint-alpha` reading**: 14% light / 18% dark, where 18% over `#1C1C1E` is *dimmer* than
  14% over white — the interpretation used for "about 18% so they do not glow".
- **Environment quirks to reuse**: this Mac is in Dark Mode, so *System* resolves to dark and
  `--force-dark-mode` changes nothing — force light by storing `duitstheme: "light"`. For iframe probes,
  serve `/tmp/preview` over `python3 -m http.server 8899` (file:// iframes cannot read the child
  document). Run **one headless Chrome per shell command**; chained runs fail silently and leave stale
  dump files that look like fresh results.
