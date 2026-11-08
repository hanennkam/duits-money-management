# Handoff — Duits

**A short snapshot, re-verified on 2026-10-20.** The session-by-session history is `NEXT_STEPS.md`,
which is authoritative where the two disagree; older logs are in `docs/handoff-archive.md`. Rules for
agents are in `AGENTS.md` (its §4 is the canonical list of iOS Safari traps).

## 1. Deployed state

- **Live:** `https://duits-money-tracking.onrender.com` — Render free web service, Docker, auto-deploy
  from GitHub `main`.
- **Last verified deployed commit: `434cfd0`**, read from the live Build row on 2026-10-20. It carries
  the Supabase-auth multi-user work, budget/balance/commitments, and `GET`+`HEAD /health`.
- **The free instance sleeps when idle.** The page's splash shows "Waking up the server…" after 4s; a
  cold start can exceed that. No keep-alive configuration lives in this repo.
- **Supabase live is migrated through `0004`** (§4) and **sign-up is disabled**.
- Read-only audit on 2026-10-20: 108 transactions, 19 receipt objects in 11 folders, bucket `receipts`
  private, one ES256 signing key. (Counts rot; re-run `scripts/audit_live.py`.)

## 2. Architecture

```
app/main.py            routes, exception mapping, security headers, icons, Build stamp
app/auth.py            Supabase JWT verification (ES256 via JWKS), per-IP throttle on failures
app/config.py          settings from env only; fails fast naming missing NAMEs, never values
app/db.py              Supabase client; every helper takes user_id and filters by it
app/extractor.py       Claude calls: image or text -> Extraction (tool use, validated, one retry)
app/models.py          Pydantic models; Extraction.to_row(); account-number masking
app/static/index.html  the whole UI (HTML + CSS + vanilla JS, ~5.9k lines), served at GET /
app/static/*.png       logo + apple-touch icons (public, cacheable for 600s)
schema.sql             the pre-0002 base schema; later changes live in migrations/
migrations/            0002 multi-user, 0003 budget/commitments, 0004 commitment link (+ .down.sql)
Dockerfile             python:3.11-slim, non-root uid 10001, binds ${PORT:-8000}
render.yaml            Render blueprint: Docker, free plan, healthCheckPath /health, PORT=10000
ctl.sh                 local start/stop/restart/status/logs (no --reload, warns on a stale process)
tests/                 pytest: auth, dedupe, models, extractor, endpoints, finance, isolation, static
scripts/               live audit, receipt backup/migration, staging seed and runner
```

## 3. Auth and API

Every API request except `/health` needs `Authorization: Bearer <Supabase access token>`; the page at
`GET /` and the icons are public. The user id comes only from the JWT's `sub` claim (verified against
the project's JWKS, audience `authenticated`, issuer `<project>/auth/v1`). A legacy `X-API-Key` is
accepted only while `ALLOW_LEGACY_API_KEY` is on, and then acts as `LEGACY_USER_ID`.

| Method | Path |
| --- | --- |
| GET, HEAD | `/health` — `{"status": "ok"}`, no auth, no database, `Cache-Control: no-store` |
| GET | `/` and the icon routes (public) |
| POST | `/transactions/scan`, `/transactions/text`, `/transactions` |
| GET | `/transactions?month=YYYY-MM&mode=...`, `/transactions/{id}` |
| PATCH, DELETE | `/transactions/{id}` |
| GET | `/transactions/{id}/receipt-url` |
| GET | `/summary?month=YYYY-MM&mode=...` |
| GET, PUT | `/finance/settings` |
| GET | `/finance/summary?month=YYYY-MM&mode=...` |
| GET, POST | `/commitments?month=YYYY-MM` |
| PATCH, DELETE | `/commitments/{id}` |
| POST, DELETE | `/commitments/{id}/paid` |

`/health`, `/transactions*`, `/summary`, `/finance*` and `/commitments*` are `no-store` via one
middleware list (`NO_STORE_PREFIXES` in `main.py`). Every response gets `nosniff` and
`Referrer-Policy: no-referrer`.

## 4. Database state (live)

| Migration | What it adds | Live |
| --- | --- | --- |
| `0002_multi_user` | `transactions.user_id`, per-owner dedupe constraints and indexes | Applied (owner-verified 2026-10-17) |
| `0003_budget_commitments` | `user_finance_settings`, `monthly_commitments`, `commitment_payments`, `transaction_totals` view | Applied (owner-reported 2026-10-19) |
| `0004_commitment_link` | `transactions.commitment_id` and the view's wider `commitment_expense` column | Applied — the live schema was read on 2026-10-20 and `commitment_expense` is the view's last column (the fixed order) |

`0005` is **not written**: a unique partial index on `(commitment_id, month)` would close the Pay
race, but the API does not translate the resulting `23505` into the `409` the UI expects. That is an
owner decision, recorded in `NEXT_STEPS.md`.

Rollback files sit beside each `up.sql`. Receipt paths are `user_id/YYYY/MM/<uuid>.ext`;
`scripts/migrate_receipts.py` re-homes a legacy path. Live receipt backups and the audit queries are
in `scripts/`.

## 5. UI

One file, no build step, no service worker. Screens: sign-in / set-password / reset, then Home,
Transactions, Add, Insights, Settings. Theme is System/Light/Dark stored in `localStorage`.

- **Add** opens a Manual/AI chooser. Manual is one Stitch-style screen (amount block, category chips,
  merchant/date/note card, keypad footer). AI is Smart Entry text or Scan Receipt; the browser
  downscales to 1600px and re-encodes JPEG before upload.
- **Home** opens on the brand hero: a cobalt gradient panel (`--brand-grad-*`) carrying the nav bar, the
  balance label, the month pill (right-aligned in the same row), the 40px amount and the safe-to-spend
  panel — Home has no Personal/Business toggle. Only the safe panel is glass; the refresh button is a
  borderless translucent disc and the month pill is a small translucent chip. `.hero` plus
  `html[data-screen="home"]` scope the paint, so the other screens keep the plain light chrome. Below
  the hero: Income/Expenses, the budget bar/prompt, the recent list, and a What's New sheet shown once
  per version per account.
- **Personal-only.** No screen has a Personal/Business toggle, the Add sheet has no Mode row, and the
  detail/edit sheets do not show the field. Every request sends `mode=personal`; `/finance/summary`
  totals personal rows only, so stored `business` rows (kept in the database, readable through the
  API) do not move the balance or safe-to-spend.
- **Top bar / status bar.** `apple-mobile-web-app-status-bar-style` is fixed at `black-translucent` and
  never switched (iOS reads it once at launch, so a per-theme switch left a light launch with an opaque
  strip). White glyphs therefore need a dark strip: in light theme the nav bar is the brand gradient on
  every screen, transparent over the hero on Home, and a fixed `body::before` of height `--sat` paints
  the inset even after the bar scrolls; dark keeps the dark bar/hero. The splash and auth screens paint
  the same band. `theme-color` follows (light: the brand top; dark: brand on Home, `--browser-chrome`
  elsewhere).
- **Sign-up (flag off).** `SIGNUP_ENABLED=true` serves the Create-account screen and link; false (the
  default) strips both from the page and keeps the invite-only copy. The flag is read by `GET /`, which
  also strips the `<!-- SIGNUP:START -->…<!-- SIGNUP:END -->` block when off. Sign-up posts to Supabase
  `/auth/v1/signup`; confirmation links (`type=signup` in the hash) are read once, the URL is wiped, and
  the user is signed in (or sent to Sign in if the link carried no tokens). The password fields gained
  Show/Hide controls in the same pass.
- **Pay** a commitment writes the expense and then the paid mark; a retried Pay answers 409 with the
  existing row instead of charging twice.
- **Settings** — grouped inset rows, headers + cards only: Budget & Finance (Opening balance, Monthly
  budget and Commitments open full sub-pages with Back + Save; Currency is read-only), Appearance
  (theme, inline), Account (email, Sign out — with a confirm), About (Version, What's new, Date format).
  Sub-pages hide the tab bar/FAB and sit below every overlay, so Pay's Add sheet still stacks on top.
  The "Add to Home Screen" line is on the sign-in screen and only when not standalone.
- **Version row** (Settings → About) always shows the repo's `VERSION` file. In development only, five
  quick taps on the row (or `?debug=1`) reveal the debug string (short SHA, status-bar style,
  standalone); production sets `APP_DEBUG=false` and never shows it.

## 6. Verification

- `./.venv/bin/python -m pytest -q` → **363 passed, 21 skipped** (measured 2026-11-07). Read the number
  from the run, never from this file.
- **GitHub Actions:** `.github/workflows/test.yml` runs `pytest -q` on every push and pull request
  (Python 3.11, fake env values, no secrets). The suite was checked in a copy with **no `.env`** and an
  unresolvable `SUPABASE_URL`, so it is hermetic. **The workflow itself has not run on GitHub yet.**
- **No automated UI test exists in the repo.** `tests/test_static.py` pins strings and ordering in the
  page; it does not drive the page.
- **Not verified on a real iPhone:** the newest motion batches, the centred popup, the money fade and
  ring, the keyboard/`--kb` path, safe areas, the edge-to-edge status strip in standalone
  (`black-translucent`, the fixed `--sat` band, white glyphs), the Home hero's underlap and glass
  blur, the hero's pill + segmented row on a 320px phone, the real Reduce Motion switch, and a full
  Pay flow.
- Real Claude output on real receipts/screenshots is not verified in CI; it needs a real key and images,
  kept out of the repo.

## 7. Known gaps and next steps

1. **Render still auto-deploys without waiting for tests.** CI now reports, but it does not gate a
   deploy; branch protection or Render's checks would be needed.
2. **Automated UI tests** are not implemented. A proposal exists (Python Playwright under `tests/`,
   Chromium + WebKit, the app served by `uvicorn`, `page.route()` stubs) but was never written.
3. **iPhone pass** on the live URL, including the Build row matching the deployed commit.
4. **Insights Year** needs a `?from=&to=` API endpoint first.
5. **`0005`** (Pay race) and custom categories remain product decisions.

## 8. Ops and configuration

- **Render:** `render.yaml` is the blueprint (Docker, free plan, `healthCheckPath: /health`,
  `PORT=10000`, auto-deploy on). Secrets are **not** in it; they are set in the Render dashboard. Env
  var names: `API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_PUBLISHABLE_KEY`,
  `ANTHROPIC_API_KEY`, optional `ALLOW_LEGACY_API_KEY`, `LEGACY_USER_ID`, `CLAUDE_MODEL`,
  `CLAUDE_FALLBACK_MODEL`, `RECEIPTS_BUCKET`, `MAX_UPLOAD_BYTES`, `ENVIRONMENT`.
- **Keep-alive:** a monitor can poll `HEAD /health`; it is public, touches no database, and is never
  cached. On the free plan this keeps the instance from idling into a cold start.
- **Staging** is a separate Supabase project driven by `scripts/serve_staging.py` and
  `scripts/run_staging_tests.py`; the rehearsal runbook is `docs/migration-runbook.md`.

## 9. Where the history lives

- `NEXT_STEPS.md` — every pass, decision and measured result, newest last. Authoritative.
- `docs/handoff-archive.md` — older session logs, including features since removed.
- `docs/migration-runbook.md` — the live/staging migration and rollback steps.
- `docs/multi-user-audit.md`, `docs/multi-user-step2.md`, `docs/CUTOVER_RUNBOOK.md` — the multi-user
  work and cutover.
