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

### 5. Onboarding settings write — contract reviewed, end-to-end proof pending

- Optional onboarding reuses `PUT /finance/settings` for `opening_balance` and `monthly_budget`.
- Blank values are omitted; Skip records onboarding completion without submitting either financial value.
- The endpoint is owner-scoped through `CurrentUser` and the finance-settings DB helper.
- Verify on staging that a new account can save each field, skip both, sign out/in and resume incomplete onboarding, and cannot see another test account's values.

## Required release test matrix

| Area | Required proof | Current status |
| --- | --- | --- |
| Python suite | Run `./.venv/bin/python -m pytest -q` on the exact branch head | Not run in this audit environment |
| UI harness | Run the repo's documented UI harness if present; otherwise record unavailable | Not run; harness is documented as external/not in repo |
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

1. Create or identify two dedicated staging test accounts and use the staging Supabase project only.
2. Confirm staging schema has every migration required by the current app, including finance settings and commitment/payment tables. The checked-in runbooks contain historical notes and must not be treated as proof of current staging state.
3. Run the full pytest suite on a local checkout of this exact branch head and record the actual summary. Do not substitute historical test counts from `NEXT_STEPS.md`.
4. Execute the staging test matrix above, especially cross-account object access and signed receipt URLs.
5. Test the whole onboarding and recovery journey on desktop and a physical iPhone.
6. Review and update stale auth/setup statements in `README.md` before public release.
7. Only after the above pass, request explicit approval to change production Supabase Auth settings and deploy.

## Scope and changes

- This audit made no application code, API, schema, migration, RLS, or Storage changes.
- No secrets, tokens, user data, or live account identifiers were read or copied.
- No tests were executed by this audit.
- No merge, production setting change, or deployment was performed.
