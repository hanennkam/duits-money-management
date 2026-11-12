# ADR-001 — Authentication links and OAuth architecture

- **Status:** Accepted (recorded in Phase 5E, 2026-11-09). Email links (D1/D2) implemented in Phase 5F-A;
  Phase 5F-C remediated the 5F-B findings; Phase 5G redacted `token_hash` from Uvicorn access logs.
  Google OAuth/PKCE (D3) remains Phase 6A. External infrastructure logs are not covered — see
  `ADR-002-access-log-token-exposure.md`.
- **Scope:** browser authentication only (`app/static/index.html`). No backend, database or RLS change.
- **Supersedes:** the implicit URL-fragment token adoption in the current page.
- **Related:** `docs/CUTOVER_RUNBOOK.md` (legacy key policy), `NEXT_STEPS.md` (launch checklist),
  Phase 5C audit finding M2, Phase 5D hardening.

> This record is documentation. It does not change Supabase templates, dashboard settings, environment
> variables or application code. Those are Phase 5F (code) and Phase 6A (Google provider) work.

---

## 1. Context and the security issue

Duits signs users in against Supabase Auth with **direct REST calls** from a single vanilla-JS page. No
SDK, no build step. During Phase 5C the page was found to **adopt any `access_token` + `refresh_token`
pair presented in the URL fragment**, provided the fragment also said `type=invite|recovery|signup`:

```js
// index.html, before Phase 5D
var type = params.type || "";
if (type !== "invite" && type !== "recovery" && type !== "signup") return false;
pendingToken = params.access_token || null;
if (params.access_token && params.refresh_token) { writeSession(session); }
```

The fragment is attacker-controlled and there is no correlation with a flow this browser started.
An attacker can sign into their own account, copy that session's tokens, and send the victim
`https://<duits-host>/#access_token=…&refresh_token=…&type=recovery`. The victim's browser stores the
attacker's session: **login CSRF / session fixation**. Everything the victim then records lands in the
attacker's account, and the attacker can read it. The same class of bug also lets a link "sign in" a
browser with no email round-trip at all.

Phase 5D hardened the *handling* of the fragment without removing adoption:

- parsing moved into `parseAuthHash()` with `try/catch`, so a malformed escape cannot break boot;
- `stripAuthHash()` removes the fragment **before** the type is judged, so unknown fragments do not
  linger in history/screenshots/referrers;
- no session is written before the type gate.

That closed the leak and the boot failure, but **not** the fixation: `#access_token=…&type=recovery`
is still adopted. Removing adoption needs an architecture decision because Supabase's default email
links are exactly this implicit fragment redirect, and a naive removal breaks password recovery,
signup confirmation and admin invitations. This ADR records those decisions.

### Threat model

In scope:

- crafted links that inject a session (fixed by D1/D2 + removal of adoption);
- replayed or forwarded auth links (single-use tokens);
- tokens leaking through browser history, screenshots, referrers and logs;
- email security scanners consuming a link before the user does;
- a callback that arrives without a flow this browser started.

Out of scope (unchanged, recorded in §12): XSS reading `localStorage`, a compromised device, a
compromised Supabase project key, and server-side session revocation policy.

---

## 2. Decisions

### D1 — Email confirmation and password recovery use `token_hash`

Email confirmation and password recovery links carry a **one-time token hash in the query string**.
The page verifies it with the documented endpoint:

```http
POST {SUPABASE_URL}/auth/v1/verify
apikey: {SUPABASE_PUBLISHABLE_KEY}
Content-Type: application/json

{ "type": "signup", "token_hash": "<from the link>" }
```

**Rejected:** adopting `access_token` / `refresh_token` from a fragment. It cannot be correlated with
a flow, works cross-device by accident (the attacker's device), and is the fixation vector.

**Verified:** the endpoint, the payload and the OTP types are in the official GoTrue OpenAPI spec and
source (§5). Cross-device works because the token hash is validated server-side; no browser-local
verifier is involved.

**Token handling:** the token hash is single-use, short-lived, held in memory only, stripped from the
address bar immediately, and never logged, stored or put in another URL.

### D2 — Admin invitations use `token_hash`

Invitation links use the same mechanism (`type: "invite"`). Invitations are minted by the project
owner and therefore cannot use a browser-bound PKCE verifier. `token_hash` preserves cross-device
acceptance: the invited person can open the mail on a phone even if the owner sent it from a laptop.

**Rejected:** a documented exception that keeps fragment adoption for `type=invite`. One exception
re-opens the same fixation class, just with `type=invite`.

**Verified:** the invite template is minted with `type=invite` and the invite token is the user's
confirmation token (§5). `type=invite` is a first-class verify type.

### D3 — LAN development uses Web Crypto feature detection

Google OAuth uses PKCE S256, which requires `crypto.subtle`, which browsers expose **only in a secure
context**. On `http://<mac-LAN-ip>:8765/` the API is absent. The page must:

- require `window.isSecureContext === true` **and** `crypto.subtle` before starting a PKCE flow;
- when unavailable, explain why and leave email/password and `token_hash` links working (they need no
  Web Crypto);
- **never** fall back to `code_challenge_method=plain`, and never fall back to accepting hash tokens.

HTTPS (local certificate) or a secure tunnel is the documented preferred way to test OAuth on a phone.
No dev-server or networking configuration changes in this phase.

### D4 — No dual-support period for implicit hash tokens

There is no transition release that keeps adopting arbitrary fragments. Keeping the old path "just in
case" keeps the vulnerability open for the whole transition, which defeats the change.

- Links issued **before** the template switch (`#access_token=…`) will no longer be adopted and must be
  re-requested.
- The expired/invalid screen offers **Resend confirmation** (signup) and **Reset password** actions.
- Users see: *"This link has expired or was already used. Request a new confirmation email, or reset
  your password."*
- No Supabase template or setting changes are made in Phase 5E.

---

## 3. Current authentication architecture (as implemented)

All references are to `app/static/index.html` at the Phase 5E commit; line numbers shift as the file
changes.

### 3.1 Client

- **No SDK.** `authBase()` is `SUPABASE_URL`; `authHeaders()` sends `apikey: <publishable key>` and
  JSON. The publishable key is injected by the server at serve time (`AUTH`).
- **Session:** `localStorage["duits.session"]` =
  `{ access_token, refresh_token, expires_at, email }`.
  `expires_at` is UNIX seconds; expiry is treated as 60 s early (`sessionExpired()`).
- **Refresh:** one in-flight promise (`refreshInFlight`) so a burst of 401s costs one
  `POST /auth/v1/token?grant_type=refresh_token`. Failure drops the session and shows sign-in.
- **Any 401** from the Duits API triggers one refresh + one retry; a second 401 clears the session and
  caches, then shows sign-in.

### 3.2 Supabase endpoints used today

| Purpose | Call |
|---|---|
| Sign in | `POST /auth/v1/token?grant_type=password` |
| Refresh | `POST /auth/v1/token?grant_type=refresh_token` |
| Sign up | `POST /auth/v1/signup` |
| Resend confirmation | `POST /auth/v1/resend` `{type:"signup", email}` |
| Request recovery | `POST /auth/v1/recover` `{email, redirect_to}` |
| Set password from a link | `PUT /auth/v1/user` `{password}` with the link's access token |
| Current user / metadata | `GET`, `PUT /auth/v1/user` |
| Sign out | `POST /auth/v1/logout` |

### 3.3 Email confirmation and recovery today

1. **Signup.** `POST /auth/v1/signup` with `{email, password, data:{onboarding_version:1}}`. If the
   project has confirmations disabled, the response already carries a session and the page enters the
   app (`afterSignIn(..., true)`). Otherwise the page shows "Check your email".
2. **Confirmation.** The user opens the Supabase link. GoTrue's `GET /auth/v1/verify?token=…&type=signup`
   answers `302` to the app with **the session in the fragment**. `readAuthRedirect()` adopts it, the
   type gate sees `signup`, and `restoreSession()` enters the app and shows optional onboarding.
3. **Recovery.** `POST /auth/v1/recover` sends a link; opening it lands on the app with
   `#access_token=…&refresh_token=…&type=recovery`. The page adopts the session, then shows the
   **Set a new password** view. Saving calls `PUT /auth/v1/user {password}` with `pendingToken`.
4. **Invite.** Same as recovery with `type=invite`; the invited user sets a password and continues.

The defect is step 2–4's first action: **the fragment is trusted because of what it says about itself.**

### 3.4 What Phase 5D changed (retained)

`parseAuthHash()`, `stripAuthHash()`, strip-before-gate, no adoption before the gate, no unguarded
`decodeURIComponent`. These stay as defence in depth after adoption is removed.

---

## 4. Target architecture

### 4.1 Email links (signup, recovery, invite)

The Supabase email templates stop using `{{ .ConfirmationURL }}` and link to the app with the token
hash in the **query string** (Site URL configured without a trailing slash, as in Supabase's own
examples):

```html
<!-- Confirm signup -->
<a href="{{ .SiteURL }}/?token_hash={{ .TokenHash }}&type=signup">Confirm email address</a>

<!-- Invite user -->
<a href="{{ .SiteURL }}/?token_hash={{ .TokenHash }}&type=invite">Accept invitation</a>

<!-- Reset password -->
<a href="{{ .SiteURL }}/?token_hash={{ .TokenHash }}&type=recovery">Reset password</a>
```

Page flow:

1. On boot, read `token_hash` and `type` from `location.search` (not the hash).
2. **Immediately** `history.replaceState` them away; hold both in memory for this page load.
3. Choose the screen from `type`:
   - `signup` → "Confirm your email" card, one explicit **Confirm** button;
   - `recovery` → "Reset your password" card, then the password form;
   - `invite` → "Accept invitation" card, then set password + optional onboarding;
   - anything else → invalid-link card, no request.
4. Only the button tap sends `POST /auth/v1/verify`.
5. On 200, map the response to `writeSession()` and continue as today.
6. On failure, show the expired-link card with the two recovery actions.

No fragment is read for authentication. Any `#access_token=`, `#refresh_token=`, `#error=` is stripped
and ignored.

### 4.2 Google OAuth (Phase 6A integration, scaffolding in 5F)

```
GET {SUPABASE_URL}/auth/v1/authorize
    ?provider=google
    &redirect_to=<origin>/
    &scopes=email profile
    &code_challenge=<base64url(SHA-256(verifier))>
    &code_challenge_method=s256
```

- Verifier: 32+ random bytes from `crypto.getRandomValues`, base64url. Never `Math.random()`.
- Store `{verifier, created, flowId}` in `localStorage["duits.auth.flow"]` (or `sessionStorage`) with a
  10-minute TTL; single-use.
- Callback: GoTrue redirects to `redirect_to?code=<auth code>`.
- Require a stored flow record; **delete it before exchanging**.
- Exchange: `POST /auth/v1/token?grant_type=pkce` `{auth_code, code_verifier}`.
- Map the response to `writeSession()`; strip `code` from the URL in every outcome.
- No record / expired record / exchange failure → sign-in card with a generic message.

**Important verified detail:** GoTrue generates and validates the OAuth `state` itself (a flow-state
UUID) and strips client-supplied reserved OAuth parameters, so the app cannot round-trip its own
`state` through `/authorize`. See §5.6. Correlation is therefore: *this browser holds the verifier* +
a single-use code with a 5-minute lifetime. That is the security property `state` would provide
against code injection; a literal matching `state` parameter is not available.

### 4.3 What does not change

- Password sign-in, refresh and logout keep their current shape.
- The Duits API still receives `Authorization: Bearer <access token>` only.
- No backend, schema, RLS or service-role change.

---

## 5. Verified Supabase contract

Everything below was checked against the official GoTrue OpenAPI spec and source, and the official
Supabase guides, on 2026-11-09. Anything not directly shown there is marked **unverified**.

### 5.1 Sources

| Source | What it establishes |
|---|---|
| [GoTrue OpenAPI spec](https://github.com/supabase/auth/blob/master/openapi.yaml) | Endpoints, parameters, request/response schemas, OTP enums |
| [verify.go](https://github.com/supabase/auth/blob/master/internal/api/verify.go) | Token-hash lookup per type, single-use/expiry, error codes |
| [external.go](https://github.com/supabase/auth/blob/master/internal/api/external.go) | `/authorize` params, server-owned `state`, PKCE validation |
| [templatemailer.go](https://github.com/supabase/auth/blob/master/internal/mailer/templatemailer/templatemailer.go) | The `type=` value each email link is minted with |
| [auth-js types](https://github.com/supabase/auth-js/blob/master/src/lib/types.ts) | `EmailOtpType` union (`… , 'email'`) |
| [Email Templates guide](https://supabase.com/docs/guides/auth/auth-email-templates) | Template variables, custom-link pattern, prefetch warning |
| [PKCE flow guide](https://supabase.com/docs/guides/auth/sessions/pkce-flow) | Same-device limitation, 5-minute single-use code |
| [verifyOtp reference](https://supabase.com/docs/reference/javascript/auth-verifyotp) | Documented `{token_hash, type}` usage |
| [resetPasswordForEmail reference](https://supabase.com/docs/reference/javascript/auth-resetpasswordforemail) | Recovery initiation |
| [signInWithOAuth reference](https://supabase.com/docs/reference/javascript/auth-signinwithoauth) | OAuth initiation |
| [exchangeCodeForSession reference](https://supabase.com/docs/reference/javascript/auth-exchangecodeforsession) | PKCE exchange |
| [inviteUserByEmail reference](https://supabase.com/docs/reference/javascript/auth-admin-inviteuserbyemail) | Invite minting (admin key) |

### 5.2 Verification endpoint

`POST /auth/v1/verify` (OpenAPI `/verify` → `post`):

```json
{
  "type": "signup | recovery | invite | magiclink | email_change | sms | phone_change",
  "token_hash": "<hash>",
  "redirect_to": "<optional URI>"
}
```

- `token_hash` is documented as *"The hashed value of token. Applicable only if used with `type` and
  nothing else."* The server enforces this: `isUsingTokenHash()` requires `token_hash != ""` **and**
  `token`, `email`, `phone` all empty.
- **200** returns `AccessTokenResponseSchema`: `access_token`, `refresh_token`, `token_type`,
  `expires_in`, `expires_at`, `user`. This maps directly onto `writeSession()`; **no SDK is needed**.
- **403** with `error_code: otp_expired` and `"Email link is invalid or has expired"` when the hash is
  unknown, already consumed or past `Mailer.OtpExp`.
- **400** `validation_failed` for an unsupported type (`"Unsupported verification type"` /
  `"Invalid email verification type"`).
- **429** is documented on the endpoint.

The **GET** form (`/verify?token=…&type=…&redirect_to=…`) is the `{{ .ConfirmationURL }}` endpoint. It
answers `302` and puts tokens in the fragment (implicit) or a `?code=` in the query (PKCE). It remains
the endpoint the *old* templates point at; the new design does not use it from the app.

### 5.3 OTP types — what each one actually matches

| Type | Token searched | Resulting flow | Use in Duits |
|---|---|---|---|
| `signup` | confirmation token | signup verify | **Email confirmation** |
| `email` | confirmation **or** recovery token (alias; resolves to `signup`, or `magiclink` for a recovery token) | signup/magiclink | Not used directly; documented example uses it |
| `invite` | confirmation token | signup verify (invite semantics) | **Admin invitation** |
| `recovery` | recovery token | recover verify | **Password recovery** |
| `magiclink` | recovery token | recover verify | Not used |
| `email_change`, `sms`, `phone_change` | their own tokens | other flows | Out of scope |

Notes:

- The Supabase **guide's** `{{ .ConfirmationURL }}` example shows `type=email`; the **mailer source**
  mints the signup link with `type=signup`. Both work: `email` is in the `EmailOtpType` union and is
  handled as `EmailOTPVerification`. The ADR standardises on `signup` because it is what the server
  mints and it searches only the confirmation token.
- `recovery` and `magiclink` are both accepted for a recovery token; use `recovery` for password reset.
- Use `invite` for invitations even though the token is the same confirmation token: it is what the
  server mints and what the docs document.

### 5.4 Email template variables

Documented (`{{ … }}`): `.ConfirmationURL`, `.Token`, `.TokenHash`, `.SiteURL`, `.RedirectTo`,
`.Email`, `.Data`, `.NewEmail`, `.OldEmail`, `.SendingTo`.

Phase 5F uses only `.SiteURL` and `.TokenHash`; `type` is written literally per template (the mailer's
own `type` is not exposed as a variable).

### 5.5 PKCE exchange

`POST /auth/v1/token?grant_type=pkce`:

```json
{ "auth_code": "<code from the callback>", "code_verifier": "<the stored verifier>" }
```

- The code is valid for **5 minutes** and can be exchanged **once** (PKCE guide).
- A second exchange fails; the flow must be restarted.
- The exchange must happen in the **same browser/device** that created the verifier (PKCE guide,
  "Limitations").

### 5.6 `/authorize` and `state`

`GET /auth/v1/authorize` parameters (OpenAPI): `provider` (required), `scopes` (required), `redirect_to`,
`code_challenge_method` (`plain` | `s256`), `invite_token`. The handler also reads `code_challenge`.

`external.go` shows that the server:

- validates `code_challenge`/`code_challenge_method`;
- creates a **flow-state row** and uses its UUID as the OAuth `state`;
- strips client-supplied reserved OAuth params, including `state`, before building the provider URL;
- rejects a callback whose `state` is missing, malformed, unknown or expired (`bad_oauth_state`).

So **Supabase owns state correlation**. The app's job is to require that *it* has a matching stored
verifier before exchanging the returned code. `state` is *not* passed through to `redirect_to`, so an
app-generated state value cannot be compared on the callback. This is recorded as a limitation in §12.

`scopes` is marked required by the OpenAPI schema even though supabase-js only appends it when supplied.
Send `scopes=email profile`; confirm Google's configured scopes in Phase 6A (**partly unverified**).

### 5.7 Resend

`POST /auth/v1/resend` `{type, email}` supports only `signup`, `email_change`, `sms`, `phone_change`.

- **Confirmation resend:** available (`type=signup`).
- **Recovery resend:** not available — call `POST /auth/v1/recover` again.
- **Invite resend:** not available — the owner sends a new invite.

### 5.8 `redirect_to` placement

Every supabase-js call sends `redirect_to` as a **query parameter** (`fetch.ts` appends it to the URL).
The OpenAPI request body for `/recover` does **not** list `redirect_to` as a field. The current page
sends it in the JSON body. Whether the hosted server honours the body field is **unverified**; Phase 5F
should use the query parameter.

---

## 6. Error handling

| Situation | Detection | User-facing result | Session |
|---|---|---|---|
| Expired link | 403 `otp_expired` | Expired-link card: "This link has expired or was already used." + **Resend confirmation** + **Reset password** | none |
| Invalid / consumed token | 403 `otp_expired` (single-use) | Same card | none |
| Wrong verification type | 403 (token not found for that type) or 400 `validation_failed` | Same card. **Never** retry automatically with a different type | none |
| Unknown `type` in the URL | client-side allow-list | Invalid-link card, **no network call** | none |
| Missing PKCE verifier / no stored flow | client-side | "This sign-in link was opened in a different browser. Start again here." | none |
| Missing/mismatched OAuth state | Supabase rejects (400 `bad_oauth_state`), or `?error=` returned | Generic "Sign-in failed. Try again." | none |
| Replayed OAuth callback | second `/token?grant_type=pkce` fails | Generic failure; no partial session | none |
| Replayed email link | second `/verify` → 403 | Expired-link card | none |
| Network failure during verify | fetch rejects | Keep the token hash in memory; **Retry** button. Do not reload (a reload loses it) | none |
| 429 | status 429 | "Too many attempts. Wait a minute and try again." | none |
| Provider error | `error` / `error_description` in the callback query | Generic message; details never rendered as HTML and never logged | none |

Rules that apply to every row:

- the token hash, code, verifier and tokens are never logged, never put in `localStorage` (except the
  finished session), and never sent anywhere but Supabase;
- error text is set with `textContent`, never `innerHTML`;
- a failed flow leaves the previous session untouched if one existed (opening a bad link must not sign
  the user out).

---

## 7. Cross-device behaviour

| Flow | Cross-device? | Why |
|---|---|---|
| Email confirmation (`token_hash`) | **Yes** | Server validates the hash; the POST carries no browser-local secret |
| Password recovery (`token_hash`) | **Yes** | Same |
| Admin invitation (`token_hash`) | **Yes** | Same; the invitee can open it on their own phone |
| Google OAuth (PKCE) | **No** | The verifier lives in the starting browser; PKCE guide states the exchange must start there |
| Password sign-in | Yes | Ordinary credentials |

Consequence: email links are the cross-device-safe mechanism and are used for all three email flows.
Google sign-in is expected to be completed on the device that started it; if it is not, the page says so
and offers email sign-in.

---

## 8. LAN and insecure-context behaviour

- `window.isSecureContext` is true for `https://…` and for `http://localhost` / `127.0.0.1`; it is
  **false** for `http://<mac-LAN-ip>:8765/`.
- `crypto.subtle` is absent when the context is insecure. (`crypto.getRandomValues` may still exist;
  that is not enough.)
- Before showing **Continue with Google**, check `isSecureContext && crypto && crypto.subtle`. If it
  fails, do not start the flow and show:

  > Google sign-in needs a secure connection. Open Duits over HTTPS, or use email and password.

- **No `plain` fallback.** supabase-js degrades to `code_challenge_method=plain` with a console warning
  when Web Crypto is missing; Duits must not copy that. A `plain` verifier offers no protection if the
  code is intercepted.
- Email/password and all `token_hash` links keep working on plain-HTTP LAN, because they need no Web
  Crypto. That keeps phone testing usable.
- Preferred phone testing: HTTPS with a locally trusted certificate, or a secure tunnel. The chosen
  method and commands are documented in Phase 5F; no server/network config changes now.

---

## 9. Email prefetch and security scanners

Supabase documents the problem: providers such as Microsoft Defender Safe Links prefetch URLs, and with
`{{ .ConfirmationURL }}` the GET **consumes the token instantly**, producing "Token has expired or is
invalid" before the user clicks.

Mitigations documented by Supabase: use the OTP (`{{ .Token }}`), or link to an intermediate page that
performs verification only on user action.

This ADR takes the second route, which also removes the fixation vector:

- the email links to `{SiteURL}/?token_hash=…&type=…` — a **plain page load does not consume the hash**;
- the page strips the parameters and shows a card with one explicit button;
- **no** verification request is sent on load, on focus, on visibility change or on a timer;
- verification happens exactly once, on the tap.

Residual risks and responses:

- A scanner can load the page; that only renders a card. It cannot press the button.
- A prefetcher that executes JavaScript still finds no automatic POST.
- The token hash appears in the email link and in the first page URL. It is removed with
  `replaceState` before any rendering that could leak it, the app already sends
  `Referrer-Policy: no-referrer`, and it is never written to storage or logs.
- A user who reloads the card loses the in-memory hash; they are told to reopen the link. This is
  preferable to persisting a credential in storage.

---

## 10. Migration sequence and rollback

### 10.1 Ordering

The template format and the page must switch together. Either order alone has a window where links do
not work:

| First | Effect during the window |
|---|---|
| Page first | Old templates still send `#access_token=…`; the new page ignores it → users see the expired-link card |
| Templates first | Links carry `?token_hash=…`; the old page ignores the query → same |

Recommended: **deploy the code, then change the three templates immediately** (or vice versa), and treat
the deploy duration as the window. The dashboard change is instant; the Render deploy is minutes.

### 10.2 Impact on existing links

Per D4:

- Links issued before the switch are not adopted and will not work. They must be re-requested.
- Because Supabase tokens are single-use and time-limited anyway, the practical impact is "the last
  email someone has not opened yet".
- Any link already consumed before the switch has already created its session; the switch does not
  revoke it.

### 10.3 Rollback

- **Code rollback** restores fragment adoption. `?token_hash=` links then stop working, and recovery /
  confirmation return to the old template path. Do not roll back the code while the new templates are
  live unless the templates are reverted too.
- **Template rollback** restores `{{ .ConfirmationURL }}`, which points at `GET /auth/v1/verify`; the
  old page path resumes.
- Roll back both together, exactly as they were deployed. No data migration is involved: users,
  passwords and transactions are untouched.
- Rolling back **re-opens** the fixation vulnerability; it is an incident-response action, not a
  routine one.

> **Deployment gate (Phase 5G).** The Uvicorn application access log is redacted (ADR-002). External
> logs (Render edge/proxy, drains) are not covered and remain unverified; confirm or formally accept
> them before production. The paired email-template change in §10 is still required.

---

## 11. Phase 5F implementation sequence and test plan

### 11.1 Sequence

**Code (one reviewable PR; page + tests only; no backend):**

1. Add `parseAuthParams()` for `location.search` (query, not hash) and a `stripAuthParams()` that
   removes `token_hash`, `type`, `code`, `state`, `error`, `error_description` before anything else runs.
2. Add `verifyEmailLink(type, tokenHash)` → `POST /auth/v1/verify` `{type, token_hash}`; map 200 to
   `writeSession()` using `expires_at` (fallback `expires_in`).
3. Add the intermediate card and route by `type`: `signup` → confirm → onboarding; `recovery` → reset
   → password form; `invite` → accept → set password (+ onboarding); unknown → invalid.
4. Delete fragment adoption from `readAuthRedirect()`; keep stripping. Old-style fragments are ignored
   and produce the expired-link card.
5. Add the expired-link card with **Resend confirmation** (`/resend` `{type:"signup"}`) and **Reset
   password** (`/recover` with `redirect_to` as a query param). Reuse the existing no-enumeration copy.
6. Add secure-context detection that gates only the Google button, with the message in §8. No `plain`.
7. Add Google start: verifier + S256 challenge, stored flow record (TTL 10 min), navigate to
   `/authorize` with `provider`, `redirect_to`, `scopes=email profile`, `code_challenge`,
   `code_challenge_method=s256`.
8. Add callback handling: require the flow record, delete it **before** `POST /token?grant_type=pkce`,
   map the session, strip `code` in success and failure. (Deleting first means a network failure during
   the exchange requires restarting the sign-in; that is the safer default.)
9. Keep refresh/logout untouched; confirm a failed link does not clear an existing session.
10. Add the tests in §11.2.

Steps 1–6 are shippable without Google being enabled. 7–8 can land dark (button hidden behind a flag)
until Phase 6A.

**Manual Supabase dashboard (owner; not code, not this phase):**

11. **Auth → Email Templates** — replace the bodies of *Confirm signup*, *Invite user* and *Reset
    password* with the links in §4.1. Keep the rest of the copy. Do not touch *Magic link*.
12. **Auth → URL Configuration** — confirm the Site URL and the redirect allow-list for staging, the
    Render host, and the HTTPS/tunnel URL used for phone testing.
13. **Google provider** — stays disabled until Phase 6A. This phase verifies the client flow only.

### 11.2 Test plan

The current Python suite does not execute JavaScript; it pins strings in the served page. Phase 5F
should keep those and add behaviour tests for the pure pieces.

**Static/contract tests (add to `tests/test_page_auth.py`, `tests/test_static.py`):**

- no code path writes a session from `location.hash`, `params.access_token` or `params.refresh_token`;
- `token_hash` + `type` are read from `location.search` and stripped before any `fetch`;
- the verify body is exactly `{type, token_hash}` (no `email`, no `token`);
- the three accepted types map to the three screens; an unknown type performs no request;
- no verification request fires on load (no top-level call, no `DOMContentLoaded` hook, no timer);
- the Google button is gated on `isSecureContext` and `crypto.subtle`, and the page contains no
  `"plain"` challenge method;
- the callback requires the flow record, deletes it before exchange, and strips `code`;
- error mapping covers 403/400/429/network and uses `textContent`.

**Behaviour tests (new, optional harness):** `node` is available in the dev environment. Extract the
parser, URL cleanup, error mapping and session mapping into functions that can run under Node with a
stubbed `fetch`, then cover:

| Case | Expected |
|---|---|
| Valid `token_hash` | one POST, session written, URL clean |
| Invalid hash | 403 → expired card, no session |
| Expired hash | 403 → expired card, resend/recover offered |
| Replayed hash | second POST → expired card |
| Wrong type for the hash | failure card, no automatic retry |
| Missing query params | no request |
| OAuth without stored flow | no exchange |
| OAuth with mismatched/expired flow | no exchange |
| Valid PKCE callback | one exchange, verifier deleted, URL clean |
| Replayed OAuth code | second exchange fails, no session |
| Network error | retry offered, hash retained in memory |

**Manual browser checks (record what was and was not done):**

- Desktop Chrome and Safari: all three email links, expired link, resend, recover, Google start/callback.
- iOS Safari on a real iPhone: link from Mail, keyboard/sheet behaviour, standalone Home Screen app.
  Emulation is not a substitute (AGENTS.md §3.2).
- Two browsers: link requested in A, opened in B (must work); Google started in A, opened in B (must
  explain why it fails).

**Staging integration (Phase 5F/6A, gated; not run in Phase 5E):**

- Use staging `tddigsmukmhkjrwiqdec` only; the isolation guard must still refuse
  `viorpltdkpexswvofeul`.
- Request a confirmation and a recovery email for a **new** staging user; open on a second browser;
  verify, replay, and confirm the second attempt fails.
- Invite a second staging address and accept on a different browser.
- Account linking: while signed in as an existing email/password staging user, start
  `GET /auth/v1/user/identities/authorize?provider=google&scopes=…` and confirm the same `sub`/user is
  kept and `user_metadata` is preserved. **Requires manual linking to be enabled** (**unverified**) and
  is part of Phase 6A.
- Onboarding metadata: today `onboarding_version:1` is set only by email signup. A Google-first user has
  no metadata, so `needsOptionalOnboarding()` returns false. Decide in 6A whether to write the metadata
  after the first OAuth sign-in; do not silently change the condition.

---

## 11.3 Phase 6B-3A implementation status (2026-11-10)

The client-side Google OAuth PKCE flow is implemented in `app/static/index.html` and is **dark** behind
`GOOGLE_OAUTH_CONFIGURED = false`. The provider is still disabled, so this is not a working Google
sign-in for users.

Implemented:

- No Supabase JS SDK is added: the page uses the same documented REST endpoints the SDK uses. The
  authorization-code exchange is Supabase’s PKCE endpoint, not a custom OAuth implementation.
- `GET /auth/v1/authorize` with `provider=google`, `redirect_to=origin + "/"`, `scopes=email profile`,
  `code_challenge` and `code_challenge_method=s256`.
- A 32-byte verifier from `crypto.getRandomValues`, base64url-encoded; S256 challenge from
  `crypto.subtle.digest`.
- A single-use flow record in `sessionStorage` under `duits.auth.oauth`, with a 10-minute TTL and a
  10-second repeat guard. No code, verifier or token is written to `localStorage`.
- Callback handling for `?code=` and provider `?error=`: clean the URL first, require an unexpired flow
  record, remove the record before exchanging, and call
  `POST /auth/v1/token?grant_type=pkce` with exactly `{auth_code, code_verifier}`.
- Existing `sessionFromAuthBody()` mapping and `afterSignIn()` routing. New Google users are detected by
  onboarding metadata or a recent `created_at`; completed users go to the dashboard; incomplete users
  resume onboarding. Finance settings are never written by the OAuth path.
- No custom account-linking: the app never reads email, user ID or metadata from the callback to link
  identities. The authenticated Supabase session is the only identity source; Supabase owns linking.
- Error mapping for cancellation, missing/expired flow, malformed callback, network, rate limit, server
  and storage failures. A failed callback preserves an existing valid session.
- The Google button remains disabled with the honest “isn't available yet” note until the flag is flipped.

Tests: `tests/js/oauth_pkce_test.mjs` (22 behavioural cases) plus static assertions in
`tests/test_page_auth.py` and `tests/test_static.py`.

### Required Phase 6B-3B configuration (manual, not done)

1. Google Cloud: create an OAuth 2.0 **Web application** client. Authorized redirect URI:
   `https://tddigsmukmhkjrwiqdec.supabase.co/auth/v1/callback`. Keep the client secret in the Supabase
   dashboard, never in the repository.
2. Supabase staging → Authentication → Providers → Google: enable, set the client ID and secret, and
   keep only the basic identity scopes.
3. Provide a secure HTTPS staging origin (Render service or stable tunnel). Set the exact Site URL and
   redirect allow-list; the current `http://192.168.8.105:8765` origin is not a secure context.
4. Verify Supabase’s account-linking policy for an existing verified email user before enabling the
   provider. Do not assume automatic linking; do not link unverified emails in the app.
5. Flip `GOOGLE_OAUTH_CONFIGURED = true` only after provider and HTTPS are ready.
6. Run real desktop/iPhone E2E: new user onboarding, returning user dashboard, existing email user
   linking, cancellation/denial, replay, cross-browser callback, and settings preservation.

Remaining limitations: no real Google authentication, no provider configuration, no HTTPS staging
origin, no real-device test, and one PKCE flow per browser (a second start replaces the first after the
repeat guard).

---

## 12. Unresolved technical limitations

1. **No app-generated OAuth `state`.** Supabase owns and strips `state`; the app cannot compare a
   self-generated value on the callback. Correlation is the locally stored verifier plus a single-use,
   5-minute code. If a product requirement demands a visible `state`, the architecture must change
   (custom OAuth, which is out of scope and discouraged).
2. **Overlapping PKCE flows.** Two Google sign-ins started in the same browser overwrite the stored
   verifier; the first callback then fails. Supabase's multi-flow support is experimental
   (`appendPkceFlowIdToRedirects`). Duits will keep one flow key and document the behaviour.
3. **JavaScript test runtime.** The auth-link core is covered by `tests/js/auth_link_test.mjs` under Node
   (run by pytest when Node is present); the DOM wiring is still pinned by string assertions. A real
   browser is still required for the page itself.
4. **Template drift.** Email templates live only in the Supabase dashboard. If they are edited there,
   the repo cannot detect the change. Phase 5F should record the exact bodies in the ADR or a doc and
   check them manually before each release.
5. **Invite resend does not exist.** A lost/expired invite needs a new `inviteUserByEmail` call by the
   owner.
6. **Recovery resend is a new `/recover` call**, subject to rate limits.
7. **`type=email` vs `type=signup`.** The docs example says `email`, the mailer mints `signup`, and both
   work. Phase 5F-C normalizes `email` to `signup` in the page, so either template form is accepted.
8. **`redirect_to` in the `/recover` body is unverified.** Phase 5F-C uses the documented query string
   instead (`/recover?redirect_to=…`), matching supabase-js and GoTrue's `r.Form` handling.
9. **OTP expiry and rate limits are project/plan settings.** The exact values were not verified here;
   read them from the dashboard before writing copy that states a duration.
10. **`scopes` for Google** is marked required by the OpenAPI but supabase-js omits it unless supplied.
    The correct minimal set depends on the provider configuration (Phase 6A).
11. **Session storage remains `localStorage`.** Any XSS can read the access and refresh tokens. This ADR
    removes URL-token injection, not XSS. Moving to `HttpOnly` cookies would be a separate architecture
    change (and needs a backend).
12. **No real iPhone or real mailbox verification was performed in Phase 5E.** The flow is specified
    from official sources, not observed end-to-end.
13. **Access-log exposure of `token_hash`.** Uvicorn's application access log is redacted in Phase 5G
    (`app/logging_redaction.py`). Render edge/proxy logs and external drains are not covered and their
    retention is unverified; see `ADR-002-access-log-token-exposure.md`.
