# Duits — personal expense tracker (Phase 1)

Backend that takes a **receipt photo**, a **short text note**, or a **hand-typed row**, extracts the
transaction with Claude (vision), and stores it in Supabase. Designed for Apple Shortcuts on an
iPhone, and shipped with its own iPhone-first web UI — API calls are authenticated with a Supabase sign-in token (`Authorization: Bearer`); a temporary legacy key sits behind a flag.

9 protected endpoints, plus `/health` and the UI page at `GET /`. No auth/users, no dashboard, no
CSV/PDF import, no voice, no sync.

## Files

```
app/
  main.py          # FastAPI app, routes, error mapping, production switches
  config.py        # settings from env only: fails fast listing missing NAMEs
  auth.py          # Supabase JWT verification (JWKS), owner id from `sub`, per-IP throttle; optional legacy key
  extractor.py     # Claude vision/text extraction -> Extraction
  db.py            # Supabase client, dedupe_hash, query/insert helpers
  models.py        # Pydantic v2 models + row/JSON shaping
  static/index.html  # the whole mobile UI: HTML + CSS + vanilla JS, served at GET /
  static/logo.png    # the app icon (180x180): the favicon, and the source the other sizes come from
  static/apple-touch-icon*.png  # 180/152/120 slots iOS probes, opaque white, served publicly
schema.sql         # transactions table, indexes, receipts bucket
tests/             # pytest: dedupe, models, auth, extractor, endpoints, bank screenshots, production, static (167 tests)
.env.example
ctl.sh             # start / stop / status / restart, and whether the listener is stale
design/            # the Stitch screens the UI was rebuilt from (screen.png + code.html + DESIGN.md)
Handoff.md         # handoff notes for the next session
README.md
requirements.txt   # production runtime deps (what the Dockerfile installs)
requirements-dev.txt  # `-r requirements.txt` plus pytest + httpx, for local tests
Dockerfile         # production image: non-root user, no secrets baked in
render.yaml        # Render blueprint: sets PORT=10000 and the health check. No secrets in it
.dockerignore      # keeps .env, .venv, tests and caches out of the build context
.gcloudignore      # UNUSED (old Google Cloud Run setup); Render does not read it, safe to delete
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

## Deploy (Render)

Production runs on **Render** as a free **web service** built from the repo's `Dockerfile`:

- URL: `https://duits-money-tracking.onrender.com`
- Branch `main`, **auto-deploy on every push** to `main` (Render's default for a GitHub-connected service).
  Render does not wait for tests, so a broken push goes live. Run pytest before pushing.
- Health check path: `/health` (no auth).
- Environment variables are set in the Render dashboard, under the service's **Environment** tab. Set
  `ENVIRONMENT=production` there too.
- **The free instance sleeps when idle** (Render's free web services spin down after a period with no traffic;
  check Render's current docs for the exact time and monthly-hours limits). The first request after a sleep is
  slow. The UI shows "Waking up the server…" after 4 seconds. Shortcuts will time out on a cold start, so retry
  once.
- Render terminates TLS and sets `X-Forwarded-For`. Confirm that header's behaviour on Render before relying on
  the per-IP throttle described below.

Deploy steps: create the web service from the GitHub repo, choose **Docker** as the runtime (the `Dockerfile`
is used as-is; nothing is passed as build args), add the variables below, then deploy.

**`PORT` is set by `render.yaml` to `10000`.** The image's start command is
`exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`, so it binds whatever `PORT` says and falls
back to `8000` when the variable is absent (local runs). Keep the `Dockerfile` default at `8000`; the
platform supplies the real value. Verified locally with `PORT=10000`.

The `.gcloudignore` file is **unused**. It came from an earlier Google Cloud Run setup and Render does not
read it. It can be deleted.

One image, no secrets inside it: everything is read from the environment at runtime, and the
process runs as a non-root user (`appuser`, uid 10001). `.dockerignore` keeps `.env`, `.venv`,
`tests/`, caches and `.git` out of the build context.

Environment variables — **names only**. Put the values in Render's environment settings (or any other secret
store); never commit them, never bake them into the image or pass them as build args.

| Variable | Required | Default / notes |
| --- | --- | --- |
| `API_KEY` | yes | only used while `ALLOW_LEGACY_API_KEY` is on: the `X-API-Key` value; generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ALLOW_LEGACY_API_KEY` | no | temporary single-owner fallback, **off by default**. When `true`, `X-API-Key: <API_KEY>` acts as `LEGACY_USER_ID` |
| `LEGACY_USER_ID` | only with the flag | the owner's `auth.users` id (a UUID). The app refuses to start with the flag on and this unset or invalid |
| `SUPABASE_URL` | yes | your project URL |
| `SUPABASE_SERVICE_KEY` | yes | `service_role` key — server-side only, it bypasses RLS. Never sent to the page |
| `SUPABASE_PUBLISHABLE_KEY` | for the web UI | the publishable (anon) key the **browser** signs in with; injected into the page at serve time. Public by design. Empty means the web UI cannot sign in (the API and the Apple Shortcut are unaffected) |
| `ANTHROPIC_API_KEY` | yes | Claude API key |
| `CLAUDE_MODEL` | no | defaults to `claude-sonnet-4-5` |
| `CLAUDE_FALLBACK_MODEL` | no | defaults to `claude-sonnet-5-5`. Check the model ID against Anthropic's docs |
| `RECEIPTS_BUCKET` | no | defaults to `receipts` |
| `MAX_UPLOAD_BYTES` | no | defaults to `10485760` (10 MB) |
| `ENVIRONMENT` | no | set to `production` to switch `/docs`, `/redoc` and `/openapi.json` off |
| `PORT` | no | port uvicorn binds inside the container. `render.yaml` sets it to `10000`; the `Dockerfile` default is `8000` |

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

The platform proxy (Render) must pass the client address in `X-Forwarded-For`; only the first hop of
that header is trusted. Failed
Failed sign-in attempts (bad or missing credentials) are limited to 10 per minute per client IP, then `429` with `Retry-After`;
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
- **Add** (opened by the raised `+`) — the Stitch "New Transaction" sheet, three ways in, all ending in
  the same row on the list. It opens on a **chooser** — *Manual* or *AI* — so nothing is typed before
  the choice is made. A bottom sheet — `position: fixed; left: 0; right: 0; bottom: var(--kb)` with
  `overflow: hidden` — and a flex column whose only flexible slot is the amount itself, so the slack on
  a tall phone collects around the number. Its height is per view: the chooser hugs its two cards,
  Manual and AI take the full sheet, and `max-height` is clamped by `--kb` (the keyboard), so a lifted
  sheet's top still clears `--sheet-top-gap`.
  - Header: `Cancel` / `New Transaction` / **Save** (blue, bold, right). Save stays disabled until the
    amount is greater than zero, and while a request is in flight it is disabled and reads `Saving…`, so
    a double tap cannot post twice.
  - **AI** is the *Smart Entry* card — the sparkle icon and the `Smart Entry` label, then the field and
    a fixed-width `Add` button (10px apart, the field flexing with `min-width: 0`) inside one grey card
    with 14px of padding — with *Scan Receipt* under it. The card is a 44px control, not an expandable
    row: nothing about the sheet opens, closes or reflows when it gets focus, and the keypad is not on
    screen in this view. It posts to `POST /transactions/text`, letting Claude fill whatever it can.
    *Scan Receipt* (camera) is the other row in the AI view: an 80px box with a 20px radius, a 52px tinted
    tile holding a 28px icon, the title at 18px semibold, one muted line under it (`Receipt or bank
    screenshot`) and a grey chevron on the right. The AI sheet is titled `Add with AI`, hugs its content
    rather than filling the screen, and it opens the camera roll/camera
    (`<input type="file" capture>`, no `getUserMedia`, so it works over plain HTTP) and is the only
    thing that reveals the privacy hint, which appears under the row once tapped: the photo is
    downscaled to 1600 px on the long edge and re-encoded as JPEG at quality 0.85 in the browser before
    upload, which keeps uploads small, strips EXIF/GPS and turns HEIC into JPEG.
  - **Manual is one screen**, top to bottom, in the Stitch reference order. A **Back** chevron (44px,
    beside the type control) returns to the chooser, and **Expense / Income** is the segmented control.
    The amount is a bold 56-64px number with a blinking caret and a small `RM` (about 0.38 of the figure)
    on its baseline. Its block takes the sheet's spare height and centres the figure in it, with a 48px
    floor; a long value shrinks to fit its one line (`fitAddAmount()`, so `123456.78` stays on one line
    at 375px). A
    **CATEGORY** label sits above one horizontal row of the nine categories, each with its icon and
    colour; the chosen one fills with the accent, and the last chip is cut at the edge as the scroll
    hint. The four-row card is
    **Merchant**, **Date** (`Today, 19 Oct 2026`, with the native picker invisibly over the row), **Mode**
    (Personal | Business, the rounded toggle described below) and **Note**. Each row is a label, so a
    tap anywhere on it opens its input. The keypad is the sheet's footer.
  - The **keypad** is pinned to the bottom: 3 columns and 4 rows of fixed 58px keys (48px on a short
    sheet, never under the 44px tap floor) with 8px gaps and 28px medium digits. It sizes to its content
    — 4x58 + 3x8 = 256px — and nothing stretches it, so the panel wraps the keys on a tall phone and the
    height it leaves over is shared between the blocks above; the amount keeps its 56-64px figure at
    every size. The panel keeps the card's 16px side inset, so the outer keys line up with the rows above.
    It hides while *Merchant* or *Note* holds the caret, derived from state and never remembered.
  - The whole screen fits at 390×844 and 430×932 (the card sits 20px under the chip row on 844 and 39px
    on 932); nothing in Manual scrolls. A 375×667 box is tight enough to scroll a little. The chosen chip scrolls into
    view with part of the previous chip showing when the
    sheet opens or a chip is picked; with nothing chosen the row starts at 0.
  - **Mode** is the row's compact toggle, right-aligned, in the Expense | Income control's style: a
    rounded pill track on `--control`, 32px tall, whose selected segment paints a `--seg-selected`
    pill with a `--seg-shadow` (14px text, semibold when selected). Each segment's tap box stays 44px:
    it spills over the track symmetrically, and the pill paints behind the label through the button's
    `::after`. It starts on the Home tab's mode.
  - **Note** is the `raw_extraction.note` of the row: the API has no column for it, and the payload's keys
    are the same whether or not a note is typed (`note` is `null` when blank). A row opened from Pay
    carries the commitment's name as the merchant, the amount, the bills category, an expense, and the
    commitment's id as `commitment_id` — that id is what keeps the paid bill out of the Monthly budget
    bar while the balance and the Expenses card keep counting it.
  - **Keyboard.** The sheet lifts for the real keyboard. iOS shrinks only the visual viewport when the
    keyboard opens, so its height — `innerHeight - visualViewport.height - visualViewport.offsetTop` —
    goes into one variable and one CSS variable, `--kb`, which sets each sheet's `bottom` (and every
    overlay's bottom padding) and clamps `max-height`, so the sheet sits just above the keys with its top
    still clear of `--sheet-top-gap`. Focusing a sheet field centres it about 300ms later, once the
    keyboard has settled, by scrolling the sheet's own scroller (Manual's body, or the sheet) — never the
    window, which stays locked. The inset resets when the keyboard closes and when a sheet closes.

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
  stamp (the git short hash, injected by `GET /`, or `dev` locally) plus the status bar style the meta
  ended up with and whether it is running standalone. If the shortcut shows an older stamp it is
  serving a cached document.
  There is no service worker here — the page is the only asset, with its CSS and JS inline.

  Opening `app/static/index.html` from disk shows `{{BUILD}}`; only the served page is filled in.

**Signing in.** The page has an email + password screen (invite only, no sign-up) that talks to Supabase
Auth over its REST endpoints — no SDK, no CDN, no build step. The session (access and refresh tokens) is
kept in `localStorage` under `duits.session`, and every API call sends it as `Authorization: Bearer`. A
`401` triggers one token refresh (serialised, so a burst of 401s costs one refresh request) and, if that
fails, returns to the sign-in screen **without clearing unsaved input in the Add sheet**. Invite and
password-reset links are handled on the page: the token in the link's hash is read once and the address bar
is rewritten immediately, so a token never lingers in a URL. Settings shows an *Account* card (email,
Sign out) instead of the old API key row; sign out clears the session **and** every rendered list. The
publishable key and the project URL are injected into the page by `GET /` at serve time (like `{{BUILD}}`);
the **service key never reaches the page**.

The sign-in screen is one column, centred and sitting at **45%** from the top (the bottom padding is 10vh
taller than the top, which is what shifts a centred block up). It is `min-height: 100dvh` — never `100vh`,
which is what iOS breaks — and scrolls when the keyboard eats the height. The centring is `safe center`,
because a centred flex item taller than its box overflows off the *top*, where the logo and title could
never be scrolled back into view. Focusing a field scrolls it to the middle of what the keyboard leaves
after ~250ms; leaving the form scrolls back to the top so the logo and title return. Fields are 16px with
`maximum-scale=1`, `enterkeyhint` `next`/`go`, and `autocapitalize`/`autocorrect` off. The set-password and
reset views use the same column and the same sizes. The form is taller than the strip a 45% keyboard
leaves on a small phone (456px of content against 300px at 375×667), so it is designed to scroll rather
than to fit in one glance; every control is reachable and lands clear of the keyboard when focused.

**Content-Security-Policy.** `GET /` sends a strict policy with a fresh per-response nonce:
`default-src 'self'`, `script-src 'self' 'nonce-…'` (no `unsafe-inline`, so an injected script cannot run),
`style-src 'self' 'unsafe-inline'`, `img-src 'self' blob: <project>`, `connect-src 'self' <project>`,
`font-src 'self'`, `object-src 'none'`, `base-uri 'none'`, `form-action 'self'`, `frame-ancestors 'none'`.
Two allowances were necessary: `style-src 'unsafe-inline'` for the page's two inline `<style>` blocks and the
twelve `style="…"` attributes its templates write (colour and stagger values, all escaped or from constant
maps), and `blob:` for the in-memory preview built while a photo is downscaled. There are no `data:` URIs.

Add to Home Screen works like an
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
- **Bottom sheets, not pages.** The Add and edit sheets are anchored to the bottom edge with their top
  edge at `--sheet-top-gap`, so Cancel / New Transaction / Save always sit clear of the status bar (see
  *Bottom sheets*). They are deliberately *not* sized from `window.innerHeight`: in a standalone app
  that is not the screen, and pinning them in pixels is what used to push the sheet's head under the
  status bar.
- **When the box is short, the sheet gives height back instead of scrolling.** The insets and the top
  gap are real space (a 375×667 screen has a 592px box), so container queries on
  the sheet's own box step in: the keypad's chrome gives first (grid padding and a tighter 8px gap, with
  48px rows — above the tap floor), then the amount block shrinks to the figure's line box,
  then the gaps. A tall phone trips none of them (844 and
  932 give boxes of 760 and 830) and keeps every size it was tuned with. (That was the old 65% Manual;
  the Stitch layout is the full sheet. See the Add section.)
- **The status bar style is theme-aware, and that is the honest answer.** `black-translucent` is what
  the page ships (it is what lets the page paint under the bar), but iOS gives it **white** glyphs,
  and the light theme's bar is `rgba(249, 249, 249, .85)` — white on near-white is unreadable. So the
  pre-paint script (and the theme switch) keep `black-translucent` for dark and ask for `default`
  (black glyphs) for light: the only two glyph colours iOS offers, chosen by the theme that is already
  decided before the first paint. Full-screen-ness is unaffected, because `viewport-fit=cover` and the
  safe-area padding are what put content under the bar; whatever iOS decides, `env()` reports the truth
  and the layout follows it. The alternative — `black-translucent` in both themes — needs the light
  theme's top strip darkened to a band, which is the colour hack this deliberately avoids.
- The **Build** row in Settings prints the stamp (the git short hash, injected by `GET /`, or `dev`
  locally), the status bar style the meta ended up with and whether it is running standalone, so a
  phone can be asked what it actually loaded.

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

### Bottom sheets

The Add sheet and the edit sheet are native-style bottom sheets, not full-screen pages:

- **One knob for the top edge**: `--sheet-top-gap: max(var(--sat) + 12px, 10dvh)` in `:root`. The sheet
  is `position: fixed; left: 0; right: 0; bottom: 0` with `height: calc(100dvh - var(--sheet-top-gap))`
  — the keypad's background reaches the bottom edge, so there is never a strip of scrim under the keys,
  and its bottom padding is the home-indicator inset. `border-radius: 28px 28px 0 0`, grab handle kept,
  and the header sits 8px under the handle.
- **The edit sheet wears the same clothes** (`#txnOverlay`/`#txnSheet`: same anchor, same gap, same
  28px corners, its own padding-bottom for the home indicator) but keeps a content-sized height capped
  at the gap, and it may scroll internally — a list of corrections is not a keypad. The **month wheel
  keeps its own height and its own scrim**.
- **A tap outside is judged by the target, never by where the tree says it is.** `isOutsideTap(event,
  overlay)` closes the sheet only when `event.target` IS the scrim layer or the overlay itself. The
  obvious-looking `event.target.closest(".sheet")` cannot be used: a sheet's own handlers re-render
  their content (a category chip redraws the chips row; Edit and Delete replace the sheet's body), which
  detaches the node the click's target points at — and a detached node has no ancestors, so the guard
  read "outside" and closed the sheet mid-tap. That is what made a chip tap dismiss the Add sheet and
  what swallowed the edit and delete buttons on the phone.
- **The scrim is a layer, not the overlay**: `<div class="scrim">` as the first child of every
  overlay, painted under the sheet, `--scrim-sheet: rgba(0, 0, 0, .35)` for these two sheets (the modal
  scrim stays deeper darker). It is the only opacity animation in an overlay — which is what keeps the
  sheet and its contents fully opaque while they move. `.overlay .scrim` is 0 when closed and 1 when
  open (the state for the moments when no animation is running, e.g. after a cancelled drag spring),
  and the animations move it between those two. Tapping it dismisses.
- **The page behind eases back**: `.app` scales to 0.96 and shifts down 8px while a bottom sheet is
  open, driven by the Web Animations API in `openOverlay`/`closeOverlay` (`PAGE_BEHIND`), transform
  only. The overlays are siblings of `.app`, so a transform there cannot disturb their fixed
  positioning — the sheet itself never scales with the page. Reduce Motion skips it entirely.
- **The AI view is content height**: it hugs its two boxes and never scrolls, so the shrink order applies
  to Manual only, where the keypad is pinned and the content fits both target phones without scrolling.
- Everything else is unchanged: open/close on the Web Animations API, swipe-down-to-close (still
  measured from the finger, so it behaves the same from the lifted position), the scrim tap, and the
  page behind staying locked while a sheet is open.

### What's new

One bottom sheet, shown once per version, for a user who has just met a big change:

- **A version, not a date.** `WHATS_NEW_VERSION` in `app/static/index.html` is compared with what is
  stored under `localStorage["whatsNew:<user id>:lastSeenVersion"]`. Equal means the user has read
  this version and is never asked again; different means the sheet opens. **To show it again, change
  the constant** — that is the only switch, and it is what a copy change or a new feature uses.
- **The key is per account.** The id in the key is the access token's `sub` claim — the same id the
  API scopes by (`auth.users.id`) — so two accounts on one device have two keys and the first one to
  read the card cannot hide it from the second. A token that cannot be read falls back to a shared
  `anonymous` key: the one case where a second account could still miss the card, and better than
  storing under nobody's id, which would hide it from everyone. No database and no migration.
- **Storage can fail.** Private mode, a full quota, a browser that says no. Both the read and the
  write are wrapped in `try`/`catch`: a failed read means "not seen yet" (the sheet shows), and a
  failed write means it shows again next time. Nothing throws either way.
- **Never on a sign-in screen.** The sheet is opened from the two places the user arrives at Home — a
  fresh sign-in (`afterSignIn`) and a restored session (`restoreSession`) — and only after the splash
  has faded, since the splash covers the app until it does. The sign-in, set-password and reset
  screens never carry it.
- **Three screens, a dot each, and a way out.** The screens live in one list (`WHATS_NEW_SCREENS`), so
  the dots are painted from that same list and the count can never drift. *Skip* is in the header,
  *Next* is the button at the foot, and it reads *Got it* on the last screen. Every way out — the
  button, the scrim and the drag — writes the version, so a user who dismisses it is never asked again.
- **Each screen has a button that opens the thing it describes.** No new screen is built for the card:
  Balance opens the one-field balance sheet, or the card's own *How this is calculated* breakdown when
  a balance is already set; Commitments opens the commitments sheet with the add form ready; Monthly
  budget opens the one-field budget sheet. The card closes before the next sheet opens, the way the app
  stacks one sheet on another.
- **Settings > About has a "What's new" row** that opens the card whenever the user wants it, even
  when the stored version says they have read it. That is the difference between the one-shot nudge
  that appears by itself and a deliberate request; it does not write the version on the way in.
- **The screens are cards, and the copy is two short sentences each.** The sheet is white in the
  light theme, so bare text on it read as floating text; each screen is now the app's own `.card`.
  Every sentence comes from the code that computes the figures (`app/finance.py`) or from what the UI
  does. Screen 1 carries one worked example of the arithmetic and says it is an example; the budget
  screen says what the limit is for and when the bar changes colour, because that is exactly what
  `remaining_budget = budget − (month_expense − month_commitment_expense)` does. A test in
  `tests/test_static.py` holds the copy to the code, so a formula that changes means the copy changes
  with it.

### The (i) on the balance card

A small **i** mark sits beside the *Safe to spend* label on the balance card. It says the card opens
the sheet that spells the figure out — *How this is calculated*.

- It is **decoration inside the card's own button**, so it carries no name of its own (`aria-hidden`)
  and has no handler: the whole balance card is one `<button>` that opens that sheet, and a button
  inside a button is invalid HTML. A second control for the same sheet would also be a tap target the
  app does not otherwise have.
- The circle is filled with `--text-2` and the letter with `--card`, so it reads in both themes; a
  pale letter on a faint circle would vanish on the light card.
- The button's own accessible name already says "How this is calculated", so a screen reader is told
  what the card does without the mark adding a second name to read.

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
  `touch-action: none` so a swipe anywhere on it is a dismiss rather than a pan, with the chips scroller
  handed back its own gesture (`pan-x`). The edit
  sheet still scrolls, so only its head and amounts are locked. Keys are `-webkit-tap-highlight-color`-free and `user-select: none`, while
  inputs keep selection so a typed line stays correctable.
- **No sideways scroll.** `html, body { overflow-x: hidden; max-width: 100vw }`, `box-sizing:
  border-box` throughout, `min-width: 0` on the flexing field. The only things off the right edge are
  the category chips, which live in their own horizontal scroller by design.
- **Keyboard.** A sheet lifts above the keyboard. iOS shrinks only the *visual* viewport when the
  keyboard opens and leaves the layout viewport (and every `dvh`) alone, so the height is read as
  `innerHeight - visualViewport.height - visualViewport.offsetTop`, kept in one variable, and written to
  one CSS variable, `--kb`. That variable sets each sheet's `bottom` (and every overlay's bottom
  padding) and clamps its `max-height`, so the sheet sits just above the keys with its top still clear of
  `--sheet-top-gap`; the page behind stays scroll-locked (`unlockPageScroll()` still runs on close).
  Focusing a sheet field — Merchant, Note, the commitment name/amount/day, the edit form's rows — centres
  it about 300ms later, once the keyboard has settled, by moving the sheet's own `scrollTop`; the window
  is never scrolled. `focus()` is still called with `{ preventScroll: true }` so Safari never pans the
  page to "help", and nothing in the sheet can zoom: every focusable control is at least 16px and the
  viewport meta pins `maximum-scale=1`.

### Swipe to dismiss

The Add sheet and the edit sheet close by swiping down from almost anywhere, because reaching for the
grabber with a thumb is the one gesture a phone should not require. One implementation,
`attachSheetDrag(sheetId, overlayId, onDismiss, handleOnly)`, in `app/static/index.html`:

- **pointerdown / move / up on the sheet**, with `setPointerCapture` so the sheet keeps the gesture
  even when the finger leaves it. A second finger never steals it (`isPrimary`).
- **A drag only starts where nothing else has a gesture.** `DRAG_BLOCKERS` is one selector — buttons,
  links, labels, inputs, selects, textareas, `.key`, `.keypad`, `.chip-scroll`, `.cat-chip`,
  `.add-rows` (Scan Receipt), `.smart-card` (Smart Entry), `.add-pills`, `.add-fields`,
  `.sheet-actions`, the wheel — and `.no-drag` is the escape hatch for anything added later. The
  header, the amount, the grabber and empty space are all fair game.
- **The detail sheet adds its info rows and section headings** (`.kv`, `.card-title`) to the allow list,
  so a swipe works from almost anywhere on it. Its edit mode narrows itself: the form's fields are
  labels/inputs/selects and its rows are `.form-row`, all of them blocked, so only the title, the
  sub-line and empty space can start a drag there — typing and selecting are untouched.
- **A sheet that scrolls keeps its own gesture** until it is back at the top: `openSheet`/`closeSheet`
  reset `#txnSheet.scrollTop`, and the drag refuses to claim while it is above zero, so a downward drag
  from halfway down a long receipt scrolls rather than dismisses.
- **The allowed surfaces also refuse the touch default** (`touchstart` with `passive: false`, only where
  the drag may start), because the browser decides pan-versus-gesture at touch time and `touch-action`
  inside a scroller proved advisory: a swipe that began on a `.kv` row came back as `pointercancel`
  before the drag could claim it. See *Known gaps* for what this still does not fix in Chrome.
- **It can only start on four kinds of surface**, because the allow list is a list and not an
  afterthought: `DRAG_SURFACES = ".sheet-grab, .sheet-head, .add-amount, .sheet-title, .sheet-sub,
  .sheet-amount, .result-merchant, .result-amount, .result-meta, .sheet"` — the handle, the header, the
  amount, the edit sheet's title and amounts, and the sheet's own empty space. A second check then
  removes anything interactive sitting on one of those (the header's buttons, above all) via
  `DRAG_BLOCKERS`: buttons, links, labels, inputs, selects, textareas, `.key`, `.keypad`,
  `.chip-scroll`, `.cat-chip`, `.add-rows`, `.smart-card`, `.add-card`, `.add-type-row`,
  `.sheet-actions`, `.kv`, `.item-row`, `.form-row`, `.receipt-img`, the wheel, and anything marked
  `.no-drag`. An element added later is therefore *not* draggable by default.
- **It is claimed only once it is a downward drag**: more than 8px of movement
  (`DRAG_START_PX`) and more vertical than horizontal (`|dy| > |dx|`). An upward or sideways movement
  does nothing at all, so a tap with a wobble and a scroll never fight the sheet. `setPointerCapture`
  is taken **here**, when the gesture is genuinely ours — never on pointerdown, because capturing then
  makes the sheet the target of the pointerup and moves the synthesised click onto the sheet, away
  from the button that was tapped.
- At that moment the finger takes over: any running open/close animation is **cancelled**
  (`cancelOverlayMotion`), a focused input is **blurred** so the keyboard closes with the drag, the
  sheet follows `translateY(dy)` with no animation (it never fades), and the scrim layer's opacity
  thins with the distance
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

Everything animates **transform and opacity only** (plus SVG `stroke-dasharray` for the ring), and in
an overlay the only element whose opacity moves is the scrim layer (see *Motion*), so no
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
  flight cannot re-close a sheet that has been reopened. The class is only *state* (`visibility:
  hidden; pointer-events: none` when closed, with the sheet resting at `translateY(100%)` — never
  `display: none`), and there is deliberately **no CSS transition on the overlay at all**, which is
  exactly what iOS played once and then ignored.
  **The sheet never fades.** Nothing animates the sheet's opacity: `openOverlay`/`closeOverlay` only
  ever move it, and there is no `opacity` on `.overlay` either — an opacity on an ancestor is a group
  opacity, so fading the overlay faded the sheet inside it and a closing sheet went see-through with
  the page showing through its text. The dim is a `.scrim` layer of its own (one per overlay, painted
  under the sheet) and that is the only thing in an overlay that animates opacity. A downward drag cancels whatever animation is running, hands the transform to the
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
- **The Add sheet only changes layout for the keyboard.** Its views set their own height — the chooser
  hugs its cards, Manual and AI take the full sheet — and the page behind is
  locked while it is open (`html`/`body` `overflow: hidden`, restored on close, `unlockPageScroll()`
  released before anything can throw). The keyboard is the one thing that moves it: `--kb` lifts the
  sheet and clamps its height (see *iOS touch behaviour* above). Everything else is derived from state —
  the keypad is hidden whenever a Manual text field holds the caret, `focusWithoutScroll()` calls
  `focus({ preventScroll: true })`, and no element's position is pinned in pixels at open time.
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
Transactions, Insights (week + month), Settings, the Add sheet (keypad, chips, Smart Entry,
warn/error toast, error card), the edit sheet, the month wheel, empty states and the key dialog: no
light boxes survive in dark and no text falls below 3.6:1 against its real background. The checker is
calibrated — two deliberately invisible samples are flagged every run — so a clean pass means
something.

## API

All of these except `/health` need `Authorization: Bearer <Supabase access token>`. A signed-in user sees only their own rows; another user's id answers `404`. While `ALLOW_LEGACY_API_KEY` is on, the curl examples below also work with `X-API-Key: <API_KEY>`, which acts as `LEGACY_USER_ID`.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/health` | – | `{"status": "ok"}` (no auth) |
| POST | `/transactions/scan` | multipart: `file` (jpg/png/webp), optional `mode` | 201 created transaction |
| POST | `/transactions/text` | JSON `{"text": "...", "mode": "personal"}` | 201 created transaction |
| POST | `/transactions` | JSON: `amount` (required), `txn_date` (default today), `merchant`, `category`, `type`, `mode`, `note`, optional `commitment_id` (the Pay flow's link; must belong to the caller) | 201 created transaction (422 bad value or unknown field, 409 duplicate — a scan of the same receipt, or a Pay whose bill is already charged this month — 404 unknown/foreign `commitment_id`) |
| GET | `/transactions?month=YYYY-MM&mode=personal` | – | 200 list, newest first |
| GET | `/summary?month=YYYY-MM&mode=personal` | – | 200 totals |
| GET | `/transactions/{id}` | – | 200 one transaction (404 unknown, 422 non-UUID id) |
| PATCH | `/transactions/{id}` | JSON, any of `txn_date`, `amount`, `merchant`, `category`, `type`, `mode` | 200 updated transaction (422 bad value or unknown field) |
| DELETE | `/transactions/{id}` | – | 204 empty body — deletes the row **and** its receipt object |
| GET | `/transactions/{id}/receipt-url` | – | 200 `{"url": "https://…", "expires_in": 60}` (404 if the row has no receipt). `url` is absolute and ready to open |


### The Pay flow's guard: one bill, one expense, one month

Paying a commitment is **two writes**: the expense, then the paid mark. The mark was already
idempotent (the same month twice leaves one mark, so a retried tap cannot subtract the money twice),
but the **expense in front of it was not** — and a manual row is never deduped, because a typed
entry is deliberate.

So a Pay whose *mark* failed, retried by the user, charged the same bill **twice**: the balance
dropped by twice the amount and Safe to spend went with it, while the bill was still unpaid.

`POST /transactions` now answers **409 with the row that is already saved** when the payload carries
a `commitment_id` and that commitment already has an expense in the transaction's own month:

- The month is the **transaction's own**, so last month's bill and this month's bill are two
  charges, and neither is a duplicate of the other.
- The lookup filters `user_id` explicitly (`app/db.py`'s `find_pay_expense`). The service key
  bypasses RLS, so the query's own filter — not a policy — is what keeps one owner's rows away from
  another.
- The guard looks at the rows that **exist**, so deleting a mistaken expense frees the bill again.
- A plain save never asks, and is never refused.
- The UI treats a 409 on a Pay as what it is — the expense is there, only the mark is missing — so it
  closes the sheet, carries on to the mark, and says "Already recorded. Marked as paid."

**Known limit:** this is a check, not a constraint. Two Pay requests that arrive *at the same
instant* can both pass the lookup and both insert — there is no unique index on
`(commitment_id, month)`, so a genuine race is still possible. Closing that would need a SQL
migration, which is a separate decision.

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

`amount` is always a JSON number. `source` is `receipt_scan` for a photo of paper, `bank_screenshot`
for a screen of a bank or e-wallet app, `text` for Smart Entry and `manual` for a hand-typed row. To
decide whether a row needs a human look, read `raw_extraction.needs_review` — true when Claude could not
read the amount or the merchant, or (on a screenshot) when it could not tell whether money left or
arrived.


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
  dates, today's date when the date is missing, `null` instead of guessing). **A screenshot of a bank or
  e-wallet screen is read as its own kind of document** (`document_kind = "bank_screenshot"`: Maybank
  MAE/M2U, DuitNow QR, Touch 'n Go, GrabPay "Payment/Transfer Successful" screens): the recipient or
  sender is the merchant, the direction of the money decides expense versus income ("Transfer to",
  "Payment", a minus sign = expense; "Received from", "Credit", a plus sign = income; unclear leaves
  `type` null and flags the row), and it adds the two fields a paper receipt does not have — the
  `reference` number and the `txn_time`. Balances, account numbers and card numbers are never returned in
  any field, and a category that is not obvious from the merchant becomes `other` rather than null. The
  reply is validated with Pydantic, retried once if it is not usable, then rejected with `422`.
- **Bank and e-wallet screenshots.** The scan endpoint takes more than paper: a screenshot of a
  "Payment Successful" / "Transfer Successful" screen (Maybank MAE/M2U, DuitNow QR, Touch 'n Go,
  GrabPay) is read as `document_kind = "bank_screenshot"`, and two rules follow from that.
  - **The image is not kept.** `receipt_path` is `NULL` and nothing is uploaded to the `receipts`
    bucket: a paper receipt is a document worth keeping, a screenshot is a copy of a screen the user
    already has. Only the extracted fields are stored.
  - **No account numbers.** The prompt is told never to return a balance, account number, card number or
    phone number, and `raw_extraction` is passed through a mask before insert anyway: any value that is
    entirely 8+ digits (optionally in groups) is replaced with `[redacted]`. An ISO date or timestamp is
    never mistaken for one, so `txn_date` and `txn_time` survive intact.
  - The phone shows the same success toast as any other save, now naming what was saved —
    `"DuitNow to Ahmad · RM 250"` — and appending `· needs review` when the row is flagged, rather
    than a bare "Receipt saved." that looks identical whether or not a field was readable.
- **Dedupe**: only scans are deduped, and a screenshot prefers its reference number.
  `dedupe_hash` = sha256 of `ref|<reference>` (uppercased, whitespace removed) when a screenshot shows
  one; otherwise `txn_date|amount(2dp)|lowercased merchant`, plus `|<ten-minute window>` for a screenshot
  that printed a time. That last case is why the lookup also probes the windows either side: 14:29 and
  14:33 are four minutes apart but fall in different windows, and the pair still collides. Text notes and
  merchant-less scans store `dedupe_hash = NULL` (Postgres allows many NULLs under a unique index) and
  therefore always insert — two text entries of RM12 on the same day are two different transactions, so
  `/transactions/text` never returns `409`. When a scan is a duplicate the API answers `409` with
  `{"error": "duplicate", "message": "Already recorded.", "transaction": {…}}`. Hand-typed rows through `POST /transactions` behave
  the same way (`source = "manual"`), so two identical manual entries both insert; the `409`
  branch is still wired to the same `_duplicate()` guard the receipt scan uses, so the moment the
  dedupe policy covers another source the endpoint answers `409` with the existing row. When a
  hash is present the API looks it up first and
  returns `409` with the existing row instead of inserting. The unique index is the real
  guarantee: a rare concurrent double-submit would surface as a 500 but can never create a
  duplicate row. A receipt upload that turns out to be a duplicate (or fails to insert) is deleted
  again, so Storage never keeps an orphan.
- **Status codes**: `400` bad file, file type or `month`; `401` missing/wrong key; `409`
  duplicate; `413` over the 10 MB limit (`MAX_UPLOAD_BYTES`); `422` extraction failed; `502`
  Claude or Supabase Storage failure.
- **Upload limit**: 10 MB, enforced by reading at most limit + 1 bytes.

## Known gaps

- **A stale Home Screen app is now ruled out by the header.** There is no service worker and no
  external CSS/JS — the page *is* the asset — and `GET /` sends `Cache-Control: no-store` (verified on
  the running server), so no copy of the document can be served from cache at all. The **Build** row
  in Settings remains the way to check what a phone actually loaded (the git short hash, injected by
  `GET /`, or `dev` locally); if its stamp does not match the deployed commit, the shortcut needs
  deleting and re-adding. The cost is re-downloading a ~150KB page every
  launch, which is the right trade for an app whose only asset is that page.
- **The splash's timing is measured in Chrome, not on a phone.** The probes show the minimum hold,
  the 4s waking line, the 60s backstop (in the harness, with fake timers), the side effects of a
  failing API and that it never returns; what they cannot show is how the 1200ms feels on a cold
  iPhone launch, whether Safari's own launch image (a blank screen before the page paints) makes the
  splash feel late, or whether the logo's first paint is as prompt on a device as it is in a warm
  browser cache. The logo is a 180px PNG served with `max-age=600`, so a truly cold install may show
  the icon a beat after the wordmark.
- **Opaqueness is proven by computed style, not by sampling pixels.** The probes show that nothing in the
  sheet's chain animates opacity and that the closed state does not use it — which is the mechanism
  behind the see-through bug — but a real pixel sample (a screen recording on the phone) is the only way
  to see the rendered result, e.g. whether a subpixel seam shows at the sheet's rounded corners while it
  moves over the scaled page.
- **The page-behind scale is untested on hardware.** Scaling `.app` also scales the two frosted bars
  (`backdrop-filter: blur(20px)`), which is the one thing on this page that a scaled compositing layer
  can make janky on a phone. It is one line (`PAGE_BEHIND`) to drop if it stutters.
- **A swipe that starts on a `.kv` row still does not dismiss in Chrome.** The surfaces are
  `touch-action: none` and the touch default is refused, and the computed style confirms it, but a
  gesture beginning there comes back as `pointercancel` before the drag can claim it — the title, the big
  amount and the Add sheet's own surfaces are unaffected and work. Since a `.kv` row sits where the
  "empty space" swipe would land, that pair of surfaces is the open question: the remaining candidates
  are a Chrome quirk about `touch-action` inside an `overflow: auto` ancestor, or iOS behaving differently
  again. Everything else the brief asked for is verified by real touch.
- **Real touch is emulated, not a finger.** The CDP touch probe runs Chrome's own pointer/click
  pipeline, which is what caught the detached-target bug, but it is still not iOS: WebKit's capture
  semantics, its 300ms-ish tap heuristics, its scroll arbitration on the chips row and its text-selection
  behaviour on a quick tap are all unverified until the two symptom taps are repeated on the phone.
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
- **The Add sheet is measured at two sizes only, and not on an SE-class screen.** At 390×844 (a 759.59px
  sheet) the whole Manual screen fits with no body scroll; at 375×667 (600.3px) its middle scrolls by about
  133px and the keypad stays pinned. A 320×568-class screen was not measured. See `NEXT_STEPS.md`.
- **Home's ring has three cosmetic ceilings**: a slice under ~2% draws as the minimum round dot; the
  legend folds the tail into a grey `Others`, so a month holding both a real `other` category and a
  grouped tail shows `Other` *and* `Others`; and a 6-figure month total fills the hole.

## Tests

```bash
pip install -r requirements-dev.txt   # requirements.txt alone is production-only (no pytest, no httpx)
pytest
```

167 tests, no network and no API key needed — Claude is monkeypatched at `extractor._call` and
the Supabase helpers at `app.db.*`: dedupe policy (receipts with a merchant dedupe; text notes
and merchant-less receipts do not, and two text entries of the same amount on the same day both
insert), hand-typed rows (`source = "manual"`, note kept in `raw_extraction.note`, empty category
stored as null, defaults for a bare amount, and the `409` guard), month bounds, model
validation/defaults/JSON shape, the auth dependency, and
extraction parsing/retry plus the image payload, and the app icon (four public URLs with the right
`Cache-Control`, absent from the schema, versioned in the page, and each file an alpha-free PNG at
the square size its slot expects).

### UI checks

**Historical, not reproducible from the repo.** The pytest suite covers the API, and `tests/test_static.py`
pins strings in the page. No automated test runs the page's behaviour. The UI results below were measured in
earlier sessions with scratch scripts in `/tmp`, which are gone. The plan for real UI tests is in
`Handoff.md` §7.

The earlier scratch Node harness evaluated the page's `<script>` and asserted 755 things about the
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

Opacity is checked frame by frame too (`/tmp/cdp-js-opaque.js`), because "the sheet must never be
translucent" is not something a screenshot-free probe can see directly — so it measures the property
that causes it, at every level. With a close sampled just after the tap and at +100/+200/+300ms: the
sheet's **whole ancestor chain** (the overlay included) reports `opacity=1`, every visible descendant
reports `opacity=1` (74 of them; `.add-date-input` is the one deliberately transparent element, excluded
by design), the sheet's own background stays `rgb(28, 28, 30)`, and its transform walks
`0 → 69.7 → 526.7 → 587.5 → 600.3px` while the scrim alone fades `1 → 0.884 → 0.123 → 0.021 → 0`. The
closed state is `visibility=hidden`, `pointer-events=none`, `translateY(600.297px)`, `scrim=0`, with no
opacity anywhere. The same script drags the sheet 160px (sheet and descendants opaque, scrim at 0.796),
runs ten open/close cycles sampling five times each and counts **zero** translucent frames, and reports
the page behind during the close as `appOpacity=1`, `barOpacity=1`, a static
`backdrop-filter: blur(20px)` (its `transition-property` is the CSS default `all` at a 0s duration, and
neither bar has a running animation). Under `--reduced-motion` the sheet never moves and never fades.

The bottom sheets are measured the same way, with the insets simulated, at 375×667, 390×844 and
430×932: the sheet's top edge equals `max(sat + 12px, 10dvh)` (67px at all three), its bottom equals
the viewport height, its height is the difference, the radius is `28px 0`, the scrim is
`rgba(0, 0, 0, 0.35)`, the page behind reads `matrix(0.96, 0, 0, 0.96, 0, 8)`, the header's Cancel
button starts below the status bar and 7px under the handle, the keypad's bottom is the viewport's
bottom (`distanceToVh=0`), nothing reachable is clipped (`clipped=[]`), neither the sheet nor the
content column scrolls, and the only overflow is horizontal zero. The reported shrink steps are the
brief's three — `amount 44px, keys 44px, tighter gaps` — on 375×667 and `none` on 390×844 and 430×932
(where the amount is 56px and the keys are 56px). The scrim tap closes the sheet, a drag from the
amount still closes it with `translateY(180px)` mid-flight (and the page stays scaled until it is
gone), the keypad still types, and the edit sheet reports the same anchor, radius and `54px`
bottom padding (20 + the home-indicator inset) while the month wheel keeps its own 333px height and
its own scrim. Under `--reduced-motion` the geometry is identical and `pageBehind=none`.

The two improvements in this round were checked the same two ways. Geometry, at 375×667, 390×844 and
430×932 with the insets simulated: the Add sheet fits with `clipped=[]`, `sheetScrolls=false`,
`columnScrolls=false`, `overflowX=0`, its keypad's bottom is the viewport's bottom, and the shrink steps
are `amount 44px, keys 44px, tighter gaps` at 375×667 and `none` at 390×844 and 430×932 (where the
amount is 56px and the keys are 56px). Real touch at 375×667: a swipe from the detail
sheet's title and from its big amount both close it; swipes from Edit, Delete and Close leave it open; a
swipe from a focused Amount field leaves it open *and* focused with its value intact (`12.5`); the
header Save is disabled with no amount and enabled after a key, and
three taps in a row on it produce exactly **one** `POST /transactions` (the button is disabled and
relabelled in the same tick); ten Add cycles plus ten detail-sheet cycles leave every overlay closed with
`aria-hidden="true"`, `pointer-events: none`, a `visibility: hidden` computed style, and a tap at the
centre of the screen landing on the list behind it rather than on the overlay.

Taps are also driven as **real touch** (`/tmp/cdp-touch.py`: CDP `Input.dispatchTouchEvent` with
`Emulation.setTouchEmulationEnabled`, so the browser runs its own pointer -> click pipeline, capture and
target resolution), because synthetic `element.click()` bypasses exactly the layer where a tap bug
lives. That is what found the regression behind the two phone symptoms: tapping a category chip redraws
the chips row, detaching the node the click's target points at, and the overlay's outside-tap guard —
written as `event.target.closest(".sheet")` — then read that detached node as "outside" and closed the
sheet. The same mechanism meant Edit and Delete replaced the sheet's body, detached themselves, and had
the sheet shut before the next step could run. The probe now reports, at 375×667 and 390×844: ten chip
taps -> `selections=10 closes=0`; a chip tap after scrolling the row (`scrollLeft=120`) still selects,
sheet open; a 6px drift on a keypad key -> no close, the key registers; a 160px swipe from the amount
closes, from the chips row does not; Edit opens the form, Save sends a `PATCH /transactions/<id>` and
closes, Delete asks first (`confirmDeleteBtn` appears) then sends the `DELETE`, `toast: Deleted.`, and
the Transactions tab re-renders with the row gone; ten Add cycles and ten edit cycles leave
"all overlays hidden+inert".

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
its last row clears `--sab`, that the month wheel sits between them, and that nothing reachable is
clipped or scrolled. The bottom-sheet probe (below) does the same for the sheet's new geometry.
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
are kept for static checks only. That harness is not in the repo and no longer exists on disk; moving UI tests
into the repo is `Handoff.md` §7.
