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

## 2. Changes

Files touched: `app/static/index.html` (HTML + CSS + vanilla JS, no build step, served by the API at
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
  target sizes. The **amount is the only flexible row** (`flex: 1`, centred, `min-height: 1.4em` —
  `overflow: hidden` alone lets a flex item collapse and hide the number). When height runs short the
  layout gives way in a fixed order: amount font (`clamp(40px, 8.8vh, 56px)`) → key height (48 → 44px
  below 620px) → and only below 660px may the content column scroll. Only the expanded **Details** block
  may scroll. Smart Entry expands a text field *inside its row*; any focused text field hides the keypad,
  re-derived from `document.activeElement` by one `paintKeypad()` rather than remembered from focus
  events. The Scan privacy hint appears only after tapping Scan Receipt.
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
- **No logic changed by the last three tasks** — every element id (`#smartRow`, `#smartEntry`, `#scanBtn`,
  `#scanHint`, `#addDetails`, `#addAmount`, …) was preserved, so the existing handlers, the `addSaving`
  re-entry guard and the "Save disabled until amount > 0" rule are untouched.

## 3. Validation (all executed this session)

- `pytest -q` → **83 passed** (0.31s) — the 75 original tests plus 8 in `tests/test_static.py`
  (four icon URLs public + `image/png` + `max-age=600` + byte-identical to disk; not in the schema;
  `GET /` `no-cache` with an ETag; each file alpha-free and square at 180/180/152/120; and every icon
  link in the page versioned and really served).
- `/tmp/duits-ui-check.js` (Node harness that evals the extracted `<script>`) → **647 assertions pass**,
  including: no colour literal anywhere in the stylesheet or script outside the two palette blocks and the
  two hue constants; the pre-paint script's position and `try/catch`; the exact dark palette values; the
  Add sheet order; 12/8/8px gaps and 48px rows; only `.add-details` may `overflow-y: auto`; the 44px key
  step; threshold derivations (amount still 56px at 667, keys still 48px at 667).
- Real-browser fit probe (iframe = exact viewport) at **375×667** and **390×844**, five states each:
  `orderOk=true`, `contentScroll=false`, `sheetScroll=false`, clipped elements `[]`, amount 56px, gaps
  12/8/8, rows 48/48, keys 48/48 (667) and 56/56 (844), keypad bottom == sheet bottom, Save disabled at
  RM 0.00 and enabled at RM 12.50.
- Both-theme screen audit (17 states each: Home, Transactions, Insights week/month, Settings, Add sheet
  keypad/chips/Details/Smart Entry/warn toast/error card, edit sheet, month wheel, three empty states,
  error card, key dialog): dark → **0 light boxes, 0 low-contrast text (worst 3.6:1)**; light → only the
  pre-existing `#8E8E93`-on-page-background 2.9:1 items. The detector is calibrated: two deliberately
  invisible samples are always flagged (worst 1.1:1) — before that check it silently reported `NaN` as a
  pass. Re-run after the top-bar/icon change (Home, both themes): dark → 0 light boxes, 0 low-contrast
  (worst 4.7:1); light → only the same pre-existing items; calibration still flags 2.
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
  sizes are clear of it, but it is a conscious deviation from a literal "never scroll".
- Cosmetic ceilings accepted on Home's donut: a slice under ~2% renders as the minimum round dot; the
  legend folds the tail into a grey `Others`, so a month with both a real `other` category and a grouped
  tail shows `Other` *and* `Others`; a 6-figure total would touch the ring (hole sized for ~10 chars).

## 5. Next steps (priority order)

1. Move the UI harness and probes into the repo (e.g. `tools/ui-check.js`, `tools/preview.py`) so the
   regression suite survives, and document how to run them in the README.
2. iPhone pass on `http://192.168.1.12:8000/`: keyboard vs keypad collapse, chips momentum, the date picker
   inside the sheet, safe areas, one receipt scan end to end.
3. Add `CLAUDE_FALLBACK_MODEL` to `.env.example` (one line, matching `config.py`).
4. API work to unlock the deferred UI: a summary/list range endpoint (`?from=&to=`) → Insights `Year`,
   true cross-month range totals, Home-vs-ring count alignment for ranges.
5. Product decisions still open: where notes live (column vs `raw_extraction.note`) and whether users can
   add custom categories.
6. Optional polish: donut slice minimum, `Others`/`Other` collision, ring hole sizing for 6-figure totals.

## 6. Instructions for the orchestrator — settle these before more UI work

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
