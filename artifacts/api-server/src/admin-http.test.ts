/** Opt-in development integration check. Fixtures never touch production. */
import { strict as assert } from "node:assert";
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { createSession, deleteSession } from "./lib/auth";
import { ownerEmails } from "./lib/admin-auth";
import { pool } from "@workspace/db";

if (process.env.STREAMBOT_TEST_ADMIN_HTTP !== "true" || process.env.REPLIT_DEPLOYMENT) {
  throw new Error("Opt-in development-only test; production is forbidden.");
}
const pythonDir = path.resolve(import.meta.dirname, "../python");
const subject = "admin_http_" + randomBytes(8).toString("hex");
const fixture = randomBytes(12).toString("hex");
const target = "http://localhost:80";
function fixtureSql(action: string) {
  const result = spawnSync("python3", ["-c", `
import sqlite3,json,sys,time
db=sqlite3.connect('data/demo.sqlite3')
subject,oid,action=sys.argv[1:]
owner='replit:'+subject
with db:
 if action=='setup':
  assert not db.execute("SELECT value FROM metadata WHERE key='web_admin_owner'").fetchone(), 'Existing demo owner: do not change it'
  db.execute("INSERT INTO metadata VALUES('web_admin_owner',?)",(owner,))
  db.execute("INSERT INTO orders(id,token_hash,kind,telegram_id,plan_json,asset_json,amount_units,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
   (oid,oid+'test','trial',None,json.dumps({'id':'trial','name':'HTTP test trial','package_id':'275'}),json.dumps({'network':'none','decimals':0}),'0',int(time.time()),int(time.time())+3600,'review'))
  db.execute("UPDATE orders SET telegram_id=? WHERE id=?",(int(oid[:10],16),oid))
 else:
  db.execute("DELETE FROM orders WHERE id=? AND token_hash=?",(oid,oid+'test'))
  db.execute("DELETE FROM metadata WHERE key='web_admin_owner' AND value=?",(owner,))
`, subject, fixture, action], { cwd: pythonDir, encoding: "utf8" });
  if (result.status !== 0) throw new Error("Isolated demo fixture setup/cleanup failed; no existing owner was changed.");
}
const sessions: string[] = [];
const email = ownerEmails()[0];
if (!email) throw new Error("Configure owner allowlist before the development check.");
async function session(id: string, address: string) {
  const sid = await createSession({
    user: { id, email: address, firstName: "Integration", lastName: "Fixture", profileImageUrl: null },
    access_token: "isolated-test-not-an-oidc-token", expires_at: Math.floor(Date.now()/1000)+300,
  });
  sessions.push(sid); return sid;
}
async function request(route: string, sid?: string, body?: unknown, origin = target.replace(":80", "")) {
  return fetch(target + "/api/admin" + route, {
    method: body === undefined ? "GET" : "POST", redirect: "manual",
    headers: { ...(sid ? { Cookie: `sid=${sid}` } : {}),
      ...(body === undefined ? {} : { "Content-Type": "application/json", ...(origin ? { Origin: origin } : {}) }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
let seeded = false;
try {
  const canonical = await fetch(target + "/admin", { redirect: "manual" });
  assert.equal(canonical.status, 308);
  assert.equal(canonical.headers.get("location"), "/admin/");
  assert.equal((await fetch(target + "/admin/")).status, 200);
  const login = await fetch(target + "/api/login?returnTo=/admin", { redirect: "manual" });
  assert.equal(login.status, 302);
  assert.match(login.headers.get("set-cookie") ?? "", /return_to=%2Fadmin%2F;/);
  const callback = new URL(new URL(login.headers.get("location")!).searchParams.get("redirect_uri")!);
  assert.equal(callback.pathname, "/api/callback");
  assert.equal((await request("/orders")).status, 401);
  const visitor = await session(subject + "_visitor", "not-allowed@example.test");
  assert.equal((await request("/orders", visitor)).status, 403);
  fixtureSql("setup"); seeded = true;
  const owner = await session(subject, email);
  const sameEmailOtherIdentity = await session(subject + "_other", email);
  assert.equal((await request("/orders", sameEmailOtherIdentity)).status, 403);
  const access = await (await request("/access", owner)).json() as { authorized: boolean };
  assert.equal(access.authorized, true);
  for (const route of ["/overview", "/status", "/orders?status=queued&page=1", "/orders?kind=trial&q=" + fixture, "/orders/" + fixture]) {
    const response = await request(route, owner);
    assert.equal(response.status, 200, route);
    assert.equal(response.headers.get("cache-control"), "no-store");
    const text = await response.text();
    assert.equal(text.includes("token_hash"), false);
    assert.equal(text.includes('"credentials"'), false);
  }
  const route = "/orders/" + fixture + "/recovery";
  assert.equal((await request(route, owner, {}, "")).status, 403);
  assert.equal((await request(route, owner, {}, "https://attacker.invalid")).status, 403);
  const preview = await request(route, owner, {});
  assert.equal(preview.status, 200);
  const draft = await preview.json() as { nonce: string };
  assert.equal((await request("/recovery/confirm", owner, {
    nonce: draft.nonce, attestation: false, cancel: false,
  })).status, 400);
  assert.equal((await request("/recovery/confirm", owner, {
    nonce: draft.nonce, attestation: false, cancel: true,
  })).status, 200);
  const logout = await fetch(target + "/api/logout?returnTo=/admin", {
    redirect: "manual", headers: { Cookie: `sid=${owner}` },
  });
  assert.equal(logout.status, 302);
  const afterLogout = new URL(new URL(logout.headers.get("location")!).searchParams.get("post_logout_redirect_uri")!);
  assert.equal(afterLogout.pathname, "/admin/");
  assert.equal((await request("/orders", owner)).status, 401);
  // The bridge's externally exposed namespace remains unreachable even with a session.
  assert.equal((await fetch(target + "/api/_admin/overview", {
    headers: { Cookie: `sid=${visitor}`, "X-Streamline-Actor": "forged" },
  })).status, 404);
  process.stdout.write("Admin HTTP integration passed: authorization, identity binding, filters, CSRF, preview/cancel and revoked session.\n");
} finally {
  for (const sid of sessions) await deleteSession(sid);
  if (seeded) fixtureSql("cleanup");
  await pool.end();
}
