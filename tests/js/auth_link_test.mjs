// Behavioural tests for the auth-link core embedded in app/static/index.html.
//
// The page is one vanilla-JS file, so the core is deliberately DOM-free and dependency-injected.
// This harness extracts the marked block, runs it under Node with a stubbed request/session, and
// drives the real functions. Run with: node tests/js/auth_link_test.mjs
//
// No framework: a failing assertion prints the case and exits non-zero.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(join(here, "..", "..", "app", "static", "index.html"), "utf8");
const startMarker = "/* ---------- auth link core";
const endMarker = "/* ---------- end auth link core";
const start = page.indexOf(startMarker);
const end = page.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "the auth link core block is missing from index.html");

const block = page.slice(start, end);
const core = new Function(
  block +
    "\nreturn { createAuthLinkFlow, createAuthGuard, updatePasswordForSession, parseQuery, readAuthLink, removeAuthKeys, normalizeAuthLinkType, classifyVerifyFailure, authLinkMessage, sessionFromAuthBody };"
)();

const OK_BODY = {
  access_token: "access-token",
  refresh_token: "refresh-token",
  expires_at: 2000,
  user: { email: "person@example.com" }
};

function makeFlow(response) {
  const calls = [];
  const writes = [];
  const cleans = [];
  const flow = core.createAuthLinkFlow({
    request: async (method, path, body) => {
      calls.push({ method, path, body });
      if (response instanceof Error) throw response;
      return response;
    },
    writeSession: (session) => writes.push(session),
    emailFromToken: () => "",
    now: () => 1000,
    cleanUrl: () => cleans.push(true)
  });
  return { flow, calls, writes, cleans };
}

// A flow whose request stays pending until the test resolves it, so cancellation and overlap can be
// driven deterministically.
function makeDeferredFlow() {
  const calls = [];
  const writes = [];
  const cleans = [];
  let resolveRequest = null;
  const flow = core.createAuthLinkFlow({
    request: (method, path, body) => {
      calls.push({ method, path, body });
      return new Promise((resolve) => { resolveRequest = resolve; });
    },
    writeSession: (session) => writes.push(session),
    emailFromToken: () => "",
    now: () => 1000,
    cleanUrl: () => cleans.push(true)
  });
  return { flow, calls, writes, cleans, resolve: (response) => resolveRequest(response) };
}

function makePasswordDeps(overrides = {}) {
  const calls = [];
  const deps = {
    request: async (method, path, body, token) => {
      calls.push({ method, path, body, token });
      return { ok: true, status: 200, body: {} };
    },
    refresh: async () => null,
    isExpired: () => false,
    ...overrides
  };
  return { deps, calls };
}

const tests = [];
function test(name, fn) {
  tests.push([name, fn]);
}

// --- reading the link -------------------------------------------------------

test("signup link is read and the URL is cleaned without a request", async () => {
  const { flow, calls, cleans, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  const link = flow.begin("?token_hash=hash-1&type=signup", "");
  assert.deepEqual(link, { kind: "ready", type: "signup" });
  assert.equal(cleans.length, 1, "auth parameters must be stripped immediately");
  assert.equal(calls.length, 0, "no verification request may happen on page load");
  assert.equal(writes.length, 0, "no session may be written on page load");
  assert.equal(flow.hasPending(), true);
});

test("recovery and invite links are accepted", async () => {
  for (const type of ["recovery", "invite"]) {
    const { flow } = makeFlow({ ok: true, status: 200, body: OK_BODY });
    assert.deepEqual(flow.begin(`?type=${type}&token_hash=h`, ""), { kind: "ready", type });
  }
});

test("unrelated query parameters are left alone", async () => {
  const { flow, cleans } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  assert.deepEqual(flow.begin("?utm_source=mail", ""), { kind: "none" });
  assert.equal(cleans.length, 0);
});

test("a legacy fragment is reported as unusable and never adopted", async () => {
  const { flow, calls, writes, cleans } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  const link = flow.begin("", "#access_token=stolen&refresh_token=stolen&type=recovery");
  assert.deepEqual(link, { kind: "invalid", reason: "legacy" });
  assert.equal(cleans.length, 1);
  assert.equal(calls.length, 0);
  assert.equal(writes.length, 0);
});

test("an ordinary fragment is not treated as auth", async () => {
  const { flow, cleans } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  assert.deepEqual(flow.begin("", "#some-anchor"), { kind: "none" });
  assert.equal(cleans.length, 0);
});

test("missing, unknown, duplicate and malformed parameters are rejected safely", async () => {
  const cases = [
    "?type=signup",
    "?token_hash=h&type=not-a-type",
    "?token_hash=one&token_hash=two&type=signup",
    "?token_hash=%ZZ&type=signup",
    "?token_hash=h&type=signup&type=recovery",
    "?token_hash=h&type=signup&error=access_denied"
  ];
  for (const search of cases) {
    const { flow, calls, writes, cleans } = makeFlow({ ok: true, status: 200, body: OK_BODY });
    const link = flow.begin(search, "");
    assert.equal(link.kind, "invalid", search);
    assert.ok(["malformed", "error"].includes(link.reason), search);
    assert.equal(cleans.length, 1, search);
    assert.equal(calls.length, 0, search);
    assert.equal(writes.length, 0, search);
  }
});

test("a malformed parameter cannot throw", () => {
  assert.doesNotThrow(() => core.parseQuery("?token_hash=%E0%A4%A&type=signup"));
  assert.doesNotThrow(() => core.readAuthLink("?%ZZ=1", "#%ZZ"));
});

test("OAuth callback parameters are cleaned but not acted on", async () => {
  const { flow, calls } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  assert.deepEqual(flow.begin("?code=abc&state=def", ""), { kind: "invalid", reason: "malformed" });
  assert.equal(calls.length, 0);
});

// --- verifying --------------------------------------------------------------

test("signup verification sends exactly {type, token_hash}", async () => {
  const { flow, calls, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  flow.begin("?token_hash=hash-1&type=signup", "");
  const result = await flow.verify();
  assert.equal(result.ok, true);
  assert.equal(result.type, "signup");
  assert.deepEqual(calls, [
    { method: "POST", path: "/auth/v1/verify", body: { type: "signup", token_hash: "hash-1" } }
  ]);
  assert.deepEqual(writes, [{
    access_token: "access-token",
    refresh_token: "refresh-token",
    expires_at: 2000,
    email: "person@example.com"
  }]);
  assert.equal(flow.hasPending(), false, "the token is single-use in memory");
});

test("recovery verification writes a session and reports recovery", async () => {
  const { flow, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  flow.begin("?token_hash=r&type=recovery", "");
  const result = await flow.verify();
  assert.equal(result.ok, true);
  assert.equal(result.type, "recovery");
  assert.equal(writes.length, 1);
});

test("invite verification writes a session and reports invite", async () => {
  const { flow, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  flow.begin("?token_hash=i&type=invite", "");
  const result = await flow.verify();
  assert.equal(result.ok, true);
  assert.equal(result.type, "invite");
  assert.equal(writes.length, 1);
});

test("verify without a pending link sends nothing", async () => {
  const { flow, calls, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  assert.deepEqual(await flow.verify(), { ok: false, kind: "missing" });
  assert.equal(calls.length, 0);
  assert.equal(writes.length, 0);
});

test("expired or consumed token: 403, no session, token discarded", async () => {
  const { flow, writes } = makeFlow({ ok: false, status: 403, body: { error_code: "otp_expired" } });
  flow.begin("?token_hash=dead&type=signup", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "expired" });
  assert.equal(writes.length, 0);
  assert.equal(flow.hasPending(), false);
});

test("wrong token type: 400 is invalid, not expired", async () => {
  const { flow, writes } = makeFlow({ ok: false, status: 400, body: { msg: "Unsupported verification type" } });
  flow.begin("?token_hash=h&type=recovery", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "invalid" });
  assert.equal(writes.length, 0);
});

test("rate limiting keeps the link retryable", async () => {
  const { flow, writes } = makeFlow({ ok: false, status: 429, body: {} });
  flow.begin("?token_hash=h&type=signup", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "rate" });
  assert.equal(writes.length, 0);
  assert.equal(flow.hasPending(), true);
});

test("network failure is not reported as an expired link and keeps the token", async () => {
  const { flow, writes } = makeFlow(new TypeError("Failed to fetch"));
  flow.begin("?token_hash=h&type=signup", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "network" });
  assert.equal(writes.length, 0);
  assert.equal(flow.hasPending(), true);
});

test("a 5xx is a service error, not an expired link", async () => {
  const { flow, writes } = makeFlow({ ok: false, status: 503, body: {} });
  flow.begin("?token_hash=h&type=signup", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "server" });
  assert.equal(writes.length, 0);
  assert.equal(flow.hasPending(), true);
});

test("a 200 without both tokens is an unexpected response, never a session", async () => {
  for (const body of [null, {}, { access_token: "a" }, { refresh_token: "r" }]) {
    const { flow, writes } = makeFlow({ ok: true, status: 200, body });
    flow.begin("?token_hash=h&type=signup", "");
    assert.deepEqual(await flow.verify(), { ok: false, kind: "unexpected" });
    assert.equal(writes.length, 0);
  }
});

test("no failure path writes a session", async () => {
  for (const response of [
    { ok: false, status: 400, body: {} },
    { ok: false, status: 403, body: {} },
    { ok: false, status: 429, body: {} },
    { ok: false, status: 500, body: {} },
    { ok: true, status: 200, body: {} }
  ]) {
    const { flow, writes } = makeFlow(response);
    flow.begin("?token_hash=h&type=signup", "");
    await flow.verify();
    assert.equal(writes.length, 0);
  }
});

// --- mapping ----------------------------------------------------------------

test("session mapping falls back to expires_in and a token email", () => {
  const session = core.sessionFromAuthBody(
    { access_token: "a", refresh_token: "r", expires_in: 60, user: {} },
    1000,
    () => "from-token@example.com"
  );
  assert.deepEqual(session, {
    access_token: "a",
    refresh_token: "r",
    expires_at: 1060,
    email: "from-token@example.com"
  });
});

test("status classification is exact", () => {
  assert.equal(core.classifyVerifyFailure(null), "network");
  assert.equal(core.classifyVerifyFailure({ status: 403 }), "expired");
  assert.equal(core.classifyVerifyFailure({ status: 400 }), "invalid");
  assert.equal(core.classifyVerifyFailure({ status: 401 }), "invalid");
  assert.equal(core.classifyVerifyFailure({ status: 429 }), "rate");
  assert.equal(core.classifyVerifyFailure({ status: 500 }), "server");
  assert.equal(core.classifyVerifyFailure({ status: 200 }), "invalid");
});

test("every failure kind has a message and none mentions a token", () => {
  for (const kind of ["expired", "invalid", "legacy", "malformed", "error", "rate", "server", "network", "missing", "unexpected"]) {
    const message = core.authLinkMessage(kind);
    assert.equal(typeof message, "string");
    assert.ok(message.length > 10, kind);
    assert.ok(!/token_hash|access_token|refresh_token/i.test(message), kind);
  }
});

// --- Phase 5F-C regressions -------------------------------------------------

test("type=email is normalized to signup before verify", async () => {
  const { flow, calls, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  assert.deepEqual(flow.begin("?token_hash=h&type=email", ""), { kind: "ready", type: "signup" });
  const result = await flow.verify();
  assert.equal(result.ok, true);
  assert.deepEqual(calls[0].body, { type: "signup", token_hash: "h" });
  assert.equal(writes.length, 1);
});

test("prototype keys are not auth link types", () => {
  for (const type of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
    const link = core.readAuthLink(`?token_hash=h&type=${type}`, "");
    assert.equal(link.kind, "invalid", type);
    assert.equal(link.reason, "malformed", type);
  }
});

test("cancel before verify discards the token", async () => {
  const { flow, calls, writes } = makeFlow({ ok: true, status: 200, body: OK_BODY });
  flow.begin("?token_hash=h&type=signup", "");
  flow.cancel();
  assert.equal(flow.hasPending(), false);
  assert.deepEqual(await flow.verify(), { ok: false, kind: "missing" });
  assert.equal(calls.length, 0);
  assert.equal(writes.length, 0);
});

test("cancel during verification prevents the session write", async () => {
  const { flow, writes, resolve } = makeDeferredFlow();
  flow.begin("?token_hash=h&type=signup", "");
  const pending = flow.verify();
  flow.cancel();
  resolve({ ok: true, status: 200, body: OK_BODY });
  assert.deepEqual(await pending, { ok: false, kind: "cancelled" });
  assert.equal(writes.length, 0);
});

test("a second concurrent verification is refused", async () => {
  const { flow, calls, resolve } = makeDeferredFlow();
  flow.begin("?token_hash=h&type=signup", "");
  const first = flow.verify();
  assert.deepEqual(await flow.verify(), { ok: false, kind: "busy" });
  assert.equal(calls.length, 1);
  resolve({ ok: true, status: 200, body: OK_BODY });
  assert.equal((await first).ok, true);
});

test("query-only tokens are cleaned but never adopted", () => {
  const link = core.readAuthLink("?access_token=a&refresh_token=b", "");
  assert.equal(link.kind, "invalid");
  assert.equal(link.clean, true);
  assert.equal(core.removeAuthKeys("?access_token=a&refresh_token=b"), "");
});

test("removeAuthKeys preserves unrelated query parameters and fragments", () => {
  assert.equal(core.removeAuthKeys("?utm=1&token_hash=h&type=signup&x=2"), "utm=1&x=2");
  assert.equal(core.removeAuthKeys("#access_token=a&section"), "section");
  assert.equal(core.removeAuthKeys("#section"), "section");
});

test("fragment-only auth material is reported and cleaned", () => {
  assert.deepEqual(core.readAuthLink("", "#type=recovery"), { kind: "invalid", reason: "legacy", clean: true });
});

test("the auth guard invalidates a cancelled epoch", () => {
  const guard = core.createAuthGuard();
  const first = guard.begin();
  assert.equal(guard.current(first), true);
  guard.cancel();
  assert.equal(guard.current(first), false);
  const second = guard.begin();
  assert.equal(guard.current(second), true);
  assert.equal(guard.current(first), false);
});

test("password update uses the verified session, not a replaced shared session", async () => {
  const verifiedA = { access_token: "A", refresh_token: "RA", expires_at: 2000, email: "a@example.com" };
  // A different tab replaces the shared session after verification.
  let shared = verifiedA;
  shared = { access_token: "B", refresh_token: "RB", expires_at: 2000, email: "b@example.com" };
  const { deps, calls } = makePasswordDeps();
  const result = await core.updatePasswordForSession(verifiedA, "new-password", deps);
  assert.equal(result.ok, true);
  assert.equal(calls[0].token, "A");
  assert.equal(result.session.access_token, "A");
  assert.equal(shared.access_token, "B", "the test only proves the function ignored it");
});

test("recovery and invitation both update with the verified session", async () => {
  for (const type of ["recovery", "invite"]) {
    const verified = { access_token: type + "-token", refresh_token: "r", expires_at: 2000, email: "x@example.com" };
    const { deps, calls } = makePasswordDeps();
    const result = await core.updatePasswordForSession(verified, "new-password", deps);
    assert.equal(result.ok, true, type);
    assert.equal(calls[0].token, type + "-token", type);
  }
});

test("an expired verified session refreshes with its own refresh token", async () => {
  const verified = { access_token: "old", refresh_token: "R", expires_at: 0, email: "a@example.com" };
  const fresh = { access_token: "fresh", refresh_token: "R2", expires_at: 3000, email: "a@example.com" };
  let seen = null;
  const { deps, calls } = makePasswordDeps({
    isExpired: () => true,
    refresh: async (session) => { seen = session; return fresh; }
  });
  const result = await core.updatePasswordForSession(verified, "new-password", deps);
  assert.equal(result.ok, true);
  assert.equal(seen.refresh_token, "R");
  assert.equal(calls[0].token, "fresh");
  assert.equal(result.session.email, "a@example.com");
});

test("a refresh for a different identity is refused", async () => {
  const verified = { access_token: "old", refresh_token: "R", expires_at: 0, email: "a@example.com" };
  const { deps, calls } = makePasswordDeps({
    isExpired: () => true,
    refresh: async () => null
  });
  assert.deepEqual(await core.updatePasswordForSession(verified, "new-password", deps), { ok: false, kind: "expired" });
  assert.equal(calls.length, 0);
});

test("a 401 refreshes once and retries with the fresh verified session", async () => {
  const verified = { access_token: "old", refresh_token: "R", expires_at: 3000, email: "a@example.com" };
  const fresh = { access_token: "fresh", refresh_token: "R2", expires_at: 4000, email: "a@example.com" };
  let attempt = 0;
  const tokens = [];
  const { deps } = makePasswordDeps({
    request: async (method, path, body, token) => {
      tokens.push(token);
      attempt += 1;
      return attempt === 1 ? { ok: false, status: 401, body: {} } : { ok: true, status: 200, body: {} };
    },
    refresh: async () => fresh
  });
  const result = await core.updatePasswordForSession(verified, "new-password", deps);
  assert.equal(result.ok, true);
  assert.deepEqual(tokens, ["old", "fresh"]);
});

test("a network failure during the update is reported, not treated as a bad password", async () => {
  const verified = { access_token: "A", refresh_token: "R", expires_at: 3000, email: "a@example.com" };
  const { deps } = makePasswordDeps({ request: async () => { throw new TypeError("Failed to fetch"); } });
  assert.deepEqual(await core.updatePasswordForSession(verified, "new-password", deps), { ok: false, kind: "network", session: verified });
});

test("a retryable failure after a refresh returns the fresh session for the retry", async () => {
  const verified = { access_token: "old", refresh_token: "R", expires_at: 0, email: "a@example.com" };
  const fresh = { access_token: "fresh", refresh_token: "R2", expires_at: 3000, email: "a@example.com" };
  const { deps } = makePasswordDeps({
    isExpired: () => true,
    refresh: async () => fresh,
    request: async () => ({ ok: false, status: 422, body: { msg: "weak password" } })
  });
  const result = await core.updatePasswordForSession(verified, "short", deps);
  assert.equal(result.ok, false);
  assert.equal(result.kind, "failed");
  assert.equal(result.session.access_token, "fresh");
  assert.equal(result.session.refresh_token, "R2");
});

test("Back during verification: the late response is ignored and no session is written", async () => {
  const { flow, writes, resolve } = makeDeferredFlow();
  const guard = core.createAuthGuard();
  flow.begin("?token_hash=h&type=recovery", "");
  let screen = "link-recovery";
  const epoch = guard.begin();
  const pending = (async () => {
    const result = await flow.verify();
    if (!guard.current(epoch) || screen !== "link-recovery") return "ignored";
    return result;
  })();
  // The user presses Back while the request is in flight.
  guard.cancel();
  flow.cancel();
  screen = "signin";
  resolve({ ok: true, status: 200, body: OK_BODY });
  assert.equal(await pending, "ignored");
  assert.equal(writes.length, 0);
});

test("Back during password update: no app entry and no success message", async () => {
  const guard = core.createAuthGuard();
  const verified = { access_token: "A", refresh_token: "R", expires_at: 2000, email: "a@example.com" };
  let resolvePut = null;
  let screen = "setpassword";
  let entered = false;
  let toasted = false;
  const deps = {
    request: () => new Promise((resolve) => { resolvePut = resolve; }),
    refresh: async () => null,
    isExpired: () => false
  };
  const epoch = guard.begin();
  const pending = (async () => {
    const changed = await core.updatePasswordForSession(verified, "new-password", deps);
    if (!guard.current(epoch) || screen !== "setpassword") return "ignored";
    if (changed.ok) { entered = true; toasted = true; }
    return "applied";
  })();
  guard.cancel();
  screen = "signin";
  resolvePut({ ok: true, status: 200, body: {} });
  assert.equal(await pending, "ignored");
  assert.equal(entered, false);
  assert.equal(toasted, false);
});

// --- runner -----------------------------------------------------------------

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log("ok - " + name);
  } catch (error) {
    failed += 1;
    console.log("not ok - " + name);
    console.log("    " + (error && error.message ? error.message : String(error)));
  }
}
console.log(`\n${tests.length - failed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
