# AGENTS.md — rules for AI agents working on Duits

## 1. What the app is

Duits is a personal expense tracker. It is a **FastAPI** backend that stores transactions in
**Supabase** (Postgres + private Storage bucket `receipts`) and uses **Claude vision** (Anthropic API)
to read receipt photos, bank/e-wallet screenshots and typed notes. Inputs come from Apple Shortcuts
and from the web UI.

- The UI is **one file**, `app/static/index.html` (HTML + CSS + vanilla JS, no build step), served
  publicly at `GET /` with `Cache-Control: no-store`. There is no service worker and no other frontend asset.
- Deployed on **Render**, with auto-deploy from GitHub `main`.
- Read `README.md` for the API and setup, and `Handoff.md` for the latest session's state.
  `Handoff.md` is partly outdated; see its notes before trusting a section.

## 2. Hard rules

1. **Never commit `.env` or any key.** `.env` is gitignored and must stay that way. Do not print,
   paste, log or copy values from `.env`, `ANTHROPIC_API_KEY`, `SUPABASE_SERVICE_KEY` or `API_KEY`
   into code, docs, tests, commit messages or chat. Only variable **names** may appear in docs.
2. **No backend, API or database change unless the task explicitly asks for it.** That covers
   `app/*.py`, `schema.sql`, routes, response shapes, status codes, and Supabase tables, buckets and
   policies. If you think one is needed, stop and ask. Do not "fix it while you're there".
3. **Real data only. No dummy values.** Do not seed, hard-code or ship placeholder amounts, merchants,
   dates or account data in app code, the UI or the database. Test doubles for Claude and Supabase are
   fine inside `tests/`, but they must not leak into the app or the deployed data.

## 3. Process rules

1. **Find the real root cause before changing anything.** Reproduce it, read the code path and check
   the evidence. Do not guess, and do not patch symptoms. If the cause is not known, say so.
2. **Say clearly what could NOT be verified on a real iPhone.** Desktop Chrome, emulated touch and
   faked `visualViewport` are not an iPhone. Always list what remains unproven (see §4).
3. **Before reporting, run pytest and the test harness.**
   - `./.venv/bin/python -m pytest -q` — the full suite must pass; read the count from the summary it
     prints, never from a number written in a doc (this one included — numbers here rot).
   - The UI test harness is **not in the repo**. The `/tmp` scripts that `Handoff.md` cites
     (`duits-ui-check.js`, the `cdp-*` probes) no longer exist. If you cannot run a UI check, say so
     explicitly. Never claim UI results you did not measure in this session.
4. **List every changed file** in your report, with a one-line reason each.
5. Keep changes consistent with the surrounding code's structure, naming and comment density.
   Keep the docs (`README.md`, `Handoff.md`) in step with the behaviour you change.

## 4. Known iOS Safari traps (learned the hard way, from `Handoff.md`)

- **CSS transitions and animations on `display` changes play once on iOS.** Animate with the **Web
  Animations API** (`element.animate()`), and restart a CSS animation with `replay(el, className)`
  (remove class, force reflow, re-add). Sheets use `openOverlay`/`closeOverlay` with a close token and a
  500ms fallback timer.
- **`:active` does nothing on a `<button>` unless the document has a touch listener.** `wire()` adds one
  empty passive `touchstart`. Keep it.
- **Tap guards must be target-based.** Use `isOutsideTap(event, overlay)`, which checks whether
  `event.target` *is* the scrim or the overlay. Never use `event.target.closest(".sheet")`: a handler
  that re-renders its content detaches the tapped node, and `closest()` on a detached node returns null,
  so the sheet closes mid-tap.
- **`setPointerCapture` only once the drag is real** (more than 8px, and more vertical than horizontal,
  `|dy| > |dx|`). Capturing on `pointerdown` moves the synthesised click away from the tapped button.
- **The sheet is never translucent.** Do not put `opacity` on `.overlay`, `.sheet` or any ancestor that
  animates. The dim is its own `.scrim` layer, and only that layer animates opacity. Animate
  `transform` on the sheet only.
- **Fixed sheet height, no keyboard resize.** The Add sheet is `position: fixed` with a height from
  `--sheet-top-gap`, not `window.innerHeight`. Do not add `visualViewport`, `--vvh` or scroll-into-view
  logic. Call `focus({ preventScroll: true })`.
- **Viewport font-size 16px.** Every control a finger can focus (inputs, the date input, search) must
  be at least 16px, or iOS zooms the page on focus. `maximum-scale=1` is a belt, not the fix.
- **`touch-action: manipulation`** on `html`, `body`, `button` and the date label stops double-tap zoom.
  Swipe-to-dismiss surfaces use `touch-action: none`, with `pan-x`/`pan-y` handed back to scrollers.
- Safe-area insets come only from the `--sat/--sab/--sal/--sar` variables. Nothing else calls `env()`.

## 5. Running the tests and the local server

Setup (once):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env    # then fill in real values locally; never commit it
```

Tests (no network, no API key needed; Claude and Supabase are monkeypatched):

```bash
./.venv/bin/python -m pytest -q
```

Local server:

```bash
uvicorn app.main:app --reload                       # Mac only: http://127.0.0.1:8000/
uvicorn app.main:app --reload --host 0.0.0.0        # phone on the same Wi-Fi: http://<mac-LAN-ip>:8000/
./ctl.sh start | stop | restart | status | logs     # background server, logs in /tmp/duits-8000.log
```

`ctl.sh` runs uvicorn **without** `--reload`. `./ctl.sh status` warns when a file under `app/` is newer
than the process. After any change to `app/`, run `./ctl.sh restart`. A stale process answers `405` for
new routes, which looks like a bug in the UI.

**The Build row (Settings → About → Build) is the deployed-version check.** It prints a stamp from
`index.html`, the status-bar style the page ended up with, and whether the page runs standalone. The
stamp is filled in by the server (see the note below).

**The Build stamp is automatic. Do not edit it by hand.** `GET /` replaces the `{{BUILD}}` placeholder in
`index.html` with the short commit SHA from Render's `RENDER_GIT_COMMIT` variable, or `dev` when that
variable is absent (local runs). Keep the placeholder in both spots (the `buildValue` span and `var BUILD`).
A full 40-character SHA is required, so nothing else gets written into the page.
If the Build row on the phone shows an older stamp, the Home Screen app is serving an old copy. Delete
the shortcut and add it again.

## 6. Reporting

End every task with:

- what you changed, and the changed files;
- the exact test results you actually got;
- what you could **not** verify, especially on a real iPhone;
- anything in the repo or the docs that looks outdated or wrong.
