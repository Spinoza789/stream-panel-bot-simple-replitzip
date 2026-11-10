import { strict as assert } from "node:assert";
import { test } from "node:test";
import { allowedEmail, bootstrapMatches, ownerEmails } from "./admin-auth";
import { hashPassword, verifyPassword } from "./password-auth";
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
test("passwords have unique salts and reject wrong or malformed credentials", async () => {
  const one = await hashPassword("test-only-password-123");
  const two = await hashPassword("test-only-password-123");
  assert.notEqual(one, two);
  assert.equal(one.includes("test-only-password"), false);
  assert.equal(await verifyPassword("test-only-password-123", one), true);
  assert.equal(await verifyPassword("incorrect-password-123", one), false);
  assert.equal(await verifyPassword("test-only-password-123", ""), false);
});
