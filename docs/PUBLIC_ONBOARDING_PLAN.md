# Duits public onboarding — implementation plan

Status: Phases 1–3 implemented on `feature/public-onboarding`; Phase 4 static audit documented, but staging verification and release gates remain outstanding. See `docs/PHASE_4_RELEASE_AUDIT.md`. This work does not enable public signup or change production behaviour.

## Product direction

**Duits — Your money, understood.**

A calm, editorial, iPhone-first welcome experience. It should feel native to the existing product rather than like a separate marketing template: warm neutral surfaces, confident typography, restrained green accent, generous spacing, clear hierarchy and short, purposeful motion. Avoid gradient blobs, decorative dashboards full of fake figures, and generic SaaS card grids.

Core promise: help people understand where their money goes, without making money management feel like work.

## First-time journey

1. **Welcome** — one clear promise and a primary “Get started” action. Returning users retain a direct sign-in path.
2. **What Duits helps with** — three concise value moments: see spending clearly; capture receipts and notes with AI; stay ahead of budgets and recurring commitments. No fabricated transaction data.
3. **Create account** — email and password, clear password requirements, terms/privacy links only when real URLs are available. Google/Apple sign-in is explicitly out of scope until provider configuration is ready.
4. **Verify email** — confirmation-required state with resend guidance, change-email path, and clear handling for expired or already-used links.
5. **Personalise (optional)** — starting balance and monthly budget can be skipped. Explain why each value is requested; do not make users disclose financial details before they can explore.
6. **First dashboard** — a small contextual prompt to add the first transaction or scan a receipt. Dismissible and never blocks the app.

Returning users should not see the welcome journey again. Preserve sign-in, password recovery, invite/recovery redirects and existing sessions.

## Visual and interaction principles

- Mobile-first, especially iPhone Safari and Home Screen standalone.
- Respect existing safe-area, keyboard, scroll-lock, reduced-motion and 16px input-size rules in AGENTS.md.
- One dominant action per step; secondary actions are visually quieter.
- Use progressive disclosure; avoid long forms and forced setup.
- Motion should be short and purposeful, using the existing Web Animations conventions where needed.
- No stock imagery, fake financial numbers, or decorative charts that imply real account data.
- Accessible labels, focus states, keyboard navigation and clear loading/error/success states.

## Technical approach

Keep the current architecture: FastAPI, one-file vanilla JS/CSS frontend, Supabase Auth/Postgres and Render. Do not introduce a frontend framework or a build pipeline for this work.

### Public registration gates

The current app is invite-only. Public registration is not just a UI toggle. Before enabling it for real users:

- Implement Supabase Auth sign-up with email confirmation required.
- Keep the service-role key server-side; only the publishable key may reach the browser.
- Validate email/password client-side for usability and rely on Supabase for authoritative validation.
- Handle duplicate accounts, weak passwords, rate limits, offline/network failures, expired confirmation links and resend flows without exposing sensitive account-existence details unnecessarily.
- Confirm auth redirect URLs and email templates for both production and staging.
- Preserve password recovery and invite/recovery link handling.
- Audit per-user isolation for transactions, receipts/storage objects, budgets, commitments and every user-scoped endpoint. Test with two separate accounts.
- Do not change database schema, RLS policies, production Auth settings or deploy without explicit approval.

### Onboarding state

Prefer a small versioned onboarding-completion marker in Supabase user metadata so completion follows the account across devices. Keep personalisation values optional and only persist values the user explicitly submits. Do not add a database migration unless a demonstrated requirement cannot be met with existing metadata.

## Delivery phases

### Phase 0 — baseline and safety
- Confirm current auth states, redirects and boot flow.
- Record baseline test results.
- Keep all work on `feature/public-onboarding`.

### Phase 1 — welcome experience
- Add welcome and value-proposition screens.
- Add clear paths to sign in and begin registration.
- Keep existing sign-in and dashboard logic unchanged.
- Test responsive layout, keyboard/focus behaviour and reduced motion.

### Phase 2 — public registration
- Add sign-up and email-confirmation states.
- Preserve sign-in, password recovery and invite/recovery handling.
- Use staging Supabase configuration for end-to-end tests first.

### Phase 3 — optional personalisation and first-use guidance
- [x] Add skippable starting-balance/monthly-budget setup after account verification.
- [x] Persist completion in Supabase Auth user metadata (`onboarding_completed`, versioned) without forcing financial disclosure.
- [ ] Add a dismissible first-transaction prompt (deferred; not required to complete optional setup).

Implementation notes: setup reuses the existing `/finance/settings` API for `opening_balance` and `monthly_budget`; blank fields are not written. “Skip for now” records completion without writing either financial value. New accounts resume incomplete setup on later sign-ins.

### Phase 4 — release gates
- [x] Static source audit of JWT verification, owner-scoped DB helpers, finance/commitment routes and receipt path enforcement; findings recorded in `docs/PHASE_4_RELEASE_AUDIT.md`.
- [x] Add static regression checks for signup, confirmation, resend, optional save/skip, resume and recovery preservation in `tests/test_static.py` (seven checks; execution pending).\n- [ ] Full pytest suite on the exact branch head and UI harness (if available).
- [ ] Two-account isolation checks across all private data and receipt storage on staging.
- [ ] End-to-end staging signup, confirmation, resend, recovery and optional onboarding.
- [ ] Regression checks for transactions, AI receipt scanning, commitments and recovery.
- [ ] iPhone Safari and Home Screen testing on a real device.
- [ ] Production Supabase setting changes and deployment only after owner approval.

## Acceptance criteria

- A new visitor can understand the product and find the registration path.
- A user can register, confirm their email and reach their own account.
- Existing sign-in and password recovery continue to work.
- Returning users do not repeat completed onboarding.
- Personalisation can be skipped without blocking access.
- No user can read or mutate another user's transactions, receipts, budgets or commitments.
- Existing transaction entry, AI scanning and commitments remain functional.
- Mobile Safari, desktop Chrome and standalone PWA layouts are checked; real-device checks are explicitly reported.
- No production settings, database policies or deployment are changed without approval.

## Current boundary

This plan is not permission to enable public signup in the live Supabase project, change database policies, or deploy. Those are separate release actions requiring explicit approval.
