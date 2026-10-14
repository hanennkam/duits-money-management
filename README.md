# Duits — personal expense tracker (Phase 1)

Backend that takes a **receipt photo**, a **short text note**, or a **hand-typed row**, extracts the
transaction with Claude (vision), and stores it in Supabase. Designed for Apple Shortcuts on an
iPhone, and shipped with its own iPhone-first web UI — the whole API is a static `X-API-Key` away.

9 protected endpoints, plus `/health` and the UI page at `GET /`. No auth/users, no dashboard, no
CSV/PDF import, no voice, no sync.

## Files

```
app/
  main.py          # FastAPI app, routes, error mapping, production switches
  config.py        # settings from env only: fails fast listing missing NAMEs
  auth.py          # X-API-Key dependency + per-IP throttle on failed attempts
  extractor.py     # Claude vision/text extraction -> Extraction
  db.py            # Supabase client, dedupe_hash, query/insert helpers
  models.py        # Pydantic v2 models + row/JSON shaping
  static/index.html  # the whole mobile UI: HTML + CSS + vanilla JS, served at GET /
  static/logo.png    # the app icon (180x180): the favicon, and the source the other sizes come from
  static/apple-touch-icon*.png  # 180/152/120 slots iOS probes, opaque white, served publicly
schema.sql         # transactions table, indexes, receipts bucket
tests/             # pytest: dedupe, models, auth, extractor, endpoints, production, static (83 tests)
.env.example
ctl.sh             # start / stop / status / restart, and whether the listener is stale
design/            # the Stitch screens the UI was rebuilt from (screen.png + code.html + DESIGN.md)
Handoff.md         # handoff notes for the next session
README.md
requirements.txt   # production runtime deps (what the Dockerfile installs)
requirements-dev.txt  # `-r requirements.txt` plus pytest + httpx, for local tests
Dockerfile         # production image: non-root user, no secrets baked in
.dockerignore      # keeps .env, .venv, tests and caches out of the build context
.gcloudignore      # same idea for `gcloud run deploy --source .`
pyproject.toml     # pytest config
```

## Setup

1. **Python 3.11+**

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt   # includes requirements.txt (production deps) plus pytest + httpx
   ```

   `requirements.txt` is the production set — that is what the Dockerfile installs. Use
   `requirements-dev.txt` locally, because it also pulls in the test tools.

2. **Supabase**

   - Create a project, then run `schema.sql` in the SQL editor (creates `public.transactions`,
     the `(mode, txn_date)` index, and the private `receipts` storage bucket).
   - Settings → API: copy the **Project URL** and the `service_role` key. The service key
     bypasses RLS and stays server-side only — never put it in the Shortcut.

3. **Anthropic** — create an API key at console.anthropic.com. Sonnet models support vision.

4. **Env**

   ```bash
   cp .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste as API_KEY
   ```

   `.env` is gitignored; keys are only ever read from the environment. Settings are cached at
   first use, so restart the server after editing `.env`.

## Run

```bash
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- The iPhone can't reach `127.0.0.1`: run with `--host 0.0.0.0` and use your Mac's LAN IP,
  or put a tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`) in front of it.
- `./ctl.sh status` reports whether the listener is *stale* (started before the newest source
  edit) and `./ctl.sh restart` replaces it. That matters: a server started before a new endpoint
  existed answers `405` for it, and the browser cannot tell the difference between that and a bug.

## Deploy (container host)

One image, no secrets inside it: everything is read from the environment at runtime, and the
process runs as a non-root user (`appuser`, uid 10001). `.dockerignore` keeps `.env`, `.venv`,
`tests/`, caches and `.git` out of the build context.

Environment variables — **names only**. Put the values in your host's or platform's secret store;
never commit them, never bake them into the image or pass them as build args.

| Variable | Required | Default / notes |
| --- | --- | --- |
| `API_KEY` | yes | the `X-API-Key` the clients send; generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SUPABASE_URL` | yes | your project URL |
| `SUPABASE_SERVICE_KEY` | yes | `service_role` key — server-side only, it bypasses RLS |
| `ANTHROPIC_API_KEY` | yes | Claude API key |
| `CLAUDE_MODEL` | no | defaults to `claude-sonnet-4-5` |
| `CLAUDE_FALLBACK_MODEL` | no | defaults to `claude-sonnet-5-5` |
| `RECEIPTS_BUCKET` | no | defaults to `receipts` |
| `MAX_UPLOAD_BYTES` | no | defaults to `10485760` (10 MB) |
| `ENVIRONMENT` | no | set to `production` to switch `/docs`, `/redoc` and `/openapi.json` off |
| `PORT` | no | port uvicorn binds inside the container, defaults to `8000` |

If a required variable is missing or blank, startup aborts with a message naming exactly which
ones — never their values. The rest of "Setup" above still applies (Supabase project, `schema.sql`,
private `receipts` bucket).

Build and run:

```bash
docker build -t duits .
docker run --rm -p 8000:8000 \
  -e API_KEY=... -e SUPABASE_URL=... -e SUPABASE_SERVICE_KEY=... -e ANTHROPIC_API_KEY=... \
  -e ENVIRONMENT=production \
  duits
```

Or with an env file kept outside the image (and out of git):

```bash
docker run --rm -p 8000:8000 --env-file ~/.duits.env -e ENVIRONMENT=production duits
```

Terminate TLS in front of it (platform proxy, nginx, Cloudflare) and have that proxy pass the
client address in `X-Forwarded-For` — only the first hop of that header is trusted. Failed
`X-API-Key` attempts are limited to 10 per minute per client IP, then `429` with `Retry-After`;
the counter lives in the process, so with several replicas each one throttles separately.

`/transactions*` and `/summary` responses carry `Cache-Control: no-store`, and every response
carries `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.

## Web UI (iPhone-first)

One page, no build step, no frameworks: `app/static/index.html` (HTML + CSS + vanilla JS in
a single file), served by the API itself at `GET /`. The page is public; every call it makes
still sends `X-API-Key`.

All five screens rebuilt from `design/` are built and in use — Home, Transactions, Insights, Settings
and the Add sheet — light and dark. The sticky top bar carries the app icon as a 24px rounded
(`<img class="brand-mark">`, hairline edge so its white tile stays defined on the dark bar) ahead of
the `Duits` wordmark; it measures shorter than the refresh button, so the bar's own height is
unchanged. Layout is verified in a real browser at **375×667** and
**390×844** (nothing scrolls, nothing clipped, keypad pinned) and in both themes; a per-text-node
audit finds no leftover light boxes and no text below 3.6:1 contrast in dark mode. What is *not* yet
exercised is a physical iPhone — see [Known gaps](#known-gaps).

- On your Mac: <http://127.0.0.1:8000/>
- On your iPhone, bind the server to the network and use your Mac's LAN IP:

  ```bash
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  open http://<your-mac-ip>:8000/          # same Wi-Fi as the phone
  ```

Five slots in the tab bar — Home, Transactions, the raised blue `+`, Insights, Settings — where
`+` opens the Add sheet (the only way to add now: scanning a receipt or typing a line of text).

All three data tabs share one header, rendered by a single `screenHeaderHtml()` into a
`[data-screen-header]` slot, so the three cannot drift apart: row 1 is the large title with an
`Oct 2026 ⌄` pill on the right (44px tall, `touch-action: manipulation`, nothing overlapping it),
row 2 the full-width Personal/Business toggle. Tapping the pill runs our own bottom sheet — no
`<input type="month">`, no `showPicker()`: WebKit has no month control, and there `showPicker()`
returns without throwing, so a native-first pill is silently dead on iOS. The sheet is an iOS-style
wheel: `Cancel` left, `Select Month` centre, blue bold `Done` right, a drag handle, and two snapping
columns (Month, Year) of 44px rows — five visible — behind a rounded grey band, the centred row 20px
and opaque, the ones above and below faded, with gradient fades at the edges. It opens scrolled to the
current selection; months in the future are not reachable (December of the current year springs back
to this month, and `Done` clamps), and the year column runs from the earliest year seen in loaded
rows — or two years back — up to the current year. Cancel, a tap outside, or a drag down closes it
without changing anything; the month is one `state.month`, so picking it on any tab moves the others.
Settings keeps the large title alone.

- **Home** — month picker (defaults to this month), Personal/Business toggle, and one hero card
  with total spent plus an Income/Net row (net = income − expenses, computed in the browser, red
  when negative, hidden entirely in a month with no income). Below it, **By category**: a compact
  donut (SVG, ~14px ring, rounded gaps between segments, the month's total inside over a small
  `Total` label) on the left and a four-row legend on the right — coloured dot, category name,
  `RM` amount right-aligned, percentage in small grey. Only the top three categories get their own
  row: if there are more, every remaining one is summed into a single grey `Others` row and slice,
  so the card never grows past four rows. There is no expander and no bar list any more: a small
  blue **Details** link in the card head — or a tap anywhere on the card — opens the Insights tab,
  which keeps the full breakdown. The ring is drawn by the same `donutSvg()` Insights uses, so the
  two can never disagree; Home passes the two-line variant (no transaction count) and Insights the
  three-line one. A month with no expenses shows a plain empty state instead. The recent list keeps
  Home short: newest three rows only (amount as `RM 20.80`, dates as `DD/MM/YYYY`), with **See All**
  switching to the Transactions tab. A small amber dot marks rows whose
  `raw_extraction.needs_review` is true, and the "Needs review" chip only appears while at least one
  row is flagged.
- **Transactions** — the same month and mode controls, plus a client-side search over merchant
  and category and an All/Expenses/Income filter. Rows are grouped by day ("Today", "Yesterday",
  then `DD/MM/YYYY`) with that day's net total on the right; tapping a row opens the same
  detail/edit sheet as Home.
- **Insights** — the shared header with its own **Week** / **Month** row under it (the seven days
  being read are printed in a small note below when Week is on; the pill already carries the month).
  Everything is computed in the browser from
  `GET /transactions` rows, so the totals, donut, bars, highlights and the comparison always agree:
  four cards — total spending with a "vs the previous month/week" pill and a plain sentence
  (both hidden unless the previous period has at least five expense rows *and* this period has
  spending, so a `−100%` badge never shows up over an empty month); spending by category with a
  donut (real total and transaction count in the middle), the top five categories with amount,
  share and bar, and its own **Show all N categories** expander over the full list (Home keeps the
  compact ring and folds the tail into `Others`; both rings come from the one `donutSvg()`); average by day
  (period total ÷ days elapsed, so a running month is not divided by 31) over one bar per day
  (month) or per weekday, M–S (week), heaviest bar in blue and labelled; and Key Highlights —
  highest spend day with its real date, and biggest category. Two rows, no budget.
  Plain SVG/CSS, no chart library. Three honest empty states for a period with nothing in it.
  No **Year** segment: the API only serves `?month=YYYY-MM`, so a year would need 12 requests
  (24 with the previous year for the comparison) and a per-month chart the data cannot express —
  it is hidden rather than faked. A week *is* real: it is stitched from the whole months it
  touches (one request per month, filtered to the seven days in the browser).
- **Add** (a full-height sheet opened by the raised `+`) — the Stitch "New Transaction" sheet, three ways
  in, all ending in the same row on the list. It fills one screen and does not scroll at either
  target size: `position: fixed; inset: 0` with `height: 100dvh` (a plain `100%` first as a fallback),
  `overflow: hidden`, and one flex column
  whose only flexible slot is the amount itself — so the slack on a tall phone collects around the
  number, and collapses when a panel opens or the keys step aside.
  `max-height` is forced to `none` on the id, because the base `.sheet` rule (88dvh + its own scroll)
  is declared later in the file and would otherwise win the cascade.
  The order top to bottom is: header → **Smart Entry card** → Expense/Income → amount → pills →
  Details → chips → Scan Receipt → keypad.
  - Header: `Cancel` / `New Transaction` / **Save** (blue, bold, right). Save stays disabled until the
    amount is greater than zero, and while a request is in flight it is disabled and reads `Saving…`, so
    a double tap cannot post twice.
  - Directly under the header, **always visible**: the *Smart Entry* card — the sparkle icon and the
    `Smart Entry` label, then the field and a fixed-width `Add` button (10px apart, the field flexing
    with `min-width: 0`) inside one grey card with 14px of padding. It is not an expandable row:
    nothing about the sheet opens, closes or reflows when it gets focus, and the keypad never steps
    aside for it. It posts to `POST /transactions/text`, letting Claude fill whatever it can.
    Under the chips, *Scan Receipt* (camera) is the one remaining full-width row (48px tall, 16px
    radius, the theme's light grey, icon left, grey chevron right), and it opens the camera
    roll/camera (`<input type="file" capture>`, no `getUserMedia`, so it works over plain HTTP)
    and is the only thing that reveals the privacy hint, which appears under the row once tapped: the
    photo is downscaled to 1600 px on the long edge and re-encoded as JPEG at quality 0.85 in the
    browser before upload, which keeps uploads small, strips EXIF/GPS and turns HEIC into JPEG.
  - *Expense / Income* sits directly under the header, then the big `RM 0.00`. The amount owns the
    whole flexible band — `flex: 1`, text centred, `min-height: 1.4em` so it can never be squeezed
    below its own line box — so on a tall phone the spare height becomes breathing room around the
    number instead of an empty hole above the keys. It is the only flexible row: everything else is
    `flex: none`, which is what keeps the order fixed.
  - When height runs short the layout gives way in a fixed order, never by scrolling: first the amount
    font (`clamp(40px, 8.8vh, 56px)`, so it only starts shrinking below ~636px of height and stops at
    40px), then the key height (48px → 44px below 620px). As a last resort, below 660px, the content
    column itself may scroll so nothing ever paints over the pinned keys. The two target sizes are
    clear of all of it: at 375×667 and 390×844 the number is 56px, the keys 48/56px, gaps 12/8/12 and
    nothing scrolls or clips in any state, because the collapsed Details and Smart Entry blocks are
    0 tall exactly (a 0fr grid row with the spacing inside the clip — padding on the clipped box would
    have kept 8px).
  - One row of three small pills: the **date** (`Today` / `Yesterday` / `12 Oct`, an
    invisible native `<input type="date">` over the pill opens the real picker, and nothing past today is
    accepted), **Personal/Business** (tap to toggle) and **Details**.
  - **Details** opens *Merchant* and *Note* inline between the pills and the chips. If the sheet ever
    runs out of height, that is the one area allowed to scroll, so nothing else gets cut off.
  - The category chips sit one row further down (8px under the pills), in one sideways-scrolling row,
    in their own colours. Nothing is selected by default and tapping the selected chip again clears it.
    **Personal/Business** starts on the mode of the tab behind the sheet.
  - The **keypad** is pinned to the bottom: 24px-radius container, 3 columns, 48px keys (56px from
    780px of screen height up, 44px in a short box). Focusing a text field does not move or hide it —
    the real keyboard simply covers the lower half of the sheet, which is the whole point of the sheet
    never resizing.

  **Save** posts the typed row to `POST /transactions`, so no Claude call is involved. The sheet
  closes on success with a toast, and the new row appears without a manual reload: Home (summary +
  recent), Transactions and Insights are all re-read straight away, and a row saved into a different
  month also moves the shared month pill. Every failure is visible twice over — a red toast with the
  reason plus a card floating directly above the keys (never below the fold, which is how a stale
  server's `405` once looked like a dead Save button). A `409` leaves the sheet open and shows
  "Already recorded" with the existing transaction, so nothing typed is lost. Swipe down from almost
  anywhere — the header, the amount, any empty space (or tap outside, or Cancel) — to dismiss.
- **Settings** — iOS inset groups: *Appearance* holds the System/Light/Dark segmented control,
  *Security* holds one tappable row (blue key icon, "API key",
  live "Saved on this device" / "Not set" value) that opens the change-key sheet, and *About*
  lists App, **Build**, Currency and Date format as plain read-only rows. The Build row is the one
  way to see *on the phone* whether the Home Screen app is running the current page: it prints the
  stamp plus the status bar style the meta ended up with and whether it is running standalone. Bump
  it whenever `index.html` changes, and if the shortcut shows an older stamp it is serving a cached
  document.
  There is no service worker here — the page is the only asset, with its CSS and JS inline.

The API key is asked for on first load and kept in `localStorage` under `apiKey`; it is never
in the HTML or in this repo. A `401` clears it and re-prompts. Add to Home Screen works like an
app: PWA meta tags plus four icon links — `apple-touch-icon.png` (180), `-152x152`, `-120x120` and
`logo.png` as the favicon — each with a `?v=` cache-buster and served publicly with
`Cache-Control: public, max-age=600` (deliberately *not* immutable; the `?v=` is what invalidates
iOS's Home Screen icon, which iOS keys on the URL). The files are opaque white and square — iOS
paints an icon's transparency black and applies its own rounded mask — and `GET /` itself is
`Cache-Control: no-store`, so a shortcut can never be built from stale HTML. **When the icon art changes, bump the
`?v=` in `app/static/index.html`**, or the phone keeps showing the old tile. There is no service
worker, so nothing is cached offline.

### Home Screen: full screen, status bar and home indicator included

The standalone app is edge to edge, in both themes:

- `<meta name="viewport">` carries `viewport-fit=cover`, which is what lets the page reach under the
  status bar and the home indicator; `apple-mobile-web-app-capable=yes` plus
  `apple-mobile-web-app-title` make the shortcut launch as an app rather than a Safari tab.
- **`html` paints the whole screen** (`background: var(--bg)`), so the strip behind the status bar and
  the one behind the home indicator are the theme's own background, never a band of another colour.
  `theme-color` is kept in step (#F2F2F7 light / #000000 dark) for the surfaces iOS paints itself.
- The nav bar's safe-area inset is **padding, not a margin**, so its frosted background extends up
  behind the clock while its content (the `Duits` mark and the refresh button) starts below it.
  The tab bar pads its bottom the same way, so its last row clears the home indicator.
- Every inset has one name — `--sat`, `--sab`, `--sal`, `--sar`, each resolved once from `env()`
  at `:root` — so a probe (or a device without a notch) has a single place to simulate them. Nothing
  else in the file calls `env()` directly.
- **The Add sheet is a full-screen page**: `position: fixed; inset: 0; height: 100dvh`, with
  `padding-top: max(var(--sat), 8px)` so Cancel / New Transaction / Save always sit fully below the
  status bar, and the keypad pads its bottom by `--sab`. It is deliberately *not* sized from
  `window.innerHeight`: in a standalone app that is not the screen, and pinning it in pixels is what
  used to push the sheet's head under the status bar. The edit sheet and the month wheel get the same
  treatment from the overlay they live in: `padding: max(var(--sat), 12px) 12px calc(12px + var(--sab))`
  and a `max-height` of `min(88dvh, 100dvh - the insets)`, so a tall sheet cannot reach either edge.
- **When the box is short, the sheet gives height back instead of scrolling.** The insets are real
  space (a 375×667 screen with a 47px status bar has 586px of sheet), so three container queries on
  the sheet's own box step in: 44px keys and tighter gaps and a smaller amount floor under 640px,
  40px keys under 560, and a scroll of the content column only under 500. A phone with no notch keeps
  every size it was tuned with, because 667px of box trips none of them.
- **The status bar style is theme-aware, and that is the honest answer.** `black-translucent` is what
  the page ships (it is what lets the page paint under the bar), but iOS gives it **white** glyphs,
  and the light theme's bar is `rgba(249, 249, 249, .85)` — white on near-white is unreadable. So the
  pre-paint script (and the theme switch) keep `black-translucent` for dark and ask for `default`
  (black glyphs) for light: the only two glyph colours iOS offers, chosen by the theme that is already
  decided before the first paint. Full-screen-ness is unaffected, because `viewport-fit=cover` and the
  safe-area padding are what put content under the bar; whatever iOS decides, `env()` reports the truth
  and the layout follows it. The alternative — `black-translucent` in both themes — needs the light
  theme's top strip darkened to a band, which is the colour hack this deliberately avoids.
- The **Build** row in Settings prints the stamp, the status bar style the meta ended up with and
  whether it is running standalone, so a phone can be asked what it actually loaded.

### Splash

Every cold launch opens on a splash, and nothing else ever shows it — tab switches, month changes,
sheets and refreshes do not touch it (`splashHidden` is one-way per page load).

- **Painted on the first frame.** The overlay and its styles are the first things in `<body>`, above
  the app markup, and its background is the theme's own `--bg` (#F2F2F7 / #000000, already resolved by
  the pre-paint script in `<head>`), so there is no colour jump when it fades — and no chance of the
  app flashing through, because it is opaque and `z-index: 9999`.
- **What is on it**: `logo.png` at 96px with a 22px radius and a two-layer soft shadow so it reads as
  an app icon on a white *and* a black page, `Duits` at 28px/700 in `--text`, 16px under it. Nothing
  else — no spinner, no tagline. The inset padding uses `--sat`/`--sab`, the same variables as the
  rest of the app.
- **The wordmark never moves**: the waking-up line lives in a `height: 0` wrapper whose `-16px` margin
  cancels the flex gap, so it appears under `Duits` without shifting the centred group.
- **Entrance** is a CSS animation (400ms, logo `scale(.94) → 1` with a fade), so it starts with the
  first paint rather than waiting for the script.
- **It goes when both are true**: the first data load has settled (loaded *or* failed) and
  `SPLASH_MIN_MS` (1200ms) has passed — so a warm cache still shows it for exactly the minimum, and a
  slow one is never cut short. `start()` calls the same `splashSettled()` when the key dialog takes
  over (that dialog is the next thing the user has to touch), after `await loadHome()`, and from the
  `.then` on the boot promise, so a boot that throws still hands the screen over.
- **If the load takes more than 4s** (`SPLASH_WAKING_MS`) a 14px grey line fades in under the
  wordmark: "Waking up the server…" — the Render free instance's cold start, said out loud.
- **Nothing can leave it up**: `SPLASH_MAX_MS` (60000) hides it regardless and, if the app itself
  painted nothing (a hung request never reaches `loadHome`'s catch), writes the same error card the
  loader would have.
- **Exit** is the Web Animations API: opacity `1 → 0` over `SPLASH_FADE_MS` (300ms) with the logo
  scaling to 1.04, then `visibility: hidden` and `pointer-events: none` — never `display: none` while
  it is animating, and a timer backs the animation up. Reduce Motion drops the scale and fades in
  150ms.
- **While it is up it is locked**: it covers the app, so no tap can reach it, and `touch-action: none`
  plus `overscroll-behavior: contain` stop a swipe from scrolling the page underneath.

### iOS touch behaviour

Safari's own gestures are kept out of the way, because each one breaks the sheet:

- **No focus zoom.** Every control a finger can focus is at least **16px** — `.add-field` (Smart Entry,
  Merchant, Note), the Search field, and the invisible `<input type="date">` over the date pill (it is
  `opacity: 0` but still focusable). `.field`, used by the API-key and edit sheets, is `font: inherit`
  from the 17px body. A focused control under 16px makes iOS zoom the whole page in, which is what was
  cutting the Smart Entry field and its `Add` button off on the right. `maximum-scale=1` is also in the
  viewport meta, but the font size is the real fix (iOS has ignored `maximum-scale` for pinch since
  iOS 10 — so pinch-zoom still works, as it should).
- **No double-tap zoom.** `touch-action: manipulation` on `html`, `body`, `button` (every tappable
  thing here is one, keys and chips and tabs included) and the date `<label>`. The Add sheet is
  `touch-action: none` so a swipe anywhere on it is a dismiss rather than a pan, with the two scrollers
  handed back their own gestures (`pan-x` on the chips, `pan-y` on the expanded Details row). The edit
  sheet still scrolls, so only its head and amounts are locked. Keys are `-webkit-tap-highlight-color`-free and `user-select: none`, while
  inputs keep selection so a typed line stays correctable.
- **No sideways scroll.** `html, body { overflow-x: hidden; max-width: 100vw }`, `box-sizing:
  border-box` throughout, `min-width: 0` on the flexing field. The only things off the right edge are
  the category chips, which live in their own horizontal scroller by design.
- **Keyboard.** The Add sheet does not react to the keyboard at all. It is one fixed full-screen page
  (`inset: 0`, `100dvh`) and the page behind it is scroll-locked while it is open,
  so there is no `visualViewport` reading, no `--vvh`, no scroll-into-view and no layout change —
  the keyboard simply covers the lower half, which is acceptable because the Smart Entry field is at
  the top. `focus()` is always called with `{ preventScroll: true }` so Safari never pans the page to
  "help", and nothing in the sheet can zoom: every focusable control is at least 16px and the viewport
  meta pins `maximum-scale=1`.

### Swipe to dismiss

The Add sheet and the edit sheet close by swiping down from almost anywhere, because reaching for the
grabber with a thumb is the one gesture a phone should not require. One implementation,
`attachSheetDrag(sheetId, overlayId, onDismiss, handleOnly)`, in `app/static/index.html`:

- **pointerdown / move / up on the sheet**, with `setPointerCapture` so the sheet keeps the gesture
  even when the finger leaves it. A second finger never steals it (`isPrimary`).
- **A drag only starts where nothing else has a gesture.** `DRAG_BLOCKERS` is one selector — buttons,
  links, labels, inputs, selects, textareas, `.key`, `.keypad`, `.chip-scroll`, `.cat-chip`,
  `.add-rows` (Scan Receipt), `.smart-card` (Smart Entry), `.add-pills`, `.add-details`,
  `.sheet-actions`, the wheel — and `.no-drag` is the escape hatch for anything added later. The
  header, the amount, the grabber and empty space are all fair game.
- **It is claimed only once it is a downward drag**: more than 8px of movement
  (`DRAG_START_PX`) and more vertical than horizontal (`|dy| > |dx|`). An upward or sideways movement
  does nothing at all, so a tap with a wobble and a scroll never fight the sheet.
- At that moment the finger takes over: any running open/close animation is **cancelled**
  (`cancelOverlayMotion`), a focused input is **blurred** so the keyboard closes with the drag, the
  sheet follows `translateY(dy)` with no animation, and the scrim's opacity thins with the distance
  (never below 0.3, so the screen behind stays readable).
- **On release** it closes if the sheet is more than `DRAG_CLOSE_PX` (120px) down *or* the last
  movement was faster than `DRAG_CLOSE_VELOCITY` (0.5 px/ms — a quick flick counts from much less than
  120px), continuing from the finger's exact offset through the same Web Animations close
  (`closeOverlay(element, after, fromOffset)`). Otherwise it springs back to 0 over 250ms.
- **It can never stick.** `pointercancel` clears the inline transform and scrim opacity, the spring's
  cleanup is token-guarded so a new press invalidates a settling one, the close drops every inline
  style on the way out, and the close keeps its own timer fallback.
- **Reduce Motion**: no spring animation (the sheet snaps home), and the close keeps its
  opacity-only fade. The gesture itself behaves identically.
- **The month wheel keeps its grabber-only drag** (`handleOnly: true`): its columns scroll vertically,
  so a drag on its body would fight them.

### Motion

Everything animates **transform and opacity only** (plus SVG `stroke-dasharray` for the ring), so no
animation can trigger layout on a phone. One curve, four durations, all in `:root` next to the
palette: `--ease-ios: cubic-bezier(0.32, 0.72, 0, 1)`, with `--dur-sheet: 350ms`, `--dur-page: 180ms`,
`--dur-press: 100ms` and `--dur-toast: 250ms`. No animation library, no JS tweening.

- **`replay(element, className)`** is the one way anything restarts: remove the class, force a reflow
  (`offsetWidth`), add it back. Every entrance calls it — a tab becoming active, a month changing,
  every data render, the ring, the bars, the row stagger — because an animation or transition hung
  off a `display` change only plays the first time on iOS. There is no freshness window any more:
  the call site *is* the signal, so a refresh replays too (what the phone wanted) and nothing depends
  on a timer that could be missed.
- **Sheets** (Add, edit, month picker, key dialog) are mounted permanently and move on the **Web
  Animations API**: `openOverlay()` animates the sheet `translateY(100%) → 0` and the scrim
  `opacity 0 → 1` (350ms, `--ease-ios`, `fill: both`), and `closeOverlay()` animates them back and
  applies the closed state only when the animation reports `finished` — with a **500ms fallback
  timer** so a close can never stick. Every open **cancels** whatever is still running *and* bumps a
  close token, so ten fast open/close pairs land on the right state every time and a close still in
  flight cannot re-close a sheet that has been reopened. The class is only *state* (`opacity: 0;
  visibility: hidden; pointer-events: none` when closed — never `display: none`), and there is
  deliberately **no CSS transition on the overlay at all**, which is exactly what iOS played once and
  then ignored. A downward drag cancels whatever animation is running, hands the transform to the
  finger and releases into the same exit (see *Swipe to dismiss* below).
- **Presses**: one shared rule — `button:not(.tab):not(.tab-add), .add-pill` scale to
  `var(--press-scale)` (0.96) and dim to 0.7 while held, springing back on release. The tab bar and
  the raised `+` are excluded on purpose; the date pill's hit target is the invisible native input
  above it, so it does not scale. iOS only applies `:active` to a `<button>` when the document has a
  touch listener, so `wire()` adds one empty passive `touchstart` — without it the spring never
  appears on a phone at all.
- **Pages**: a switch fades the incoming screen in with a 6px rise. The `.screen` wrappers contain
  neither the tab bar nor `+`, so those never move.
- **Month change**: `setMonth()` records the direction (older from the left, newer from the right) and
  marks the content fresh; the visible screen's blocks slide 20px and fade in.
- **Toast**: one `toast-life` animation covers its whole 4.5s life — in from above, hold, fade out —
  so the fade needs no second timer.
- **Ring, bars and rows**: each ring segment is a **path arc**, not a circle, precisely so the draw
  can be a plain `stroke-dashoffset` transition (a dash you can slide into view on a closed circle
  cannot grow — it just moves). Each arc carries its own `--len`, starts at that offset and is
  transitioned to 0 with a 60ms per-segment stagger, so it sweeps clockwise over 600ms. Category
  bars grow with `scaleX`, the day chart with `scaleY` (their `width`/`height` stay layout sizes — the
  old `transition: width`/`height` are gone); rows rise in with a 30ms stagger, first eight only
  (`--i` is capped in `txnRowHtml`).
- **Save**: `afterAdd()` waits for the sheet's **close animation** *and* for both lists to come back
  (`Promise.all([loadHome(), loadTransactions(), closed])`) before `flashRow(id)` runs, because a flash
  behind a closing sheet is a flash nobody sees. `flashRow` matches the row by `data-id` in every list
  that holds it — Home's *Recent Transactions* and the Transactions tab — and animates the row's own
  `background-color` on the Web Animations API: `--accent-soft` for the first 600ms of an 1800ms
  timeline, then an eased fade to the same colour at zero alpha (`fadeToClear` strips the alpha so the
  fade keeps its hue instead of drifting through grey). Timing is linear with the curve on the fade
  keyframe, or the ease would compress the hold and start fading at once. A class would be wiped by
  the next render; all three save paths (keypad Save, Smart Entry, Scan Receipt) funnel through
  `afterAdd`, so all three flash.
- **The Add sheet never changes layout.** It is one fixed page: `openAddSheet()` pins its height in
  pixels to `window.innerHeight` at the moment it opens and locks the page (`html`/`body`
  `overflow: hidden`, restored on close, `unlockPageScroll()` released before anything can throw), and
  then **nothing measures or follows the keyboard** — no `visualViewport`, no `--vvh`, no scroll-into-
  view helper, no hidden keypad, no `data-text-mode`. The Smart Entry input sits at the very top, so
  the keyboard only ever covers the lower half of a sheet that does not resize;
  `focusWithoutScroll()` calls `focus({ preventScroll: true })`, and the keypad stays exactly where it
  is. The trade is deliberate: while the keyboard is up, the keys below it are unreachable until it is
  dismissed.
- **Reduced motion**: `prefers-reduced-motion: reduce` zeroes the `--move-*` distances (fades stay, at
  150ms) and sets `--press-scale: 1`, and the three "movement with no fade-only equivalent" pieces —
  the ring draw, the bar grows and the row stagger — are switched off entirely (the ring is pinned to
  `stroke-dashoffset: 0`, i.e. drawn, not left at its hidden offset).

### Dark mode

*Appearance* in Settings is System / Light / Dark, stored in `localStorage` under `duitstheme`
(both read and write are wrapped in `try/catch`, so private mode degrades to "follow the phone"
instead of throwing). It applies immediately — no reload — and System re-applies live when the
phone's theme changes (`matchMedia("(prefers-color-scheme: dark)")`, with an `addListener`
fallback for older Safari).

Every colour is a CSS variable: light values on `:root`, the dark palette on
`[data-theme="dark"]` (set on `<html>`), and nothing else in the file names a colour. The dark
palette is iOS: `#000` page, `#1C1C1E` cards, `#2C2C2E` raised surfaces and the segmented track,
white primary text, `#8E8E93` secondary, `rgba(84,84,88,.6)` hairlines, `#0A84FF` accent,
`#30D158` income, `#FF453A` red, `#FF9F0A` orange, and a frosted `rgba(28,28,30,.85)` tab bar.
Category hues are unchanged — only the tint behind their icons dims, from 14% to 18% over a dark
card (`--tint-alpha`, which `tint()` reads out of CSS so the alpha has one home) — and each tinted
box takes its hue from an inline `--cat`, not from a hardcoded colour in the markup.

Two details that are easy to get wrong, so they are pinned:

- a tiny inline script in `<head>` sets `data-theme` **before** the first paint, so a dark phone
  never flashes a white page (it also seeds `theme-color` and the iOS status bar style);
- the theme switch keeps `<meta name="theme-color">` (#F2F2F7 / #000000), the status bar style
  (default / black-translucent — see *Home Screen* below) and `color-scheme` (so native inputs and
  the date picker follow) in step with the palette.

Checked in a real browser at 375×667, 375×812 and 390×844 across 17 states in each theme — Home,
Transactions, Insights (week + month), Settings, the Add sheet (keypad, chips, Details, Smart Entry,
warn/error toast, error card), the edit sheet, the month wheel, empty states and the key dialog: no
light boxes survive in dark and no text falls below 3.6:1 against its real background. The checker is
calibrated — two deliberately invisible samples are flagged every run — so a clean pass means
something.

## API

All of these except `/health` need the header `X-API-Key: <API_KEY>`.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/health` | – | `{"status": "ok"}` (no auth) |
| POST | `/transactions/scan` | multipart: `file` (jpg/png/webp), optional `mode` | 201 created transaction |
| POST | `/transactions/text` | JSON `{"text": "...", "mode": "personal"}` | 201 created transaction |
| POST | `/transactions` | JSON: `amount` (required), `txn_date` (default today), `merchant`, `category`, `type`, `mode`, `note` | 201 created transaction (422 bad value or unknown field, 409 duplicate) |
| GET | `/transactions?month=YYYY-MM&mode=personal` | – | 200 list, newest first |
| GET | `/summary?month=YYYY-MM&mode=personal` | – | 200 totals |
| GET | `/transactions/{id}` | – | 200 one transaction (404 unknown, 422 non-UUID id) |
| PATCH | `/transactions/{id}` | JSON, any of `txn_date`, `amount`, `merchant`, `category`, `type`, `mode` | 200 updated transaction (422 bad value or unknown field) |
| DELETE | `/transactions/{id}` | – | 204 empty body — deletes the row **and** its receipt object |
| GET | `/transactions/{id}/receipt-url` | – | 200 `{"url": "…", "expires_in": 60}` (404 if the row has no receipt) |


### curl

```bash
export API_KEY="paste-the-key-from-your-.env"
BASE=http://127.0.0.1:8000

# health (no key)
curl -s $BASE/health

# scan a receipt photo
curl -s -X POST $BASE/transactions/scan \
  -H "X-API-Key: $API_KEY" \
  -F "file=@receipt.jpg;type=image/jpeg" \
  -F "mode=personal" | python -m json.tool

# plain text
curl -s -X POST $BASE/transactions/text \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "makan tengah hari 12 ringgit", "mode": "personal"}'

# typed by hand, no Claude call: note is kept in raw_extraction.note
curl -s -X POST $BASE/transactions \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": 12.5, "txn_date": "2026-10-11", "merchant": "Kopitiam Ali",
       "category": "food", "type": "expense", "mode": "personal", "note": "lunch"}'

# one month, newest first
curl -s "$BASE/transactions?month=2026-03&mode=personal" -H "X-API-Key: $API_KEY"

# totals for the month
curl -s "$BASE/summary?month=2026-03&mode=personal" -H "X-API-Key: $API_KEY"
```

### Managing one transaction (curl)

Same `$API_KEY` / `$BASE` as the block above. `$ID` is the **newest** transaction of the current
month — the list is newest first, so `d[0]` is the top row of the app's Recent list.

> **Warning — the last command here is destructive and cannot be undone.** `DELETE` permanently
> removes the transaction **and its receipt photo from the Storage bucket**. Because `$ID` is
> resolved as "newest transaction", running this block on a live month deletes the receipt you
> just scanned. Run it only against a **throwaway test row**: scan or type a deliberate test entry
> first, check `echo "$ID"` prints that row (and not a real receipt) before you continue, and never
> run the `DELETE` line over data you want to keep.

```bash
ID=$(curl -s "$BASE/transactions?month=$(date +%Y-%m)&mode=personal" -H "X-API-Key: $API_KEY" \
     | python -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["id"] if d else "")')
echo "$ID"   # confirm this is the row you mean before going further

# fetch one transaction
curl -s "$BASE/transactions/$ID" -H "X-API-Key: $API_KEY" | python -m json.tool

# correct it: only the fields you send are applied, "" clears the merchant.
# A manual edit also sets raw_extraction.needs_review to false and refreshes dedupe_hash.
curl -s -X PATCH "$BASE/transactions/$ID" -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": 16.20, "txn_date": "2026-10-20", "merchant": "Kopitiam Ali",
       "category": "groceries", "type": "expense", "mode": "personal"}' | python -m json.tool

# signed URL for the private receipt, valid for 60 seconds.
# Receipt scans only: a text entry has no photo and answers 404 here, and so does a
# receipt row whose object is missing. To target one with a photo, pick the row whose
# "receipt_path" is not null instead of d[0].
URL=$(curl -s "$BASE/transactions/$ID/receipt-url" -H "X-API-Key: $API_KEY" \
      | python -c 'import json,sys; print(json.load(sys.stdin).get("url", ""))')
echo "$URL"                          # empty when this row has no receipt photo
[ -n "$URL" ] && open "$URL"         # open it before the 60 seconds are up

# DESTRUCTIVE: deletes the row and its receipt object, 204 with an empty body
curl -s -i -X DELETE "$BASE/transactions/$ID" -H "X-API-Key: $API_KEY"
```

Failure paths (nothing is modified by these three):

```bash
curl -s -o /dev/null -w 'no key:       %{http_code}\n' "$BASE/transactions/$ID"
curl -s -o /dev/null -w 'unknown id:   %{http_code}\n' \
  "$BASE/transactions/99999999-9999-9999-9999-999999999999" -H "X-API-Key: $API_KEY"
curl -s -o /dev/null -w 'bad category: %{http_code}\n' -X PATCH "$BASE/transactions/$ID" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"category": "foods"}'
```

Response of `/transactions/scan` (abridged):

```json
{
  "id": "0d3f…",
  "created_at": "2026-03-04T01:02:03.456789+00:00",
  "txn_date": "2026-03-04",
  "amount": 12.5,
  "currency": "MYR",
  "merchant": "Kopitiam Ali",
  "category": "food",
  "type": "expense",
  "mode": "personal",
  "items": [{"name": "Nasi lemak", "qty": 1, "price": 5.5}],
  "receipt_path": "2026/03/0d3f….jpg",
  "source": "receipt_scan",
  "dedupe_hash": "b696…",
  "raw_extraction": {"needs_review": false, "extraction": {"…": "full model output"}}
}
```

`amount` is always a JSON number. To decide whether a row needs a human look, read
`raw_extraction.needs_review` (true when Claude could not read the amount or the merchant).


## Apple Shortcuts (iPhone)

Optional now that the web UI exists — the UI covers the same ground on the phone, so a Shortcut is
for the cases where you want one tap from the Lock Screen, the share sheet or a photo without opening
Safari. Both write the same rows.

1. **Take Photo** / **Select Photo** → **Get Contents of URL**
   - URL: `https://<your-host>/transactions/scan`, Method `POST`
   - Headers: `X-API-Key` = your key
   - Request Body: **Form**, with `file` = the image and `mode` = `personal`
   - Shortcuts sends `image/jpeg`, which is accepted directly. If you get a HEIC original,
     convert it first (**Convert Image** to JPEG) — HEIC is intentionally not supported.
2. Text version: same host with `/transactions/text`, Body **JSON**:
   `{"text": "makan tengah hari 12 ringgit", "mode": "personal"}`.
3. A `409` means the receipt is already recorded — the body carries the existing row, so the
   shortcut can just show "already saved". Only receipt scans dedupe; `/transactions/text`
   never returns `409`.
4. A `422` means Claude could not read the receipt — prompt the user to re-shoot.

## Behaviour notes

- **Extraction** (`extractor.py`): Claude is asked for JSON only, with Malaysian-receipt rules
  (RM unless the receipt says otherwise, total actually paid rather than subtotal, DD/MM/YYYY
  dates, today's date when the date is missing, `null` instead of guessing). The reply is
  validated with Pydantic, retried once if it is not usable, then rejected with `422`.
- **Dedupe**: only receipt scans with a readable merchant are deduped. `dedupe_hash` = sha256 of
  `txn_date|amount(2dp)|lowercased merchant`; text notes and merchant-less receipts store
  `dedupe_hash = NULL` (Postgres allows many NULLs under a unique index) and therefore always
  insert — two text entries of RM12 on the same day are two different transactions, so
  `/transactions/text` never returns `409`. Hand-typed rows through `POST /transactions` behave
  the same way (`source = "manual"`), so two identical manual entries both insert; the `409`
  branch is still wired to the same `_duplicate()` guard the receipt scan uses, so the moment the
  dedupe policy covers another source the endpoint answers `409` with the existing row. When a
  hash is present the API looks it up first and
  returns `409` with the existing row instead of inserting. The unique index is the real
  guarantee: a rare concurrent double-submit would surface as a 500 but can never create a
  duplicate row. The receipt image of a rejected duplicate stays in the bucket (harmless).
- **Status codes**: `400` bad file, file type or `month`; `401` missing/wrong key; `409`
  duplicate; `413` over the 10 MB limit (`MAX_UPLOAD_BYTES`); `422` extraction failed; `502`
  Claude or Supabase Storage failure.
- **Upload limit**: 10 MB, enforced by reading at most limit + 1 bytes.

## Known gaps

- **A stale Home Screen app is now ruled out by the header.** There is no service worker and no
  external CSS/JS — the page *is* the asset — and `GET /` sends `Cache-Control: no-store` (verified on
  the running server), so no copy of the document can be served from cache at all. The **Build** row
  in Settings remains the way to check what a phone actually loaded; if its stamp is older than the
  server, the shortcut needs deleting and re-adding. The cost is re-downloading a ~150KB page every
  launch, which is the right trade for an app whose only asset is that page.
- **The splash's timing is measured in Chrome, not on a phone.** The probes show the minimum hold,
  the 4s waking line, the 60s backstop (in the harness, with fake timers), the side effects of a
  failing API and that it never returns; what they cannot show is how the 1200ms feels on a cold
  iPhone launch, whether Safari's own launch image (a blank screen before the page paints) makes the
  splash feel late, or whether the logo's first paint is as prompt on a device as it is in a warm
  browser cache. The logo is a 180px PNG served with `max-age=600`, so a truly cold install may show
  the icon a beat after the wordmark.
- **The gesture's arbitration against iOS's own is reasoned, not tested.** The probes drive synthetic
  pointer events, so they prove the app's state machine (thresholds, velocity, cancel, spring, the
  exclusions) and nothing about how a real finger is arbitrated: whether iOS delivers `pointercancel`
  instead of `pointermove` when a drag begins over a `touch-action: pan-y` region of the edit sheet,
  whether a real finger on the chips row still scrolls while the sheet listens for pointers, and how
  the scrim looks mid-drag. Locking the whole Add sheet with `touch-action: none` is what makes that
  one reliable; the edit sheet keeps scrolling, so its header is the drag-locked part.
- **The iOS status bar can only be reasoned about, not tested, from here.** `black-translucent` is
  shipped and the theme swap is decided before the first paint, but whether iOS re-reads that meta on
  a relaunch (rather than only at install) cannot be checked without a device. If it does not, a light
  theme would show white glyphs over the near-white bar; the fallback would be to keep `default` in
  both themes (`theme-color` still matches the bar, so the top looks continuous either way).
- **Not yet run on a physical iPhone.** Everything is verified in a desktop browser sized to the
  phone, so these remain open: WebKit's own Web Animations timing against the built-in keypad, whether
  iOS really leaves the page alone now that it is scroll-locked and nothing calls `focus()` with a
  scroll (the probes prove the code *asks* for nothing — `visualViewport` is faked to emulate the
  keyboard), whether iOS honours `maximum-scale=1`, a double tap on the keypad, the native date picker
  raised from inside the sheet, actual `env(safe-area-inset-*)` values, and a receipt scan end to end
  (camera → HEIC → upload). The animations are the same story: their timing, travel and resting state
  are measured in Chrome over CDP on real timers, but 60fps on a real iPhone, the *feel* of the curve,
  iOS's own reduced-motion switch (the media query was emulated) and the keyboard's own animation
  staying in step are not.
- **No `Year` segment in Insights** — the API has no range query (see the Insights bullet above); it
  needs a `?from=&to=` endpoint before a year can be honest.
- **`.env.example` does not list `CLAUDE_FALLBACK_MODEL`**, although `config.py` defaults it to
  `claude-sonnet-5-5` and `extractor.py` uses it — a deployment copied from the example silently gets
  the default. The env table under *Deploy* is the complete list.
- **Below 660px of viewport height** the Add sheet's content column may scroll (it is the last resort
  that keeps anything from painting over the pinned keys). Both target sizes are well clear of it, but
  an SE-class screen with Details open cannot show every row at once. Same story at 375×667 in one
  state: the Smart Entry card open while the keyboard is dismissed (keypad back on screen) is 32px
  taller than the row it replaced, so the column scrolls rather than hiding Scan Receipt.
- **Home's ring has three cosmetic ceilings**: a slice under ~2% draws as the minimum round dot; the
  legend folds the tail into a grey `Others`, so a month holding both a real `other` category and a
  grouped tail shows `Other` *and* `Others`; and a 6-figure month total fills the hole.

## Tests

```bash
pip install -r requirements-dev.txt   # requirements.txt alone is production-only (no pytest, no httpx)
pytest
```

83 tests, no network and no API key needed — Claude is monkeypatched at `extractor._call` and
the Supabase helpers at `app.db.*`: dedupe policy (receipts with a merchant dedupe; text notes
and merchant-less receipts do not, and two text entries of the same amount on the same day both
insert), hand-typed rows (`source = "manual"`, note kept in `raw_extraction.note`, empty category
stored as null, defaults for a bare amount, and the `409` guard), month bounds, model
validation/defaults/JSON shape, the auth dependency, and
extraction parsing/retry plus the image payload, and the app icon (four public URLs with the right
`Cache-Control`, absent from the schema, versioned in the page, and each file an alpha-free PNG at
the square size its slot expects).

### UI checks

The pytest suite above covers the API only; the UI has no committed test suite yet. It is checked
with a scratch Node harness that evals the page's `<script>` and asserts 755 things about the
markup, the CSS and the behaviour (theme plumbing and palette, Add-sheet order, the shrink ladder,
the icon links and the removal of the runtime canvas icon, the iOS touch rules — a 16px floor on
controls, `touch-action: manipulation` — the motion tokens and every animation
declaration, which areas may scroll, Save gating, keypad visibility) — plus headless-Chrome probes
and screenshots at 375×667 and 390×844 in both themes. Those probes report the computed font size of
every focusable control, the computed `touch-action` per element, any element crossing the viewport
edge, the Smart Entry card geometry, and a simulated keyboard (a faked `visualViewport` shrinking to
43% of the screen) to prove that **nothing moves**: the sheet keeps its size and position, the
amount and keypad stay at the same coordinates, the keypad stays on screen, the page does not scroll
and the layout does not overflow sideways.
The splash is measured over CDP too: with a normal stub it is visible while the probe starts
(`z-index: 9999`, covering the viewport, `touch-action: none`, `elementFromPoint` at the centre
resolving to the splash itself), the logo is 96×96 at a 22px radius with its shadow, `Duits` is
28px/700, the gap under the logo is exactly 16px, the logo+wordmark group is centred to the pixel, the
hint is present but at `opacity: 0`, and the background is `rgb(242, 242, 247)` in light and
`rgb(0, 0, 0)` in dark. It then hides ~1290ms after the script ran, leaves `visibility: hidden`,
`opacity: 0`, `pointer-events: none` and `aria-hidden`, hands hits back to the app, and stays hidden
through a tab switch, a month wheel, an add sheet and a refresh. With the stub slowed to 5.2s
(`?slow`) the hint fades in at 4.2s and the splash goes at 5.7s; with the stub failing (`?fail`) the
splash hides at ~1.25s with the app's own `error-card` visible behind it; under `--reduced-motion` the
logo uses the opacity-only keyframes and the whole lifetime sees a single animation (no scale).

The swipe-to-dismiss gesture is exercised with synthetic pointer sequences (`pointerdown` → moves →
`pointerup`/`pointercancel`) in the same harness: a 200px drag from the header, from the amount and
from the sheet's own empty space all follow the finger (`translateY(200px)` mid-drag, scrim at 0.745)
and close; a slow 60px drag springs back to 0 with the overlay still open; a 70px flick closes
(velocity, not distance); upward and sideways drags move nothing; a 6px wobble on a keypad key, in the
chips row, on the Smart Entry card, on Scan Receipt and on Save leaves the sheet open (and the key
still types `RM 5`); a drag with the Smart Entry field focused blurs it and closes; `pointercancel`
midships leaves the sheet at rest and open; ten drag-close cycles end `10/10` closed with nothing
stuck and no inline styles left; the edit sheet closes from its title; the month wheel stays open when
its columns are swiped and closes from its grabber; and 60ms into the open animation a drag cancels
it and takes over. Under `--reduced-motion` the same script closes on a long drag, settles on a short
one with **zero** spring animations, and still takes the transform from a running animation.

The safe-area probe runs with the notch insets simulated (47px/59px top, 34px bottom, set through the
`--sat`/`--sab` variables) at 375×667, 390×844 and 430×932: it checks that the nav bar's background
reaches y=0 while its content starts below `--sat`, that the tab bar reaches the bottom edge while
its last row clears `--sab`, that the Add sheet is a full-screen page (`top=0`, height = the viewport,
`position: fixed`, `padding-top` = the status bar inset) whose Cancel button and last key row both
clear the insets, that the month wheel sits between them, that nothing reachable is clipped or
scrolled, and that the sheet's container-query shrink (44px keys at 375×667, 56px at the two taller
sizes) is what makes that fit possible.
Animation is measured over CDP in a real Chrome on real timers, at an exact 375×667 / 390×844 device
viewport: ten open/close pairs (10/10 open, 10/10 close, nothing stuck, the sheet back at
`translateY(667px)`, no running animations left, no thrown errors), ten tab switches (the ring's dash
offset is back at 100+ of its 128.25 length 50ms after re-entry every time), a month change (wheel
mid-slide, rows at `opacity 0.99` and `--i:0`), the save path end to end with the preview stub
creating a row (nothing at +255ms while the sheet is still open, then `rgba(10, 132, 255, .18)` in
*both* lists at +508ms, holding to 600ms and fading to 0 by 1800ms), the Smart Entry save path, and
again with `--force-prefers-reduced-motion` (opacity-only fades, `move-sheet: 0%`, sheets still
opening and closing, the ring already drawn). Note that headless `--virtual-time-budget` **freezes animations and
transitions**, so every number it produces for anything animated is meaningless — the older probes
are kept for static checks only. That harness lives outside the repo today;
moving it in (e.g. `tools/`) is the first item in `Handoff.md`.
