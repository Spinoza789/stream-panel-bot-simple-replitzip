import { test } from "node:test";
import { strict as assert } from "node:assert";
import { canonicalBasePath } from "../src/base-path";

test("browser login and logout retain artifact routing's trailing slash", () => {
  assert.equal(canonicalBasePath("/admin/"), "/admin/");
  assert.equal(canonicalBasePath("/admin"), "/admin/");
  assert.equal(canonicalBasePath("/"), "/");
});
