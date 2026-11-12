# ADR-002 — Access-log exposure of `token_hash`

- **Status:** **Resolved for the Duits application's Uvicorn access logs** (Phase 5G, 2026-11-09).
  External infrastructure logs (Render edge/proxy, log drains) remain outside this decision and unverified.
- **Recorded:** Phase 5F-C (2026-11-09), from Phase 5F-B finding M1.
- **Scope:** operational logging for the Duits web service. No configuration was changed in Phase 5F-C.

---

## 1. Context

Email links point at the app with the verification token in the query string:

```
https://<duits-host>/?token_hash=<hash>&type=signup|recovery|invite
```

The browser sends that URL to the Duits backend **before** any page JavaScript runs. The page then
strips the parameters (`cleanAuthUrl()`), but the request has already reached the server.

The token hash is a credential: it is single-use, but while it is valid anyone who has it can call
`POST /auth/v1/verify` with the public publishable key and receive the session.

## 2. What was verified

- Uvicorn enables access logging by default (`uvicorn/config.py:216`, `access_log: bool = True`).
- The access-log request line includes the query string
  (`uvicorn/protocols/utils.py:58-63` `get_path_with_query_string`, used by
  `uvicorn/logging.py:107`).
- The container command does not disable it:
  `Dockerfile:24` (`uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`) and
  `ctl.sh:31` (`python -m uvicorn app.main:app --host … --port …`).
- The FastAPI app itself does not log the request URL; the exposure is the server access log.
- Render captures the service's stdout, so the line is expected to appear in the Render log stream.
  Render's retention, access control and export policy were **not** inspected (out of scope).

A typical line is:

```
<client> - "GET /?token_hash=<hash>&type=signup HTTP/1.1" 200
```

### 2.1 Implementation (Phase 5G)

**Option A was implemented: redact, do not disable.**

- `app/logging_redaction.py` defines `RedactTokenHashFilter`, attached to the `uvicorn.access`
  logger. It rewrites the string arguments of the access record before any formatter runs:
  every `token_hash` value becomes `[REDACTED]`.
- Keys are decoded and compared case-insensitively before matching, so `token%5Fhash`,
  `TOKEN_HASH` and `Token_Hash` are also redacted. Values are replaced wholesale, so a
  percent-encoded value cannot bypass the match. Repeated parameters are all redacted. Order,
  unrelated parameters and their original encoding are preserved.
- The filter never mutates the request's ASGI scope. If a future Uvicorn version attaches the
  scope to the record, the filter replaces it with a sanitised copy.
- It is installed when `app.main` is imported, and again (idempotently) at application startup.
  Uvicorn 0.54 configures logging in `Config.__init__` before importing the app, and
  `dictConfig` does not clear an existing logger's filters. Both documented startup paths run
  `uvicorn app.main:app`, so no `Dockerfile` or `ctl.sh` change was needed for activation.
- The runtime requirement is `uvicorn[standard]>=0.54.0,<0.55.0`: the minor verified by the
  integration test, with patch releases inside 0.54 allowed.
- Access logging stays enabled; method, path, status code and latency are unchanged.

Captured from a real Uvicorn process with a dummy token:

```
INFO:     127.0.0.1:51451 - "GET /?token_hash=[REDACTED]&type=signup HTTP/1.1" 200 OK
```

The dummy token was absent from the complete captured output. The regression suite is
`tests/test_logging_redaction.py` (15 tests, including a real `uvicorn app.main:app`
subprocess); the full ordinary suite passes 396 tests.

**Not covered:** Render's edge/proxy request logs, any external log drain, and copies of logs
made outside the application. Their retention and access policies have not been verified.

## 3. Risk

- Anyone with access to the service logs can read a live token hash and consume it before the user,
  taking over the session the link would create (or changing the password, for a recovery link).
- The window is bounded by the Supabase OTP expiry and by single use, but the log may be retained far
  longer than the token is valid.
- Logs are often copied into support tickets, dashboards, or third-party log drains, widening access.
- The risk applies to staging as well as production; staging links can authenticate staging accounts.

## 4. Mitigation options

### Option A — Redact `token_hash` in the access log (recommended)

Add a logging filter/formatter (or a small ASGI middleware) that replaces the `token_hash` value
with `[redacted]` before the record is emitted.

- **Keeps** method, path, status, latency and client address: operational visibility and abuse
  detection are preserved.
- Requires a backend change (not in Phase 5F-C). It must cover the uvicorn access record and any
  other place the URL could be logged (exception traces, proxies).
- Must be tested: the log line for `/?token_hash=secret` must not contain `secret`.

### Option B — Disable access logs

Run uvicorn with `--no-access-log` (or `access_log=False`).

- **Removes** the exposure from the application server with a one-line operational change and no
  code.
- **Loses** request-level observability: status distribution, latency, client addresses and abuse
  signals. That is a real operational cost for a small service.
- Does not necessarily remove edge/proxy logs (Render's own request logs), so the guarantee is
  weaker than it appears.

### Option C — Keep the token out of the request URL

Use a fragment (`#token_hash=…`) or a POST/form landing page.

- Avoids the server receiving the token at all.
- Conflicts with the approved query-parameter design in ADR-001 and would need its own decision and
  migration; not a Phase 5F-C change.

### Option D — Formally accept the risk

Document who can read the logs, the retention period, and why the single-use/short-expiry window is
acceptable. This is a decision, not a fix, and should be time-bounded and reviewed.

## 5. Impact comparison

| | Redaction (A) | Disable access logs (B) |
|---|---|---|
| Token removed from logs | Yes, if all log paths are covered | Yes for uvicorn; proxy logs may remain |
| Operational visibility | Preserved | Lost |
| Code/config change | Small backend change | One flag |
| Residual risk | A missed log path or trace | Blind to request-level abuse |

## 6. Decision taken

**Option A — redact `token_hash` in the Uvicorn access log — is implemented.**

- The original token value is replaced with `[REDACTED]`.
- Method, path, status code, latency and unrelated query parameters are preserved.
- Access logging remains enabled; no observability was lost.
- No request URL, application request handling or Supabase authentication behaviour changed.

Options B (disable access logs), C (move the token out of the request URL) and D (formally
accept the risk) were not chosen. Option D remains relevant only for the external logs listed
below.

## 7. Deployment gate

- The **Uvicorn application-access-log** exposure is resolved; that specific blocker is lifted.
- **External logs are not covered.** Render's edge/proxy logs, external log drains and copies
  made outside the application may still contain the request URL. Their retention and access
  have not been verified. Confirm or formally accept them before production.
- Staging and production still require the paired email-template change described in ADR-001
  §10; this ADR does not change templates or dashboard settings.
- Phase 5G changed no Supabase settings, templates, credentials or infrastructure.
