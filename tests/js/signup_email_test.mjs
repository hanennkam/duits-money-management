// Behavioural tests for the signup email validator embedded in app/static/index.html.
//
// The validator is deliberately DOM-free so it can be extracted and driven under Node. The page's
// submitAuth() calls the same function before it reaches the Supabase signup request.
//
// Run with: node tests/js/signup_email_test.mjs
//
// No framework: a failing assertion prints the case and exits non-zero.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(join(here, "..", "..", "app", "static", "index.html"), "utf8");
const startMarker = "/* ---------- signup email validation";
const endMarker = "/* ---------- end signup email validation";
const start = page.indexOf(startMarker);
const end = page.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "the signup email validation block is missing from index.html");

const block = page.slice(start, end);
const core = new Function(block + "\nreturn { isValidSignupEmail };")();

const tests = [];
function test(name, fn) {
  tests.push([name, fn]);
}

function valid(email) {
  assert.equal(core.isValidSignupEmail(email), true, `expected valid: ${email}`);
}

function invalid(email) {
  assert.equal(core.isValidSignupEmail(email), false, `expected invalid: ${JSON.stringify(email)}`);
}

test("standard valid addresses pass", () => {
  valid("person@example.com");
  valid("suhaib@gmail.com");
  valid("person.name@example.co.uk");
});

test("addresses without @ are rejected", () => {
  invalid("person.example.com");
  invalid("personexample.com");
});

test("addresses without a domain suffix are rejected", () => {
  invalid("person@example");
  invalid("person@localhost");
});

test("an empty email is rejected", () => {
  invalid("");
  invalid("   ");
});

test("malformed surrounding whitespace and multiple @ are rejected", () => {
  invalid(" person@example.com");
  invalid("person@example.com ");
  invalid("person@@example.com");
  invalid("@example.com");
  invalid("person@.com");
  invalid("person@example.");
});

test("the extracted validator uses the corrected single-backslash pattern", () => {
  assert.equal(typeof core.isValidSignupEmail, "function");
  assert.ok(block.includes("/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/"), "the corrected pattern is missing");
  assert.ok(!block.includes("/^[^\\\\s@]+@[^\\\\s@]+\\\\.[^\\\\s@]+$/"), "the old double-escaped pattern is back");
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
