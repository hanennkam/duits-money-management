// Behavioural tests for the Google OAuth PKCE core embedded in app/static/index.html.
//
// The page is one vanilla-JS file, so the OAuth core is DOM-free and dependency-injected. This harness
// extracts the auth-link core (for parseQuery/sessionFromAuthBody) and the OAuth core, then drives the
// real functions under Node with deterministic crypto, storage, navigation and request doubles.
//
// Run with: node tests/js/oauth_pkce_test.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { webcrypto } from "node:crypto";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(join(here, "..", "..", "app", "static", "index.html"), "utf8");

function block(startMarker, endMarker) {
  const start = page.indexOf(startMarker);
  const end = page.indexOf(endMarker);
  assert.ok(start >= 0 && end > start, `missing block: ${startMarker}`);
  return page.slice(start, end);
}

const linkBlock = block("/* ---------- auth link core", "/* ---------- end auth link core");
const oauthBlock = block("/* ---------- oauth pkce core", "/* ---------- end oauth pkce core");
const core = new Function(
  linkBlock +
    "\n" +
    oauthBlock +
    "\nreturn { createOAuthFlow, oauthAuthorizeUrl, oauthIsNewUser, oauthMessage, base64UrlFromBytes, sha256Base64Url, removeAuthKeys };"
)();

const subtle = webcrypto.subtle;
const FLOW_KEY = "duits.auth.oauth";

function makeStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem(key) { return map.has(key) ? map.get(key) : null; },
    setItem(key, value) { map.set(key, String(value)); },
    removeItem(key) { map.delete(key); },
    has(key) { return map.has(key); },
    raw(key) { return map.get(key); }
  };
}

function makeFlow(overrides = {}) {
  const storage = overrides.storage || makeStorage();
  const navigated = [];
  const cleaned = [];
  const calls = [];
  let now = overrides.now || 1000;
  let randomCall = 0;
  const deps = {
    request: async (method, path, body) => {
      calls.push({ method, path, body });
      return overrides.response || { ok: true, status: 200, body: {} };
    },
    storage,
    now: () => 1000,
    nowMs: () => now,
    randomBytes: (length) => {
      randomCall += 1;
      return new Uint8Array(length).fill(randomCall);
    },
    subtle,
    isAvailable: () => true,
    baseUrl: "https://tddigsmukmhkjrwiqdec.supabase.co",
    redirectTo: "https://staging.example/",
    navigate: (url) => navigated.push(url),
    cleanUrl: () => cleaned.push(true),
    emailFromToken: () => "",
    ...overrides
  };
  const flow = core.createOAuthFlow(deps);
  return {
    flow, storage, navigated, cleaned, calls,
    advance: (ms) => { now += ms; },
    setNow: (value) => { now = value; }
  };
}

function seedRecord(storage, verifier = "verifier-1", created = 1000) {
  storage.setItem(FLOW_KEY, JSON.stringify({ verifier, created, redirectTo: "https://staging.example/", flowId: "flow-1" }));
}

const OK_BODY = {
  access_token: "access-token",
  refresh_token: "refresh-token",
  expires_at: 2000,
  user: { email: "person@example.com", created_at: new Date(1000 * 1000).toISOString(), user_metadata: {} }
};

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

// --- PKCE and authorize URL -------------------------------------------------

test("authorize URL uses Google, basic scopes, S256 and the exact redirect", () => {
  const url = core.oauthAuthorizeUrl(
    "https://tddigsmukmhkjrwiqdec.supabase.co/",
    "https://staging.example/",
    "challenge-1"
  );
  assert.match(url, /^https:\/\/tddigsmukmhkjrwiqdec\.supabase\.co\/auth\/v1\/authorize\?/);
  assert.match(url, /provider=google/);
  assert.match(url, /redirect_to=https%3A%2F%2Fstaging\.example%2F/);
  assert.match(url, /scopes=openid/);
  assert.doesNotMatch(url, /scopes=email/);
  assert.match(url, /code_challenge=challenge-1/);
  assert.match(url, /code_challenge_method=s256/);
  assert.doesNotMatch(url, /plain/);
  assert.doesNotMatch(url, /client_secret|access_type|prompt=/);
});

test("S256 challenge matches the RFC 7636 example", async () => {
  const challenge = await core.sha256Base64Url(
    "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    subtle
  );
  assert.equal(challenge, "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});

test("verifier is base64url with no padding", () => {
  const encoded = core.base64UrlFromBytes(new Uint8Array([251, 255, 191]));
  assert.equal(encoded, "-_-_");
});

// --- initiation -------------------------------------------------------------

test("start stores a single-use flow record and navigates to authorize", async () => {
  const { flow, storage, navigated } = makeFlow();
  const started = await flow.start();
  assert.equal(started.ok, true);
  assert.equal(navigated.length, 1);
  assert.match(navigated[0], /provider=google/);
  assert.match(navigated[0], /code_challenge_method=s256/);
  const record = JSON.parse(storage.raw(FLOW_KEY));
  assert.equal(typeof record.verifier, "string");
  assert.ok(record.verifier.length >= 43);
  assert.equal(record.created, 1000);
  assert.equal(typeof record.flowId, "string");
  assert.equal(record.code, undefined);
  assert.equal(record.access_token, undefined);
  assert.equal(record.refresh_token, undefined);
});

test("repeated start immediately is busy and does not navigate twice", async () => {
  const { flow, storage, navigated } = makeFlow();
  assert.equal((await flow.start()).ok, true);
  const second = await flow.start();
  assert.deepEqual(second, { ok: false, kind: "busy" });
  assert.equal(navigated.length, 1);
  assert.ok(storage.has(FLOW_KEY));
});

test("start refuses when the provider is unavailable or insecure", async () => {
  const { flow, storage, navigated } = makeFlow({ isAvailable: () => false });
  assert.deepEqual(await flow.start(), { ok: false, kind: "unavailable" });
  assert.equal(navigated.length, 0);
  assert.equal(storage.has(FLOW_KEY), false);
});

test("start reports a storage failure without navigating", async () => {
  const storage = makeStorage();
  storage.setItem = () => { throw new Error("quota"); };
  const { flow, navigated } = makeFlow({ storage });
  assert.deepEqual(await flow.start(), { ok: false, kind: "storage" });
  assert.equal(navigated.length, 0);
});

// --- callback parsing -------------------------------------------------------

test("valid callback cleans the URL, removes the record and holds the code", async () => {
  const { flow, storage, cleaned, calls } = makeFlow();
  seedRecord(storage);
  const link = flow.begin("?code=code-1&state=server-owned", "");
  assert.deepEqual(link, { kind: "ready" });
  assert.equal(cleaned.length, 1);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(calls.length, 0, "begin must not exchange anything");
  assert.equal(flow.hasPending(), true);
});

test("a second callback is missing and cannot replay the code", async () => {
  const { flow, storage, calls } = makeFlow();
  seedRecord(storage);
  assert.deepEqual(flow.begin("?code=code-1", ""), { kind: "ready" });
  assert.deepEqual(flow.begin("?code=code-1", ""), { kind: "missing" });
  assert.equal(calls.length, 0);
});

test("code with no stored flow is rejected without an exchange", async () => {
  const { flow, storage, cleaned, calls } = makeFlow();
  assert.deepEqual(flow.begin("?code=code-1", ""), { kind: "missing" });
  assert.equal(cleaned.length, 1);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(calls.length, 0);
});

test("an expired flow is rejected without an exchange", async () => {
  const { flow, storage, advance, calls } = makeFlow();
  seedRecord(storage);
  advance(10 * 60 * 1000 + 1);
  assert.deepEqual(flow.begin("?code=code-1", ""), { kind: "missing" });
  assert.equal(calls.length, 0);
});

test("provider cancellation is mapped and removes the flow", async () => {
  const { flow, storage, cleaned, calls } = makeFlow();
  seedRecord(storage);
  assert.deepEqual(flow.begin("?error=access_denied&error_description=nope", ""), { kind: "cancelled" });
  assert.equal(cleaned.length, 1);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(calls.length, 0);
});

test("signup_disabled is distinguished from genuine cancellation", async () => {
  const { flow, storage, cleaned, calls } = makeFlow();
  seedRecord(storage);
  assert.deepEqual(
    flow.begin("?error=access_denied&error_code=signup_disabled&error_description=nope", ""),
    { kind: "signup_disabled" }
  );
  assert.equal(cleaned.length, 1);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(calls.length, 0);
});

test("an unknown provider error is generic and removes the flow", async () => {
  const { flow, storage, cleaned, calls } = makeFlow();
  seedRecord(storage);
  assert.deepEqual(
    flow.begin("?error=server_error&error_code=server_error&error_description=no", ""),
    { kind: "error" }
  );
  assert.equal(cleaned.length, 1);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(calls.length, 0);
});

test("error_code and Supabase sb marker are stripped; unrelated params survive", () => {
  assert.equal(
    core.removeAuthKeys("?code=c&error=access_denied&error_code=signup_disabled&sb=&utm=1"),
    "utm=1"
  );
  assert.equal(
    core.removeAuthKeys("#error=access_denied&error_code=signup_disabled&sb=&section=2"),
    "section=2"
  );
});

test("a malformed duplicate code is rejected", async () => {
  const { flow, storage, cleaned, calls } = makeFlow();
  seedRecord(storage);
  assert.deepEqual(flow.begin("?code=one&code=two", ""), { kind: "malformed" });
  assert.equal(cleaned.length, 1);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(calls.length, 0);
});

test("provider error without a stored flow is left to the email-link path", () => {
  const { flow, cleaned, calls } = makeFlow();
  assert.deepEqual(flow.begin("?error=access_denied&error_description=nope", ""), { kind: "none" });
  assert.equal(cleaned.length, 0);
  assert.equal(calls.length, 0);
});

test("cancel clears the pending callback and the stored record", () => {
  const { flow, storage, cleaned } = makeFlow();
  seedRecord(storage);
  assert.deepEqual(flow.begin("?code=code-1", ""), { kind: "ready" });
  assert.equal(flow.hasPending(), true);
  flow.cancel();
  assert.equal(flow.hasPending(), false);
  assert.equal(storage.has(FLOW_KEY), false);
  assert.equal(cleaned.length, 1);
});

// --- exchange ---------------------------------------------------------------

test("verify sends exactly auth_code and code_verifier to the PKCE endpoint", async () => {
  const { flow, storage, calls } = makeFlow({
    response: { ok: true, status: 200, body: OK_BODY }
  });
  seedRecord(storage, "verifier-1");
  flow.begin("?code=code-1", "");
  const result = await flow.verify();
  assert.equal(result.ok, true);
  assert.equal(result.session.access_token, "access-token");
  assert.equal(result.session.refresh_token, "refresh-token");
  assert.equal(result.isNewUser, true);
  assert.deepEqual(calls, [{
    method: "POST",
    path: "/auth/v1/token?grant_type=pkce",
    body: { auth_code: "code-1", code_verifier: "verifier-1" }
  }]);
});

test("verify without a pending callback does nothing", async () => {
  const { flow, calls } = makeFlow();
  assert.deepEqual(await flow.verify(), { ok: false, kind: "missing" });
  assert.equal(calls.length, 0);
});

test("a network failure is reported without a session", async () => {
  const { flow, storage } = makeFlow({
    request: async () => { throw new TypeError("Failed to fetch"); }
  });
  seedRecord(storage);
  flow.begin("?code=code-1", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "network" });
});

test("a rejected exchange is classified and never maps a session", async () => {
  const { flow, storage } = makeFlow({
    response: { ok: false, status: 400, body: {} }
  });
  seedRecord(storage);
  flow.begin("?code=code-1", "");
  assert.deepEqual(await flow.verify(), { ok: false, kind: "invalid" });
});

test("verify is single-use after a successful exchange", async () => {
  const { flow, storage, calls } = makeFlow({ response: { ok: true, status: 200, body: OK_BODY } });
  seedRecord(storage);
  flow.begin("?code=code-1", "");
  assert.equal((await flow.verify()).ok, true);
  assert.deepEqual(await flow.verify(), { ok: false, kind: "missing" });
  assert.equal(calls.length, 1);
});

// --- onboarding identity ----------------------------------------------------

test("new Google user is routed to onboarding; completed user is not", () => {
  const now = Date.parse("2026-11-10T00:00:00Z");
  assert.equal(core.oauthIsNewUser({
    created_at: "2026-11-10T00:00:00Z",
    user_metadata: {}
  }, now), true);
  assert.equal(core.oauthIsNewUser({
    created_at: "2026-11-10T00:00:00Z",
    user_metadata: { onboarding_version: 1, onboarding_completed: false }
  }, now), true);
  assert.equal(core.oauthIsNewUser({
    created_at: "2026-11-10T00:00:00Z",
    user_metadata: { onboarding_version: 1, onboarding_completed: true }
  }, now), false);
  assert.equal(core.oauthIsNewUser({
    created_at: "2026-01-01T00:00:00Z",
    user_metadata: {}
  }, now), false);
});

test("oauth errors are user-facing and never include codes or tokens", () => {
  for (const kind of ["cancelled", "signup_disabled", "missing", "malformed", "invalid", "busy", "unavailable", "insecure", "storage", "rate", "server", "network", "failed", "unexpected"]) {
    const message = core.oauthMessage(kind);
    assert.equal(typeof message, "string");
    assert.ok(message.length > 0);
    assert.doesNotMatch(message, /access_token|refresh_token|code_verifier|authorization code/i);
  }
});

// --- runner -----------------------------------------------------------------

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`not ok - ${name}`);
    console.error(error && error.stack ? error.stack : error);
  }
}
console.log(`\n${tests.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
