// Behavioural tests for the authentication UI helpers embedded in app/static/index.html.
//
// The helpers are deliberately DOM-free: the page passes real inputs/buttons at runtime, and this
// harness passes small fakes. Run with: node tests/js/auth_ui_test.mjs
//
// No framework: a failing assertion prints the case and exits non-zero.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(join(here, "..", "..", "app", "static", "index.html"), "utf8");
const startMarker = "/* ---------- auth UI helpers";
const endMarker = "/* ---------- end auth UI helpers";
const start = page.indexOf(startMarker);
const end = page.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "the auth UI helpers block is missing from index.html");

const block = page.slice(start, end);
const core = new Function(
  block +
    "\nreturn { authLinkTypeFor, authSubmitLabel, authSubmitBusyLabel, authResendLabel, applyPasswordVisibility, resetPasswordVisibility, setAuthBusy };"
)();

const tests = [];
function test(name, fn) {
  tests.push([name, fn]);
}

function fakeInput(value = "secret") {
  return { type: "password", value };
}

function fakeButton(label = "Sign in") {
  const attrs = {};
  return {
    disabled: false,
    textContent: label,
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
    removeAttribute(name) { delete attrs[name]; },
    hasAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name); }
  };
}

test("show/hide changes type, label and pressed state without touching the value", () => {
  const input = fakeInput("secret-one");
  const button = fakeButton();
  core.applyPasswordVisibility(input, button, true, "Show password", "Hide password");
  assert.equal(input.type, "text");
  assert.equal(input.value, "secret-one");
  assert.equal(button.getAttribute("aria-pressed"), "true");
  assert.equal(button.getAttribute("aria-label"), "Hide password");

  core.applyPasswordVisibility(input, button, false, "Show password", "Hide password");
  assert.equal(input.type, "password");
  assert.equal(input.value, "secret-one");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(button.getAttribute("aria-label"), "Show password");
});

test("the two password fields toggle independently", () => {
  const input1 = fakeInput("first");
  const input2 = fakeInput("second");
  const button1 = fakeButton();
  const button2 = fakeButton();
  core.applyPasswordVisibility(input1, button1, true, "Show password", "Hide password");
  assert.equal(input1.type, "text");
  assert.equal(input2.type, "password");
  assert.equal(button1.getAttribute("aria-pressed"), "true");
  assert.equal(button2.getAttribute("aria-pressed"), null);
  assert.equal(input2.value, "second");
});

test("reset returns a field to hidden and restores its label", () => {
  const input = fakeInput("secret");
  const button = fakeButton();
  core.applyPasswordVisibility(input, button, true, "Show password", "Hide password");
  core.resetPasswordVisibility(input, button, "Show password");
  assert.equal(input.type, "password");
  assert.equal(input.value, "secret");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(button.getAttribute("aria-label"), "Show password");
});

test("submit labels match every authentication view", () => {
  assert.equal(core.authSubmitLabel("signin"), "Sign in");
  assert.equal(core.authSubmitLabel("signup"), "Create account");
  assert.equal(core.authSubmitLabel("forgot"), "Send reset link");
  assert.equal(core.authSubmitLabel("setpassword"), "Save password");
  assert.equal(core.authSubmitLabel("link-signup"), "Confirm email");
  assert.equal(core.authSubmitLabel("link-recovery"), "Continue");
  assert.equal(core.authSubmitLabel("link-invite"), "Accept invitation");
  assert.equal(core.authSubmitBusyLabel("signin"), "Signing in\u2026");
  assert.equal(core.authSubmitBusyLabel("signup"), "Creating account\u2026");
  assert.equal(core.authSubmitBusyLabel("forgot"), "Sending reset link\u2026");
  assert.equal(core.authSubmitBusyLabel("setpassword"), "Saving password\u2026");
  assert.equal(core.authSubmitBusyLabel("link-signup"), "Verifying\u2026");
  assert.equal(core.authResendLabel("confirmation"), "Resend confirmation email");
  assert.equal(core.authResendLabel("expired"), "Send a new confirmation email");
});

test("busy state sets and clears aria-disabled, aria-busy and the label", () => {
  const button = fakeButton("Sign in");
  core.setAuthBusy(button, true, "Signing in\u2026");
  assert.equal(button.getAttribute("aria-disabled"), "true");
  assert.equal(button.getAttribute("aria-busy"), "true");
  assert.equal(button.disabled, false, "the button stays focusable while busy");
  assert.equal(button.textContent, "Signing in\u2026");

  core.setAuthBusy(button, false, "Sign in");
  assert.equal(button.hasAttribute("aria-disabled"), false);
  assert.equal(button.hasAttribute("aria-busy"), false);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Sign in");
});

test("busy state without a label leaves the text alone", () => {
  const button = fakeButton("Confirm email");
  core.setAuthBusy(button, true, null);
  assert.equal(button.getAttribute("aria-disabled"), "true");
  assert.equal(button.getAttribute("aria-busy"), "true");
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Confirm email");
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
