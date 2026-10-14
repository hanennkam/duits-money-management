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

- **Splash on every cold launch, then never again.** Markup + its own `<style>` are the first things in
  `<body>`, so the overlay is painted with the first frame (opaque, `z-index: 9999`, background
  `var(--bg)` from the already-resolved theme); logo 96px/radius 22px/soft shadow, `Duits` 28px/700,
  16px under it, and the waking-up line in a `height: 0` wrapper so the wordmark cannot move when it
  appears. Entrance is a CSS animation (400ms, `scale(.94) → 1`); the exit is WAAPI (`opacity 1 → 0`
  over 300ms, logo to 1.04) followed by `visibility: hidden` + `pointer-events: none` — never
  `display: none`, plus a backing timer. Reduce Motion: no scale, 150ms fade.
  - `SPLASH_MIN_MS = 1200`, `SPLASH_WAKING_MS = 4000`, `SPLASH_MAX_MS = 60000`, `SPLASH_FADE_MS = 300`.
  - `startSplash()` returns the settle callback; `start()` calls it when the key dialog takes over,
    after `await loadHome()` (the boot now awaits it) and again from `start().then(...)`, so a
    loaded/failed/thrown boot always hands the screen over.
  - The 60s backstop also writes the normal error card when the app painted nothing (a hung request
    never reaches `loadHome`'s catch).
  - It is one-way per page load: tab switches, month changes, sheets and refreshes cannot re-show it.
  - The splash uses the app's `--sat`/`--sab` variables rather than `env()` directly, so it stays part
    of the "one name per inset" rule (and a probe can simulate a notch for it too).

- **Swipe down to dismiss, from almost anywhere on the Add and edit sheets.** The old drag was bound to
  the grabber only and used an 80px threshold; it is replaced by one `attachSheetDrag(sheetId,
  overlayId, onDismiss, handleOnly)`:
  - pointerdown/move/up **on the sheet** with `setPointerCapture`, `isPrimary` guard;
  - a drag starts only where nothing else has a gesture — `DRAG_BLOCKERS` (buttons, links, labels,
    inputs, selects, textareas, `.key`, `.keypad`, `.chip-scroll`, `.cat-chip`, `.add-rows`,
    `.smart-card`, `.add-pills`, `.add-details`, `.sheet-actions`, the wheel) plus a `.no-drag` escape
    hatch — and only after 8px of *downward, mostly vertical* movement (`|dy| > |dx|`);
  - at that point the running open/close animation is cancelled, a focused input is blurred (the
    keyboard leaves with the drag), the sheet follows `translateY(dy)` with no animation and the scrim
    thins with the distance (floored at 0.3);
  - release closes on `dy > 120` **or** `velocity > 0.5 px/ms`, continuing from the finger's offset via
    `closeOverlay(element, after, fromOffset)` — the close animation now accepts a start offset, and
    drops every inline style when it lands. Otherwise a 250ms spring back to 0.
  - `pointercancel` clears the inline styles, the spring cleanup is epoch-guarded (a new press
    invalidates a settling one) and the close keeps its timer fallback, so nothing can stick.
  - Reduce Motion: no spring, closing unchanged (opacity-only). The month wheel keeps `handleOnly:
    true` (its columns scroll vertically); the edit sheet drags from its head/amount surfaces because
    its body still has to scroll.
  - CSS: `#addSheet { touch-action: none }` with `pan-x` handed back to the chip scroller and `pan-y`
    to the expanded Details row; the edit sheet locks only its head and amounts.

- **Full screen on the Home Screen, and the Add sheet's head no longer under the status bar.**
  - **The Add sheet is a full-screen page now**: `position: fixed; inset: 0; height: 100dvh` (a
    `100%` fallback) with `padding-top: max(var(--sat), 8px)` and no JS height at all. The old
    `addSheet.style.height = window.innerHeight + "px"` was the bug: in a standalone app
    `innerHeight` is not the screen, so the sheet was short and its head (Cancel / New Transaction /
    Save) sat under the status bar. The keypad pads its bottom by `--sab`, and the edit sheet and the
    month wheel get the same from the overlay: `padding: max(var(--sat), 12px) 12px calc(12px +
    var(--sab))` plus `max-height: min(88dvh, calc(100dvh - insets))`.
  - **One name per inset** — `--sat/--sab/--sal/--sar` resolved once from `env()` at `:root`; nothing
    else in the file calls `env()` directly, which is also what lets a probe simulate a notch.
  - **Edge to edge in both themes**: `html { background: var(--bg) }` paints the canvas behind the
    status bar and home indicator; the nav bar's inset is padding (so its frosted background reaches
    y=0 while its content starts below the clock) and the tab bar's bottom padding clears the home
    indicator. `viewport-fit=cover` was already there; `apple-mobile-web-app-capable=yes` is
    unchanged.
  - **Status bar style is theme-aware**, and this is the judgement call to review: the meta ships as
    `apple-mobile-web-app-status-bar-style = black-translucent` (as asked) but the pre-paint script and
    `applyTheme` keep `black-translucent` only for the dark palette and ask for `default` in light,
    because iOS gives `black-translucent` **white** glyphs and our light bar is
    `rgba(249, 249, 249, .85)` — white on near-white. Full-screen-ness does not depend on that value
    (`viewport-fit=cover` + the safe-area padding do that, and `env()` adapts either way). The
    alternative is `black-translucent` in both themes with a darkened top strip in light mode, which
    is the colour hack deliberately not taken.
  - **Short-box container queries** make the sheet fit rather than scroll when the insets take real
    space: `@container (max-height: 640px)` → 44px keys, tighter gaps, amount floor 1em;
    `(max-height: 560px)` → 40px keys, smaller amount, no hint; `(max-height: 500px)` → the content
    column scrolls as a last resort. The container is the sheet's own content box, so 667px of box
    (a phone with no notch) trips none of them and keeps its old sizes.
  - **Build row** is now `motion 5 · fullscreen` plus the live status bar style and
    `standalone`/`browser` (`window.navigator.standalone`), painted by `paintBuild()` — the field
    check for "did this phone load the new meta".
- Earlier in the same session: **three iPhone-only defects** — sheets now animate through the Web
  Animations API (cancel + close token + 500ms fallback), the save highlight runs after the sheet has
  closed and animates the row's own background in both lists, and the Add sheet's text mode /
  `visualViewport` keyboard handling was deleted in favour of one fixed page (the height pin above was
  part of that change).

- **Three iPhone-only defects, all three traced to a real cause in the code and fixed with no backend
  change.**
  1. **`+` sheet animated only once.** The sheet moved on a CSS **transition** driven by `.open`; iOS
     played it once and then ignored it. Sheets now move on the **Web Animations API**:
     `openOverlay()` animates the sheet `translateY(100%) → 0` and the scrim `opacity 0 → 1`
     (350ms, `--ease-ios`, `fill: both`), `closeOverlay()` animates back and applies the closed state
     only when the animation reports `finished`, with a **500ms fallback timer** so a close can never
     stick. Every open **cancels** what is still running and bumps a close token, so ten fast
     open/close pairs land on the right state (the token is what stopped a late close from re-closing a
     sheet that had been reopened). Reduce Motion keeps opacity-only fades and no movement. The
     `.overlay`/`.sheet` CSS now carries **no transition at all** — it is state (`opacity`,
     `visibility`, `pointer-events`, resting transform), and dragging the handle cancels the animation
     before the finger takes the transform.
  2. **Save highlight never seen.** It ran *before* the sheet had closed, and it was a class
     (`is-new` + a `::after` overlay) that the next render could wipe. `afterAdd()` now waits for
     `Promise.all([loadHome(), loadTransactions(), closed])` — the sheet's close promise included — and
     `flashRow(id)` animates the row's own `background-color` on the Web Animations API: `--accent-soft`
     held for 600ms of an 1800ms timeline, then eased to the same hue at zero alpha. It matches by
     `data-id` in every list that holds the row (Home *Recent Transactions* and the Transactions tab).
     All three save paths (keypad Save, Smart Entry, Scan Receipt) funnel through `afterAdd`, so all
     three flash.
  3. **The Add sheet moved when the keyboard opened.** Text mode (`html[data-text-mode]`), the
     `visualViewport`/`--vvh` measuring and `revealFocusedField()`'s scroll-into-view are **all
     removed**. The sheet is now one fixed page: height pinned in px to `window.innerHeight` when it
     opens, the page scroll-locked (`html`/`body` `overflow: hidden`, restored on close), and nothing
     in it measures or follows the keyboard. Smart Entry is no longer an expandable row — it is a
     compact card directly under the header (sparkle + label, then a 16px text field and a fixed-width
     blue `Add`), and the keypad no longer hides when a text field takes focus. `focus()` is called
     with `{ preventScroll: true }`; `scrollIntoView` / `visualViewport` / `--vvh` / `data-keyboard`
     appear nowhere in the page.
- Earlier in the same session: **iPhone animations reported broken: five separate causes, all found in
  the code.**
  1. *"only plays the first render"* — the 900ms freshness gate (`bumpContentMotion`/`markFresh`)
     deliberately suppressed every replay, so a tab switch, a month change or a refresh animated
     nothing after the first paint. Replaced by one explicit `replay(el, className)` helper
     (remove class → force reflow → add it) called by every entrance, and the gate is gone.
  2. *"sheets only slide once"* — see the Web Animations fix above; the intermediate step was a CSS
     transition on `.open`, which replaced the original CSS animation hung off a `display` flip.
  3. *"no press spring"* — iOS Safari only applies `:active` to a `<button>` when the document has
     a touch listener, and the page had none. One empty passive `touchstart` in `wire()` fixes it.
  4. *"the save flash never shows"* — the flash was decided *before* `refreshAllScreens()`, so a
     slow reply (or any later re-render) painted over it; now the Web Animations highlight above.
  5. *"standalone shows none at all"* — **not reproducible from here**: there is no service worker and
     no external CSS/JS (the page is the only asset). `GET /` now sends **`Cache-Control: no-store`**,
     so no copy of the document can come from cache; the **Build** row in Settings still shows the
     stamp the phone actually loaded.
  Also fixed while in there: two layout-property animations (`transition: height` on the day
  chart, `width` on the category bars), `backdrop-filter` on the moving toast, and the keyboard
  layout (superseded by the fixed page above).
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
  carries `?v=2`, and `GET /` sends `no-store`.
- **iPhone animations reported broken: five separate causes, all found in the code.**
  1. *"only plays the first render"* — the 900ms freshness gate (`bumpContentMotion`/`markFresh`)
     deliberately suppressed every replay, so a tab switch, a month change or a refresh animated
     nothing after the first paint. Replaced by one explicit `replay(el, className)` helper
     (remove class → force reflow → add it) called by every entrance, and the gate is gone.
  2. *"sheets only slide once"* — the entrance was a CSS **animation** hung off the
     `hidden` attribute flipping `display`. Chromium replays that; iOS WebKit is exactly where it
     fails. Sheets are now mounted permanently and move on a **transition** driven by `.open`
     (`openOverlay` adds it two frames after mount).
  3. *"no press spring"* — iOS Safari only applies `:active` to a `<button>` when the document has
     a touch listener, and the page had none. One empty passive `touchstart` in `wire()` fixes it.
  4. *"the save flash never shows"* — the flash was decided *before* `refreshAllScreens()`, so a
     slow reply (or any later re-render) painted over it. `flashRow(id)` now runs in the promise
     after Home and the list have reloaded and marks the live row by `data-id`.
  5. *"standalone shows none at all"* — **not reproducible from here, and not a code path**: there
     is no service worker and no external CSS/JS (the page is the only asset), and `GET /` already
     sends `no-cache`. The remaining explanation is a document cached *before* that header existed
     (heuristic freshness) still being served to the standalone shortcut. The new **Build** row in
     Settings shows the stamp on the phone to confirm it, and `?v=` was bumped on the icons.
  Also fixed while in there: two layout-property animations (`transition: height` on the day
  chart, `width` on the category bars), `backdrop-filter` on the moving toast, and the keyboard
  layout: `align-items: flex-end` pinned the sheet to the bottom of the *layout* viewport, which
  iOS leaves under the keyboard — capping its height was never going to help.
- **iOS motion pass.** Every animation now runs on `transform`/`opacity` only (plus the ring's
  `stroke-dasharray`) on one curve (`cubic-bezier(0.32, 0.72, 0, 1)`) with four durations in `:root`
  (sheet 350, page 180, press 100, toast 250). Two real defects were found while doing it: the day
  chart was animating **height** and the category bars **width** (layout properties), and the collapsed
  Details/Smart Entry blocks were leaking 8px/12px of padding into the layout.
- **iOS zoom + Smart Entry row.** The "field and Add button cut off on the right" was not a layout bug:
  the Smart Entry input was **15px**, and iOS zooms the whole page in when a focused control is under
  16px, which is what pushed the right-hand edge off screen. Measured first: `overflow=0` on every
  screen and the input's right edge at 345 of 375. Fixed by a 16px floor on every focusable control, a
  `touch-action: manipulation` / no-text-select pass, and turning Smart Entry into one card.

## 2. Changes

Files touched (the last three tasks: `app/static/index.html` and the docs only — no backend, no API,
no test file):
`app/static/index.html` (HTML + CSS + vanilla JS, no build step, served by the API at
`GET /`), `app/main.py` (one `_icon()` helper + four public icon routes, and **`Cache-Control:
  no-store` on `GET /`** — the one backend line this session, plus its two test assertions),
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
- **Replay, not remounting**: `replay(element, className)` removes the class, reads `offsetWidth` to
  force a reflow, then adds it back. It is called by `showScreen` (`is-entering`), `slideScreen`
  (`is-sliding`), every renderer (`is-fresh` on `#txnList`, `#txnGroups`, `#categoryList`,
  `#insightDays`, `#insightCats`), the two donuts (`is-drawn`) and `flashRow` (`is-new`). No timer,
  no freshness window, nothing to miss.
- **Overlays**: always in the DOM, `opacity: 0; visibility: hidden; pointer-events: none` when closed
  (`visibility` flipped after the fade), `.open` transitions the scrim's opacity and the sheet's
  `translateY` (`--move-sheet` → 0). `openOverlay` clears any pending close timer and adds `.open`
  after two rAFs; `closeOverlay` removes it and finishes on `transitionend` (scrim opacity, which
  always animates even under reduce motion) with a `min(dur + 120, 400)`ms fallback; `closeDone`
  makes the two paths race safely. The `hidden` attribute and the four old keyframes are gone.
- **The ring**: segments are `<path>` arcs (`ringArc`/`ringArcPoint`) so the draw is a
  `stroke-dashoffset` transition from each arc's own `--len` to 0. A circle could not do this — a dash
  on a closed loop can only slide, never grow. Under reduce motion the offset is pinned to 0 with no
  transition, or the ring would simply disappear.
- **Smart Entry text mode**: `setTextMode(on)` toggles `html[data-text-mode]`, which hides
  Expense/Income, the amount, the date and Details pills, the chips, Scan Receipt, the hint and the
  keypad, and anchors `#addOverlay` to `--vvh` (`inset: 0 0 auto 0; height: var(--vvh, 100dvh)`). The
  anchoring is the fix: the sheet is bottom-aligned inside the overlay, so sizing the overlay to the
  visual viewport parks the sheet above the keyboard. Restored by `closeAddSheet` and on reopen.
- **A Build row** in Settings (`motion N`) exists only to answer "is the phone running the current
  page?" from the phone. Bump it with every `index.html` change.
- **Motion**: the tokens (`--ease-ios`, `--dur-sheet/page/press/toast`, `--move-sheet/page/month/row/toast`,
  `--press-scale`) live in one `:root` block beside the palette, and `prefers-reduced-motion: reduce`
  overrides the same block (durations 150ms, every `--move-*` zero, `--press-scale: 1`) plus switches
  off the three pieces that are movement without a fade-only equivalent (ring draw, bar grows, row
  stagger). The entrance of a sheet rides the display change (no JS), the exit is `.is-closing` + a
  `closeOverlay()` timer whose length is read from CSS via `motionMs()` — so reduced motion also
  shortens the *wait*, and the timer is stored on the element so a second close restarts it instead
  of stacking (nothing can be stuck). `button:not(.tab):not(.tab-add), .add-pill` is the one press
  rule; the tab bar and the `+` are excluded by the task's wording. `.screen` wrappers give the page
  fade without touching the tab bar. `bumpContentMotion()` opens a 900ms window and `markFresh()`
  guards every row/ring/bar animation, so a re-render or a refresh is silent (verified: a refresh
  leaves `freshMarks=0`). The day chart now grows with `scaleY` and the category bars with `scaleX`
  (`transition: height`/`width` are gone), and the collapsed expanders are 0-tall grid rows with
  their spacing as a margin on the clipped content — padding on the clipped box was the 8px/12px leak.
  The old `html:has(.add-row.is-open) #screen-add` scroll escape was removed: with the leak fixed no
  state overflows at 375×667 any more.
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

**This session — the cold-launch splash (all re-run after the final edit):**

- `./.venv/bin/python -m pytest -q` → **83 passed**; `node /tmp/duits-ui-check.js` → **710 assertions**
  / **852 in total** (40 splash pins: the markup being first in `<body>` with its own styles, the four
  timings, the geometry, the entrance/exit keyframes, `visibility`/`pointer-events` and the absence of
  `display: none`, the settle wiring, and two behavioural ones — firing the armed 4s and 60s timers
  from the harness asserts the waking line appears, the backstop hides the splash **and** writes the
  `error-card`, and that a second `hideSplash()` neither animates nor re-shows anything). The harness's
  boot hook now targets `start().then(splashSettled, splashSettled)` and the exposed list carries
  `startSplash/hideSplash/showTimeoutNotice` + the constants.
- **Splash probe over CDP** (`/tmp/cdp-js-splash.js`), 375×667 and 430×932, dark and light:
  - visible while the probe starts: `z=9999`, covers the viewport, `touch-action: none`,
    `elementFromPoint(centre)` resolves inside the splash; logo `96x96 radius=22px shadow=true`,
    `word: 28px/700`, `gap=16`, group centred `0px` off centre; hint present at `opacity: 0` with text
    "Waking up the server…"; background `rgb(242, 242, 247)` light / `rgb(0, 0, 0)` dark;
  - hides `~1290ms` after the script ran (`goneAt` 1620ms with injection at 330ms), leaving
    `visibility=hidden opacity=0 pointerEvents=none ariaHidden=true`, and hits land on the app again;
  - does not return after a tab switch, a month wheel, an add sheet and a refresh (`0/12` samples
    visible, `anims=0`, one splash in the DOM).
- **Slow and failing servers** (stub knobs `?slow` / `?fail` in the preview, `FRAME_URL` +
  `READY_SELECTOR` in the runner):
  - `?slow` (5.2s): the hint fades in at **4.2s**, the splash hides at **5.7s**;
  - `?fail` (500): the splash hides at ~1.25s with the app's own `<div class="error-card">` behind it
    at every 250ms sample, and no thrown errors or rejections.
- **Reduce Motion** (`--reduced-motion`): `logo animation-name=splash-logo-fade`, and the whole
  lifetime sees **one** animation on the logo (the CSS fade) instead of two (fade + WAAPI scale),
  hiding at 1414ms with the app tappable.
- **Regressions re-checked**: the ten button open/close cycles are still `10/10` with nothing stuck,
  and the drag probe still closes from the header/amount/empty space (`translateY(200px)` mid-drag).

**Previous session — swipe to dismiss (all re-run after the final edit):**

- `./.venv/bin/python -m pytest -q` → **83 passed**; `node /tmp/duits-ui-check.js` → **670 assertions**
  / **812 in total** (36 new pins: the four drag constants, `setPointerCapture` on the sheet, the
  vertical-only gate, the velocity line, the blur, the cancel-before-takeover, the reduce-motion
  spring guard, the two-axis release rule, `pointercancel`, the three `attachSheetDrag` wirings with
  the wheel's `handleOnly`, the `fromOffset` close keyframes, the inline-style cleanups and the
  `touch-action` rules; the stale `wireSheetDrag` / 80px / `window.innerHeight` pins were replaced).
- **Synthetic pointer probes over CDP** (`/tmp/cdp-js-drag{1,2a,2b,3}.js`), 375×667 and 390×844:
  - 200px drags from the **header**, the **amount** and the sheet's **own empty space** all follow the
    finger (`midDrag transform=translateY(200px)`, `scrimOpacity=0.745`) and close, with
    `inline="" running=0` afterwards;
  - slow 60px → springs back (2 spring animations), stays open; 70px flick → closes on velocity;
  - upward 200px and sideways 200px → the sheet never moves, stays open;
  - 6px wobbles on a keypad key, in the chips row (`touch-action: pan-x`), on the Smart Entry card, on
    Scan Receipt and on Save → all stay open, and the key still types `RM 5`;
  - drag with the Smart Entry field focused → `focusedBefore=true focusedAfter=false`, closes;
  - `pointercancel` mid-drag → stays open, sheet at rest, no inline leftovers;
  - ten drag-close cycles → `closed=10/10 stuck=0`, settled `visibility=hidden pointers=none
    inline=""` and the sheet back at `translateY(667px)`;
  - edit sheet closes from its `.sheet-title`; month wheel stays open on a column swipe and closes from
    its grabber; `final: openOverlays=0 overflow=0`;
  - 60ms into the open animation a drag cancels it (`midDragRunning=0`) and takes the transform.
- **Reduce motion** (`--reduced-motion`): the same script closes on a long drag, settles on a short one
  with **zero** spring animations, and still takes over from a running animation.
- **Regressions re-checked**: the ten open/close button cycles are still `10/10` with nothing stuck and
  no thrown errors; the keyboard focus test still shows `moved? sheetH=0 sheetTop=0 amountTop=0
  keypadTop=0 scrollY=0`.

**Previous session — full screen + the Add sheet's safe area (all re-run after the final edit):**

- `./.venv/bin/python -m pytest -q` → **83 passed**; `node /tmp/duits-ui-check.js` → **634 assertions**
  / **776 in total** (21 new pins: `viewport-fit=cover`, the `black-translucent` meta, the four
  `--sat/--sab/--sal/--sar` declarations being the only `env()` uses, `html` painting the screen, the
  nav/tab-bar variable padding, the full-screen `#addSheet` rules, `container-type: size` and the three
  container queries, the overlay's two-ended padding and `min(88dvh, …)` max-height, the theme-aware
  status bar style and `paintBuild`). The old pins for the pixel height are gone, and the sandbox's
  fake nodes gained `getAttribute` for the Build row.
- **Safe-area probe over CDP** (`/tmp/cdp-js-fullscreen.js`), insets simulated through the variables
  (375×667 + 47/34, 390×844 + 47/34, 430×932 + 59/34):
  - nav bar: `top=0 reachesEdge=true`, `padTop=55/55/67px`, brand top `60/60/72` (≥ the inset),
    refresh inside the bar;
  - tab bar: `bottom = the viewport`, `padBottom=36px`, first tab bottom `631/808/896` ≤ vh − 34,
    `reachesEdge=true`;
  - Add sheet: `position: fixed`, `top=0`, `height = 667/844/932 = the viewport`, `padTop = 47/47/59`,
    Cancel top `69/69/81` ≥ inset, Save bottom `106/106/118` visible;
  - keypad: `padBottom = 38/40/40px`, last key bottom `623/798/886` ≤ vh − 34;
  - `hiddenOrClipped=[]`, `sheetScrolls=false`, `columnScrolls=false`, `overflowX=0` at every size;
    keys `44px` at 375×667 and `56px` at both taller sizes, amount `44/56/56px`;
  - keyboard faked to 43% of the screen: `dSheetH=0 dSheetTop=0 pageScrollY=0 zoom=1 focused=true` —
    still nothing moves;
  - month wheel: `top=288/465/553` ≥ inset, `bottom=621/798/886` ≤ vh − 34.
- **Both themes**: dark → `meta=black-translucent theme-color=#000000`; light →
  `meta=default theme-color=#f2f2f7`, identical geometry (the inset layout does not depend on the
  glyph choice).
- **Regressions re-checked after the shell change**: ten open/close pairs still `10/10` with nothing
  stuck and no thrown errors; reduce motion still opens/closes with opacity only; `sheetHeightStyle`
  is `(none)` (no inline height left).
- **Live server**: `GET /` → 200 `cache-control: no-store`, and the served page carries
  `black-translucent`, the `--sat` variables and `container-type: size`.

**Previous session (unchanged):**

- `./.venv/bin/python -m pytest -q` → **83 passed** (the `no-store` assertions included).
- `node /tmp/duits-ui-check.js` → **UI CHECK OK: 613 assertions** / **UI INTERACTION OK: 755
  assertions passed in total**. Pins updated for this change: the WAAPI open/close (keyframes, cancel,
  the 500ms fallback, the close token), the fixed-page sheet (`style.height = window.innerHeight`,
  `lockPageScroll`, no `visualViewport`/`--vvh`/`data-keyboard`/`text-mode` anywhere in the page), the
  card markup and sheet order, the flash (`FLASH_MS = 1800`, `FLASH_HOLD_MS = 600`, `rows[i].animate`,
  `Promise.all([loadHome(), loadTransactions(), closed])`), and the removals (`is-new`,
  `highlight-out`, `paintKeypad`, `revealFocusedField`, `toggleSmartEntry`, `setTextMode`,
  `refreshAllScreens`, `.txn { position: relative }`). The sandbox gained an `Element.animate` stub and
  a `document.body`.
- **Real timers over CDP** (`/tmp/cdp-motion.py`, exact device viewport), 375×667 and 390×844:
  - **Sheets**: 10× `+`/close → `opened=10/10 closed=10/10 stuck=0`, settled `open=false opacity=0
    visibility=hidden pointers=none` and `runningAnimations=0`; `app errors: none` (the interim run
    that showed `opened=5/10` exposed a real bug — a late close re-closing a reopened sheet — which is
    what the close token in `openOverlay` fixes).
  - **Keyboard**: with `visualViewport.height` faked to 43% of the screen and the Smart Entry input
    focused → `sheetH=667/667 sheetTop=0 amountTop=218 keypadTop=432 keypadVisible=true`, and the
    deltas against the unfocused state are **`sheetH=0 sheetTop=0 amountTop=0 keypadTop=0 scrollY=0`** —
    nothing moves; `focused=true`, `zoomed=false`, horizontal `overflow=0`. Identical at 390×844
    (`sheetH=844/844`). Typing keeps the text and the pinned height.
  - **Flash**: manual Save → at +255ms `sheetOpen=true background=rgba(0,0,0,0)` (nothing yet), at
    +508ms `sheetOpen=false` with `rgba(10,132,255,0.18)` in **both** `#txnList` and `#txnGroups`;
    the animation is `dur=1800` and still holds `0.176` at `t=617`, then falls to `0.043` at `t=883` —
    a real 600ms hold, then the fade. Smart Entry save behaves the same. Scan Receipt reaches the same
    `afterAdd()` (line-verified; the camera itself cannot be driven from here).
  - **Reduce motion** (`--reduced-motion`): `matchMedia(...).matches=true`, `move-sheet=0%`, sheet
    `transform=matrix(1,0,0,1,0,0)` while the scrim still fades (`opacity 0.72` mid-flight), sheets
    still settle closed, ring already drawn with `transitionDuration=0s`, bars not animated,
    `openOverlays=0 overflow=0`.
- **Geometry at both sizes** (375×667 and 390×844): `sheetH = innerHeight`, `amountFont=56px`,
  `keyH=48/56px`, `keypadBottom = innerHeight`, `clipped=[]`, `contentOverflow=false`,
  `sheetScroll=false`, `overflow=0`, `saveDisabled=true`; Details open adds no clipping.
- **Live server** after `./ctl.sh restart`: `GET /` → 200, 151,632 B, `cache-control: no-store`,
  `content-type: text/html`, `nosniff` and `Referrer-Policy` intact; the served page contains the
  `smart-card` markup and **no** `data-text-mode` / `smartRow` / `is-new` / `paintKeypad` references.
- The page's inline script re-parses (`node --check`).

**Previous session (unchanged):**

- `pytest -q` → **83 passed** (0.31s) — the 75 original tests plus 8 in `tests/test_static.py`
  (four icon URLs public + `image/png` + `max-age=600` + byte-identical to disk; not in the schema;
  `GET /` `no-cache` with an ETag; each file alpha-free and square at 180/180/152/120; and every icon
  link in the page versioned and really served).
- `/tmp/duits-ui-check.js` (Node harness that evals the extracted `<script>`) → **751 assertions pass**,
  including: no colour literal anywhere in the stylesheet or script outside the two palette blocks and the
  two hue constants; the pre-paint script's position and `try/catch`; the exact dark palette values; the
  Add sheet order; 12/8/12px gaps and 48px rows; the four states that may scroll (`.add-details`, the
  sub-660px escape, `html[data-keyboard]`, `html:has(.add-row.is-open)`); the 44px key step; threshold
  derivations (amount still 56px at 667, keys still 48px at 667); the 16px floor on every focusable
  control; `touch-action: manipulation`; and that `revealFocusedField()` scrolls and never zooms.
- Real-browser fit probe (iframe = exact viewport) at **375×667** and **390×844**, five states each:
  `orderOk=true`, `sheetScroll=false`, clipped elements `[]`, amount 56px, gaps 12/8/12 in every state,
  rows 48/48, keys 48/48 (667) and 56/56 (844), keypad bottom == sheet bottom, Save disabled at
  RM 0.00 and enabled at RM 12.50. No state overflows or clips any more, so the Smart Entry scroll
  escape (and the `:has()` rule behind it) is gone.
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
- **The protocol, run in a real Chrome at an exact 375×667 (and again at 390×844) on real timers**
  (`/tmp/cdp-js-protocol.js`, `-protocol2.js`, `-geometry.js`):
  - open/close "+" ten times: `opened=10/10 closed=10/10 stuck=0`, settled
    `open=false opacity=0 visibility=hidden pointers=none transform=matrix(1,0,0,1,0,667)`.
  - ten tab switches: `donuts seen=10 dressed=10`, `tabbar=none plus=none` throughout, and the ring is
    back at `stroke-dashoffset=100.41` of `--len=128.25` 50ms after re-entry every time.
  - month change: wheel sheet mid-slide `translateY(22.9px)` and closed 140ms after Done, new rows at
    `opacity 0.991` / `translateY(0.03px)` / `--i:0`, `--slide=var(--move-month)`, settled identity.
  - save end to end (the preview stub now really creates a row on POST): `flashOnRows=2 id=new-1`,
    `::after opacity 0.64` fading, sheet closed, and after the 1s cleanup `flashOnRows=0` with the new
    row still in the list.
  - Smart Entry: `data-text-mode=true`, typeToggle/amount/chips/scan/keypad/date/Details hidden, mode
    pill visible; with `visualViewport.height=380` the sheet bottom is exactly 380 and the field bottom
    360 (visible while typing, and after typing); closing the card restores `textMode=off`, rows 48/48,
    keys 48, full sheet height.
  - geometry at both sizes in every state: `contentOverflow=false sheetScroll=false overflow=0`, nothing
    clipped inside the sheet except the category chips in their own scroller, amount 56px, keys 48/56,
    keypad flush with the sheet bottom, Save disabled at RM 0.00.
  - `--force-prefers-reduced-motion`: `move-sheet=0% move-page=0px move-month=0px press=1`, sheet
    transform identity while the scrim still fades (0.72 at 40ms), the page fades without moving, the
    ring reads `strokeDashoffset=0 transitionDuration=0s` (drawn, not animated), the close still settles
    to `open=false opacity=0 visibility=hidden pointers=none`, nothing stuck, `overflow=0`.
  - the both-theme audit still passes: 35 dark states, 0 findings, calibration still flags 2.
- **Instrumentation lesson (again)**: `--virtual-time-budget` freezes the animation *and transition*
  timeline, so the older virtual-time probes now report collapsed expanders, from-state transforms and
  an invisible ring — measurements that look like broken layout. They are only trustworthy for static
  checks now; motion and geometry must go through CDP on real timers. The CDP runner also sets an exact
  device viewport instead of loading a hand-written frame page: a stale frame file silently stays
  `about:blank`, and an iframe created from `about:blank` is cross-origin (both produce empty results).
- Real-time animation measurement over CDP (the previous task's run, kept for the numbers it caught):
  **freezes the animation timeline**, so it cannot be used for any of this): Add sheet
  `translateY(381px) @60ms → 26px @200ms → none @600ms`, scrim `0.43 → 1`, resting `height=667
  bottom=667`; exit `class='overlay is-closing' @60ms` then `hidden=true transform=none class=overlay`;
  page fade `translateY(1.07px) opacity=0.82 @50ms → none/1 @350ms` with `tabbar=none plus=none`
  throughout; ring dash `0 → 52.8 → 127.7 → 128.25 of 402.12`; category bar `scaleX 0 → 0.41 → 0.996
  → 1`; day bar `scaleY 0 → 0.64 → 0.998 → 1`; toast `translateY(-49px) opacity=0 → 0/1` then
  `opacity=0.03 @4.4s` and `hidden` after; save highlight `::after opacity 0.84 → 0.03 → 0` over 800ms
  on `rgba(10,132,255,0.18)`; a real mouse press scales a key/chip/row to `matrix(0.96, …)` with
  `opacity=0.7`, back to `none`/`1` on release.
- Ten fast open/close pairs (synchronous, then one settle): `openAnimated=10/10 exitAnimated=10/10`,
  `is-closing` set on every close, never a stray visible-not-closing overlay, and after settling:
  `overlays=none closing=0 hidden=true transform=none overflow=0 scrollY=0`. Six fast tab switches:
  six page animations, `tabbar`/`+` never animated, one visible screen, nothing stuck.
- `--force-prefers-reduced-motion`: tokens read `dur-sheet=150ms move-sheet=0% move-page=0px
  move-month=0px move-toast=0px press-scale=1`; the sheet stays at `matrix(1,0,0,1,0,0)` while the
  scrim still fades, the page fades without moving, the ring/bars are `animation=none` at their final
  values, and the close still waits exactly 150ms.
- Served app (after `./ctl.sh restart`, so the new routes are live): all four icons → **200, `image/png`,
  `public, max-age=600`, no `X-API-Key`**, with `nosniff` + `Referrer-Policy` (`/logo.png` 10,045 b,
  `apple-touch-icon.png` 10,045 b, `-152x152` 8,117 b, `-120x120` 5,355 b; the `?v=2` form serves the same
  bytes with the same headers, and the served 180×180 is byte-identical to disk). `GET /` → 200 (134,624 b)
  with `cache-control: no-cache` and all four versioned `<link>` tags. `uvicorn` running; LAN IP
  **192.168.1.12** (phone URL `http://192.168.1.12:8000/`).
- In-browser brand check (375×667 and 390×844): `mark=24x24 radius=6px loaded=180x180`, bar height 52px
  with and without the mark (`barHeightMoved=false`), `barOverflow=no`, refresh button still 34px.

## 4. Unresolved issues / risks

- **The splash's timings are measured in Chrome, not on a phone.** The probes prove the minimum hold,
  the 4s line, the 60s backstop (in the harness, with fake timers), the failing-API path and that it
  never comes back. They cannot show how the 1200ms *feels* on a real cold launch, whether iOS's own
  launch image (the blank screen before the page paints) makes the splash look late, or how promptly
  `logo.png` decodes on a cold install — it is a 180px PNG at `max-age=600`, so a truly cold cache can
  put the icon a beat behind the wordmark.

- **The swipe's arbitration against iOS's own gesture handling is reasoned, not tested.** The probes
  drive synthetic pointer events, so they prove the state machine (thresholds, velocity, cancel,
  spring, exclusions) and nothing about a real finger. Open on a device: whether iOS sends
  `pointercancel` instead of `pointermove` when a drag starts over the edit sheet's
  `touch-action: pan-y` regions (the Add sheet locks the whole surface, so it is unaffected), whether
  the chips row still scrolls horizontally while the sheet is listening for pointers, and how the
  scrim reads mid-drag. Also unverified: the `.add-details` panel and the pills row are excluded from
  dragging on purpose — confirm on the device that this does not feel like a dead zone.

- **The iOS status bar style is the one judgement call to confirm on a device.** The page ships
  `black-translucent` and swaps to `default` for the light theme (white glyphs over a near-white bar
  would be unreadable). Two things cannot be checked from here: whether iOS re-reads the meta on a
  standalone relaunch rather than only at install, and how the strip looks in the light theme. If the
  light theme ends up with white glyphs, the fallback is `default` in both themes — `theme-color`
  already matches the bar, so the top still looks continuous.
- **Still never run on a real iPhone.** So these remain unverified: real `env(safe-area-inset-*)`
  values (the probe simulates them through `--sat`/`--sab`, so it proves the *layout* reacts, not that
  iOS reports 47/59/34), whether a real keyboard leaves `100dvh` alone, WebKit's own Web Animations
  timing, container-query support on the iOS version in hand (Safari 16+ has it; older falls back to
  the un-shrunk sizes), the real Reduce Motion switch, and iOS `:active` springs. `http://192.168.1.12:8000/`
  after deleting and re-adding the shortcut; the **Build** row prints the status bar style it ended up
  with and whether it is standalone.

- **Still never run on a real iPhone.** Everything above was executed in desktop Chromium sized to
  the phone, so these stay unverified: whether WebKit's Web Animations implementation looks as smooth
  as Chromium's, whether iOS really leaves the page alone now that it is scroll-locked and nothing
  calls `focus()`/`scrollIntoView` (the faked `visualViewport` proves the code *asks* for nothing, not
  what iOS does), the real keyboard against the fixed 667px page, the iOS **Reduce Motion** switch
  (the media query was emulated), and iOS `:active` springs. The **Build** row (`motion N`) is the
  fingerprint to check on the phone; `http://192.168.1.12:8000/` after deleting and re-adding the
  shortcut.
- **The keypad is now covered while typing.** By design (the sheet never moves, the keyboard overlays
  the lower half and the amount can still be entered by tapping keys with no keyboard focused), but
  this is a real product trade: with Smart Entry focused, the keypad below is unreachable until the
  keyboard is dismissed. Worth a look on the device.

- **Whether iOS really plays the sheet transition every time cannot be confirmed here** — that it
  does so in Chromium is measured (`opened=10/10`), and the fix removes the known-unreliable
  mechanism (an animation tied to a `display` flip) rather than tuning it.
- **`visualViewport` geometry is emulated**: `--vvh` and the text-mode anchor are verified against a
  faked `height` (380 of 667, 481 of 844) with `offsetTop: 0`. A real keyboard, a real
  `offsetTop`, and iOS's own scrolling of the visual viewport are untested.
- **Real-device motion is unverified beyond timing and geometry**: 60fps on an iPhone, whether the
  curve *feels* right, iOS's own Reduce Motion setting, and whether the sheet animation stays in step
  with the keyboard's own slide are all untested here (Chrome on this Mac, headless, at 375×667).
- **The 900ms freshness window is a heuristic**: a content change opens it, so a re-render that
  happens *within* 900ms of a month/filter change animates a second time, and a change that lands
  later than 900ms after the bump (a slow fetch) animates nothing. Neither has been seen in practice.
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

- **`/` was `no-cache`; should it be `no-store`? — SETTLED: it is `no-store` now.** `no-cache`
  revalidates, but Starlette's `FileResponse` never answers `If-None-Match` with 304, so a load
  re-downloaded all 150 KB anyway; `no-store` additionally makes a stale standalone copy impossible.
  `tests/test_static.py::test_the_page_is_never_stored` asserts the header, and
  `tests/test_production.py` asserts it in the hardening test.
- **The Build row** (`motion N`) is a diagnostic, not a product feature: keep bumping it by hand, or
  drop it once the standalone cache question is settled?
- **Text mode hides the keypad while the card is open**, per the brief, so the amount cannot be
  tapped in while typing. If that is wrong, the keypad needs to come back for a blurred card.
- **Is excluding the tab bar and the `+` from press feedback right?** The task said they must not
  animate during a tab switch, and that is honoured; the press scale was also left off them to stay
  literal. Say the word and they get the same 0.96 spring as every other button.
- **Toast percentages are tied to its 4.5s life** (`6% / 94%` in `toast-life` against the JS timeout).
  If the toast timeout ever changes, that keyframe needs the same edit — worth a shared constant?
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
