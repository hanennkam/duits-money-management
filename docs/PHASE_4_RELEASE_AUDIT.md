# Phase 4 — release-readiness audit

**Audit date:** 2026-11-08  
**Branch:** `feature/public-onboarding`  
**Status:** static code/documentation audit completed; release gates remain **blocked / unverified**.

This is a read-only audit of the branch source plus a documentation-only record. No production or staging requests were made. No Supabase dashboard settings, database, Storage objects, Render service, or deployment were changed.

## Executive result

The code-level ownership design is coherent on the API path: the caller identity is derived from a verified Supabase JWT; database helpers require an explicit `user_id`; owner-scoped reads and mutations apply that filter; inserts assign the owner in the server; and receipt paths are constrained to the owner's folder before Storage access.

That is **not equivalent to proving tenant isolation in a live Supabase project**. The service-role client bypasses RLS, so the Python ownership filters are the primary API boundary. Two-account tests against staging and a review of the actual deployed schema/policies are still required before public registration can be enabled.

## Findings

### 1. Authentication boundary — code review: pass, live verification: pending

- `app/auth.py` accepts Supabase Bearer tokens and verifies ES256, issuer, audience, required claims and UUID-shaped `sub`.
- The authenticated user id comes from the token's `sub`, not request body/query/path data.
- Missing/invalid credentials are rejected; failed attempts are throttled per process/IP.
- The legacy API-key path is conditional on `ALLOW_LEGACY_API_KEY`; confirm it is disabled for the public multi-user launch.
- The browser registration flow calls Supabase Auth directly. This branch does not add a FastAPI registration endpoint and does not expose the service-role key.

### 2. Tenant isolation — static API-path review: pass, staging proof: pending

Reviewed `app/db.py` and the relevant routes in `app/main.py`:

- Transactions: reads, dedupe lookups, updates and deletes are owner-filtered. Inserts set `user_id` server-side.
- Finance settings: reads are owner-filtered; upsert rejects a caller-supplied `user_id` and sets the authenticated owner.
- Commitments: reads/updates/deletes are owner-filtered; inserts set the authenticated owner.
- Commitment payments: list/delete are owner-filtered; the API checks commitment ownership before marking paid. The composite ownership relationship is expected to be enforced by the database migration.
- Totals: the API filters the aggregate view by owner.
- Receipts: generated paths start with the authenticated user's UUID; signed URL, upload and delete helpers enforce that prefix. A foreign/legacy path is not handed to Storage.

**Important limitation:** this is a source review, not a two-user adversarial test. Because the API uses the service-role key, a missing filter in any future helper would bypass RLS. Keep the required keyword-only `user_id` contract and add integration tests around every data family.

### 3. Database and Storage policies — migration source reviewed, deployed state unverified

- `migrations/0002_multi_user.up.sql` defines owner policies for transactions and receipt objects, and keeps the receipts bucket private.
- The same migration explicitly notes that the API uses the service key and therefore does not rely on RLS for its own queries.
- The migration also describes the owner-folder layout for receipt objects.
- Current project state cannot be inferred safely from migration source. Verify the actual staging and production schema, policies, bucket privacy and applied migration versions in their respective Supabase dashboards/SQL read-only checks.

### 4. Public signup configuration — release blocker until verified

- Frontend sign-up and confirmation handling are implemented in this branch.
- The existing operational runbooks describe live sign-up as closed at the time they were written. They are historical records, not proof of today's dashboard state.
- Before launch, verify **staging** email sign-up is enabled, email confirmation is required, the confirmation redirect allow-list includes the exact staging callback, and the email template returns to the correct app URL.
- Keep **production** sign-up closed until all staging gates pass and the owner explicitly approves the live setting change.
- Confirm the production Auth URL allow-list and email template separately before launch; do not assume staging configuration carries over.

### 6. Automated coverage — static regression tests added; execution pending

- Added seven focused checks to `tests/test_static.py` for the signup view, validation and metadata payload, confirmation callback, resend, optional save/skip, incomplete-onboarding resume and recovery/invite preservation.
- Added `tests/staging/test_two_user_isolation.py`, which signs in two dedicated staging accounts and exercises real API/JWKS/database isolation for finance settings, transactions and commitments, including cross-owner read/update/delete and payment attempts. It cleans up the records it creates and restores user A's finance settings.
- The staging test does not yet exercise the browser email-confirmation journey or receipt Storage object access. Those remain manual/follow-up release gates.
- The local full suite passed on the branch before this staging-only test was added; the staging test has not been executed.

### 7. Staging test runner — guarded integration test added; execution pending

- `scripts/run_staging_tests.py` invokes pytest on `tests/staging` with the `staging` marker, loads `.env.staging`, validates the required app/auth/test-account variables, and refuses any project other than the hard-coded staging project ref.
- `tests/staging/test_two_user_isolation.py` now performs a real two-account staging check for finance settings, transactions and commitments. It uses the two dedicated accounts configured in `.env.staging` and removes only records created by the test.
- The staging test has not been run yet. Do not run ordinary `pytest` to invoke it; use only `./.venv/bin/python scripts/run_staging_tests.py` after confirming the staging-only variables are present in `.env.staging`.
- The runner is deliberately hard-coded to refuse the live project. Do not weaken that guard.

### 5. Onboarding settings write — contract reviewed, end-to-end proof pending

- Optional onboarding reuses `PUT /finance/settings` for `opening_balance` and `monthly_budget`.
- Blank values are omitted; Skip records onboarding completion without submitting either financial value.
- The endpoint is owner-scoped through `CurrentUser` and the finance-settings DB helper.
- Verify on staging that a new account can save each field, skip both, sign out/in and resume incomplete onboarding, and cannot see another test account's values.

## Required release test matrix

| Area | Required proof | Current status |
| --- | --- | --- |
| Onboarding static coverage | Seven source-contract checks added to `tests/test_static.py` | Added; not executed |\n| Python suite | Run `./.venv/bin/python -m pytest -q` on the exact branch head | Not run in this audit environment |
| Staging runner | Run the guarded two-account suite from `.env.staging` only | Test added; not yet executed |\n| UI harness | Run the repo's documented UI harness if present; otherwise record unavailable | Not run; harness is documented as external/not in repo |
| Signup | New email → confirmation email → callback → first session | Not run against staging |
| Resend / duplicate | Neutral response, resend, duplicate and rate-limit behaviour | Not run against staging |
| Recovery | Existing password recovery and set-password links still work | Not run against staging |
| Existing users | Existing sign-in and existing sessions still reach the dashboard | Not run against staging |
| Two-account isolation | Two real test users; cross-read/update/delete attempts across transactions, settings, commitments, payments and receipts | Not run against staging |
| Receipt privacy | Private bucket; signed URL works for owner and fails for the other account; expiry behaves correctly | Not run against staging |
| Regression | Manual transaction, text AI entry, receipt scan, insights, budget and commitment Pay flow | Not run against staging |
| Mobile | Real iPhone Safari and Home Screen standalone; keyboard, safe areas, touch, reduced motion | Not tested on a real iPhone |
| Deployment | Confirm exact branch SHA and environment config before release | Not applicable; no deployment made |

## Release blockers / owner actions

1. Dedicated staging accounts have been confirmed by the owner; add their credentials only to local `.env.staging`, never to chat or Git.
2. Confirm staging schema has every migration required by the current app, including finance settings and commitment/payment tables. The checked-in runbooks contain historical notes and must not be treated as proof of current staging state.
3. The full local pytest suite passed (367 passed, 21 skipped) on the previous branch head. Re-run it after pulling the latest commits so the exact current branch head is covered.
4. Run `./.venv/bin/python scripts/run_staging_tests.py` only after adding the dedicated account credentials to `.env.staging`. Then complete the remaining receipt Storage and browser email-confirmation checks.
5. Test the whole onboarding and recovery journey on desktop and a physical iPhone.
6. Review and update stale auth/setup statements in `README.md` before public release.
7. Only after the above pass, request explicit approval to change production Supabase Auth settings and deploy.

## Scope and changes

- The staging suite and guarded runner were added on `feature/public-onboarding`; no API, schema, migration, RLS, or Storage changes were made.
- No staging or production requests were made by this audit, and no secrets or user data were read or copied.
- The staging suite has not been executed.
- No merge, production setting change, or deployment was performed.
