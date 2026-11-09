import { strict as assert } from "node:assert";
import { test } from "node:test";
import { allowedEmail, bootstrapMatches, ownerEmails } from "./admin-auth";
import { safeReturnTo } from "../routes/auth";
test("owner email is explicit, normalized and fail-closed", () => {
  assert.equal(allowedEmail("Owner@Example.com", ["owner@example.com"]), true);
  assert.equal(allowedEmail("visitor@example.com", ["owner@example.com"]), false);
  assert.equal(allowedEmail(null, ["owner@example.com"]), false);
  assert.equal(allowedEmail("owner@example.com", []), false);
  const saved = process.env.STREAMBOT_WEB_ADMIN_EMAILS;
  delete process.env.STREAMBOT_WEB_ADMIN_EMAILS;
  try { assert.deepEqual(ownerEmails(), []); }
  finally { if (saved !== undefined) process.env.STREAMBOT_WEB_ADMIN_EMAILS = saved; }
});
test("owner workspace proof requires configured long secret and exact match", () => {
  const saved = process.env.STREAMBOT_WEB_BOOTSTRAP_CODE;
  try {
    delete process.env.STREAMBOT_WEB_BOOTSTRAP_CODE;
    assert.equal(bootstrapMatches("x".repeat(32)), false);
    process.env.STREAMBOT_WEB_BOOTSTRAP_CODE = "test-only-code-never-used-live";
    assert.equal(bootstrapMatches("test-only-code-never-used-live"), true);
    assert.equal(bootstrapMatches("another-long-but-wrong-code"), false);
    assert.equal(bootstrapMatches({ code: "test-only-code-never-used-live" }), false);
  } finally {
    if (saved === undefined) delete process.env.STREAMBOT_WEB_BOOTSTRAP_CODE;
    else process.env.STREAMBOT_WEB_BOOTSTRAP_CODE = saved;
  }
});
test("login redirects cannot escape the admin website", () => {
  for (const value of ["https://evil.example", "//evil.example", "/\\evil.example", "/admin/../../", "/admin/%5cevil", null]) {
    assert.equal(safeReturnTo(value), "/admin/");
  }
  assert.equal(safeReturnTo("/admin/orders"), "/admin/orders");
});
