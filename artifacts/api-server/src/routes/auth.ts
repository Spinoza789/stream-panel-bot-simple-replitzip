import { randomBytes } from "node:crypto";
import { Router, type Request, type Response, type IRouter } from "express";
import {
  GetCurrentAuthUserResponse, GetPasswordAccountResponse, GetPasswordAuthStatusResponse,
  PasswordLoginBody, SetupPasswordOwnerBody, UpdatePasswordAccountBody,
} from "@workspace/api-zod";
import { clearSession, createSession, deleteUserSessions, getSessionId, SESSION_COOKIE, SESSION_TTL } from "../lib/auth";
import { allowedEmail, authConfigured, bootstrapMatches, ownerEmails, requireOwner, sessionActor } from "../lib/admin-auth";
import { allowPasswordAttempt, hashPassword, passwordProfile, passwordStatus, publicUser,
  serviceActor, verifyPassword, type PasswordProfile } from "../lib/password-auth";
import { adminRequest } from "../lib/python-bridge";
import { sameOriginJson } from "../middlewares/same-origin";

const router: IRouter = Router();
router.use((_req, res, next) => { res.set("Cache-Control", "no-store"); next(); });
router.use(sameOriginJson);
function setupAvailable() {
  const size = process.env.STREAMBOT_WEB_BOOTSTRAP_CODE?.length ?? 0;
  return size >= 20 && size <= 200 && ownerEmails().length > 0 && authConfigured();
}
async function newSession(req: Request, res: Response, profile: PasswordProfile) {
  await clearSession(res, getSessionId(req));
  const sid = await createSession({ kind: "password-v1", credentialVersion: profile.version,
    user: publicUser(profile) });
  res.cookie(SESSION_COOKIE, sid, {
    httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: SESSION_TTL,
  });
}
async function attempt(req: Request, res: Response, kind: "login" | "setup" | "update", identifier: string) {
  if (!await allowPasswordAttempt(kind, req.ip ?? "unknown", identifier)) {
    res.set("Retry-After", "900").status(429).json({ error: "Too many attempts. Try again in 15 minutes." });
    return false;
  }
  return true;
}
router.get("/auth/user", (req, res) => {
  res.json(GetCurrentAuthUserResponse.parse({ user: req.isAuthenticated() ? req.user : null }));
});
router.get("/auth/status", async (_req, res) => {
  res.json(GetPasswordAuthStatusResponse.parse({
    configured: await passwordStatus(), setupAvailable: setupAvailable(),
  }));
});
router.post("/auth/login", async (req, res) => {
  const parsed = PasswordLoginBody.safeParse(req.body);
  if (!parsed.success) { res.status(400).json({ error: "Enter your username or email and password." }); return; }
  const { password } = parsed.data;
  const identifier = parsed.data.identifier.trim().toLowerCase();
  if (!await attempt(req, res, "login", identifier)) return;
  const profile = await passwordProfile();
  const matchesPassword = await verifyPassword(password, profile?.passwordHash ?? "");
  if (!profile || !matchesPassword || ![profile.username.toLowerCase(), profile.email.toLowerCase()].includes(identifier)) {
    res.status(401).json({ error: "Username/email or password is incorrect." }); return;
  }
  await newSession(req, res, profile);
  res.json(GetCurrentAuthUserResponse.parse({ user: publicUser(profile) }));
});
router.post("/auth/setup", async (req, res) => {
  const parsed = SetupPasswordOwnerBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Use a valid username, email, password of 12–128 characters and setup code." }); return;
  }
  if (!await attempt(req, res, "setup", parsed.data.email.trim().toLowerCase())) return;
  if (await passwordStatus()) { res.status(409).json({ error: "Administrator login is already configured. Sign in instead." }); return; }
  const { username, password, setupCode } = parsed.data;
  const email = parsed.data.email.trim().toLowerCase();
  if (!setupAvailable() || !allowedEmail(email) || !bootstrapMatches(setupCode)) {
    res.status(403).json({ error: "The approved email or setup code was not accepted." }); return;
  }
  const profile: PasswordProfile = { id: randomBytes(16).toString("hex"), username, email,
    passwordHash: await hashPassword(password), version: 1 };
  const result = await adminRequest(serviceActor(profile.id), "POST", "/api/_admin/auth/setup", profile);
  if (!result.ok) {
    res.status(result.status === 409 ? 409 : 503).json({ error: "Owner setup could not be completed. Reload and try signing in." }); return;
  }
  await newSession(req, res, profile);
  res.json(GetCurrentAuthUserResponse.parse({ user: publicUser(profile) }));
});
router.post("/auth/logout", async (req, res) => {
  await clearSession(res, getSessionId(req));
  res.json(GetCurrentAuthUserResponse.parse({ user: null }));
});
router.get("/auth/account", requireOwner, async (_req, res) => {
  const profile = await passwordProfile();
  if (!profile) { res.status(503).json({ error: "Login settings unavailable." }); return; }
  res.json(GetPasswordAccountResponse.parse({ username: profile.username, email: profile.email }));
});
router.patch("/auth/account", requireOwner, async (req, res) => {
  const parsed = UpdatePasswordAccountBody.safeParse(req.body);
  if (!parsed.success) { res.status(400).json({ error: "Check your username, email and password fields." }); return; }
  if (!await attempt(req, res, "update", req.user!.id)) return;
  const current = await passwordProfile();
  if (!current || current.id !== req.user!.id ||
      !await verifyPassword(parsed.data.currentPassword, current.passwordHash)) {
    res.status(403).json({ error: "Your current password was not accepted." }); return;
  }
  const profile: PasswordProfile = { ...current, username: parsed.data.username,
    email: parsed.data.email.trim().toLowerCase(), version: current.version + 1,
    passwordHash: parsed.data.newPassword ? await hashPassword(parsed.data.newPassword) : current.passwordHash };
  const result = await adminRequest(sessionActor(req)!, "POST", "/api/_admin/auth/update", {
    expectedVersion: current.version, profile,
  });
  if (!result.ok) {
    res.status(result.status === 409 ? 409 : 503).json({ error: "Account changed or unavailable. Sign in again." }); return;
  }
  // The credential version also revokes old sessions if database cleanup fails.
  await deleteUserSessions(profile.id);
  await newSession(req, res, profile);
  res.json(GetPasswordAccountResponse.parse({ username: profile.username, email: profile.email }));
});
// Bookmarks and old callbacks never start an external provider flow.
router.get(["/login", "/callback", "/logout"], (_req, res) => { res.redirect("/admin/sign-in"); });
export default router;
