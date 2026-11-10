/** Opt-in development integration; no live data, provider writes or actual passwords. */
import { strict as assert } from "node:assert";
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { createSession, deleteUserSessions, type SessionData } from "./lib/auth";
import { hashPassword } from "./lib/password-auth";
import { pool } from "@workspace/db";

if (process.env.STREAMBOT_TEST_ADMIN_HTTP !== "true" || process.env.REPLIT_DEPLOYMENT) {
  throw new Error("Opt-in development-only test; production is forbidden.");
}
const pythonDir = path.resolve(import.meta.dirname, "../python");
const id = randomBytes(16).toString("hex");
const order = randomBytes(12).toString("hex");
const username = "http_" + id.slice(0, 12);
const email = username + "@example.test";
const password = randomBytes(20).toString("hex");
const nextPassword = randomBytes(20).toString("hex");
const profile = { id, username, email, passwordHash: await hashPassword(password), version: 1 };
const target = "http://localhost:8080";
const webTarget = "http://localhost:80";
const testIp = "192.0.2." + (1 + parseInt(id.slice(0, 2), 16) % 250);
const sessions: string[] = [];
let seeded = false;
function fixtureSql(action: string) {
  const result = spawnSync("python3", ["-c", `
import json,sys,time
from pathlib import Path
from streambot.store import Store,digest
store=Store('data/demo.sqlite3',Path('data/demo.key').read_bytes().strip())
profile,oid,action,sessions=json.loads(sys.argv[1]),sys.argv[2],sys.argv[3],json.loads(sys.argv[4])
owner='local:'+profile['id']
backup='http_test_backup:'+profile['id']
with store.connection() as db:
 if action=='setup':
  assert not db.execute("SELECT value FROM metadata WHERE key='web_local_owner'").fetchone(), 'Real local owner exists: do not change it'
  old=db.execute("SELECT value FROM metadata WHERE key='web_admin_owner'").fetchone()
  db.execute('INSERT INTO metadata VALUES(?,?)',(backup,json.dumps(old[0] if old else None)))
  db.execute("INSERT INTO metadata VALUES('web_local_owner',?)",(store.seal(profile),))
  db.execute("INSERT OR REPLACE INTO metadata VALUES('web_admin_owner',?)",(owner,))
  db.execute("INSERT INTO orders(id,token_hash,kind,telegram_id,plan_json,asset_json,amount_units,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
   (oid,oid+'test','trial',int(oid[:10],16),json.dumps({'id':'trial','name':'HTTP test trial','package_id':'275'}),json.dumps({'network':'none','decimals':0}),'0',int(time.time()),int(time.time())+3600,'review'))
 else:
  current=store.unseal(db.execute("SELECT value FROM metadata WHERE key='web_local_owner'").fetchone()[0])
  assert current['id']==profile['id'], 'Owner changed: do not overwrite it'
  previous=json.loads(db.execute("SELECT value FROM metadata WHERE key=?",(backup,)).fetchone()[0])
  db.execute("DELETE FROM orders WHERE id=? AND token_hash=?",(oid,oid+'test'))
  db.execute("DELETE FROM metadata WHERE key IN ('web_local_owner','web_admin_owner',?)",(backup,))
  if previous: db.execute("INSERT INTO metadata VALUES('web_admin_owner',?)",(previous,))
  for sid in sessions:
   actor=owner+':'+digest(sid)
   db.execute("DELETE FROM metadata WHERE key=?",('web_trial_recovery:'+digest(actor),))
  for row in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'web_owner_password_update:%'").fetchall():
   if store.unseal(row['value']).get('actor','').startswith(owner+':'):
    db.execute("DELETE FROM metadata WHERE key=?",(row['key'],))
`, JSON.stringify(profile), order, action, JSON.stringify(sessions)], { cwd: pythonDir, encoding: "utf8" });
  if (result.status !== 0) throw new Error("Demo fixture setup/cleanup refused; existing owner was not changed.");
}
function cookie(response: Response): string {
  const match = /(?:^|,\s*)sid=([a-f0-9]{64});/.exec(response.headers.get("set-cookie") ?? "");
  assert.ok(match, "Secure session cookie expected");
  sessions.push(match[1]); return match[1];
}
async function request(route: string, sid?: string, body?: unknown, method = "POST", origin = target) {
  return fetch(target + "/api" + route, {
    method: body === undefined ? "GET" : method, redirect: "manual",
    headers: { "X-Forwarded-For": testIp, ...(sid ? { Cookie: `sid=${sid}` } : {}),
      ...(body === undefined ? {} : { "Content-Type": "application/json", ...(origin ? { Origin: origin } : {}) }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
try {
  assert.equal((await fetch(webTarget + "/admin", { redirect: "manual" })).headers.get("location"), "/admin/");
  assert.equal((await request("/login")).headers.get("location"), "/admin/sign-in");
  assert.equal((await request("/callback")).headers.get("location"), "/admin/sign-in");
  assert.equal((await request("/admin/orders")).status, 401);
  const initial = await (await request("/auth/status")).json() as { configured: boolean };
  if (initial.configured) throw new Error("An actual local owner exists; test refuses to modify it.");
  const rejectedSetup = await request("/auth/setup", undefined, {
    username, email, password, setupCode: "not-the-real-setup-code-" + id,
  });
  assert.equal(rejectedSetup.status, 403);
  fixtureSql("setup"); seeded = true;
  assert.equal((await request("/auth/login", undefined, { identifier: username, password: "bad" })).status, 401);
  assert.equal((await request("/auth/login", undefined, { identifier: username, password }, "POST", "")).status, 403);
  const signed = await request("/auth/login", undefined, { identifier: username, password });
  assert.equal(signed.status, 200);
  const owner = cookie(signed);
  assert.equal((await request("/logout", owner)).status, 302);
  assert.equal((await request("/admin/orders", owner)).status, 200);
  assert.match(signed.headers.get("set-cookie")!, /HttpOnly/i);
  assert.match(signed.headers.get("set-cookie")!, /Secure/i);
  const second = cookie(await request("/auth/login", undefined, { identifier: email, password }));
  const old = await createSession({ user: { id, email }, access_token: "old-test-token" } as unknown as SessionData);
  sessions.push(old);
  assert.equal((await request("/admin/orders", old)).status, 401);
  for (const route of ["/auth/user", "/auth/account", "/admin/access", "/admin/overview",
    "/admin/status", "/admin/orders?status=queued&page=1", "/admin/orders/" + order]) {
    const response = await request(route, owner);
    assert.equal(response.status, 200, route);
    const text = await response.text();
    for (const value of ["passwordHash", "scrypt-v1", "token_hash", '"credentials"']) assert.equal(text.includes(value), false);
  }
  const draft = await (await request("/admin/orders/" + order + "/recovery", owner, {})).json() as { nonce: string };
  assert.ok(draft.nonce);
  assert.equal((await request("/admin/recovery/confirm", owner, {
    nonce: draft.nonce, attestation: false, cancel: true,
  })).status, 200);
  const changed = await request("/auth/account", owner, {
    username: "updated_" + id.slice(0, 12), email, currentPassword: password, newPassword: nextPassword,
  }, "PATCH");
  assert.equal(changed.status, 200);
  const rotated = cookie(changed);
  assert.equal((await request("/admin/orders", owner)).status, 401);
  assert.equal((await request("/admin/orders", second)).status, 401);
  assert.equal((await request("/auth/login", undefined, { identifier: email, password })).status, 401);
  assert.equal((await request("/admin/orders", rotated)).status, 200);
  const loginAgain = await request("/auth/login", undefined, { identifier: email, password: nextPassword });
  assert.equal(loginAgain.status, 200);
  const last = cookie(loginAgain);
  assert.equal((await request("/auth/logout", last, {})).status, 200);
  assert.equal((await request("/admin/orders", last)).status, 401);
  assert.equal((await request("/auth/setup", undefined, { username, email, password, setupCode: "wrong".repeat(8) })).status, 409);
  assert.equal((await fetch(target + "/api/_admin/auth/credentials")).status, 404);
  process.stdout.write("Password HTTP integration passed: login, secure cookie, no OIDC, owner protection, recovery cancel, account/password changes, session rotation/revocation and logout.\n");
} finally {
  await deleteUserSessions(id);
  if (seeded) fixtureSql("cleanup");
  await pool.end();
}
