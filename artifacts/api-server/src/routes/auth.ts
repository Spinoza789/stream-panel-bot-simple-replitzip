import { randomBytes } from "node:crypto";
import { Router, type Request, type Response, type IRouter } from "express";
import {
  GetCurrentAuthUserResponse, GetPasswordAccountResponse, GetPasswordAuthStatusResponse,
  PasswordLoginBody, SetupPasswordOwnerBody, UpdatePasswordAccountBody,
  SetupTotpResponse, EnableTotpBody, DisableTotpBody,
} from "@workspace/api-zod";
import { newSecret, otpauthUri, verifyTotp } from "../lib/totp";
import { clearSession, createSession, deleteUserSessions, getSession, getSessionId, updateSession, SESSION_COOKIE, SESSION_TTL, type SessionData } from "../lib/auth";
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
  if (profile.totp) {
    // Second factor: the password alone never opens a session once an authenticator is enrolled.
    if (!parsed.data.code) { res.status(401).json({ error: "Enter the 6-digit code from your authenticator app.", code: "totp_required" }); return; }
    if (!verifyTotp(profile.totp.secret, parsed.data.code)) { res.status(401).json({ error: "That authenticator code is not right." }); return; }
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
function account(profile: PasswordProfile) {
  return GetPasswordAccountResponse.parse({ username: profile.username, email: profile.email, totpEnabled: !!profile.totp });
}
router.get("/auth/account", requireOwner, async (_req, res) => {
  const profile = await passwordProfile();
  if (!profile) { res.status(503).json({ error: "Login settings unavailable." }); return; }
  res.json(account(profile));
});
async function saveProfile(req: Request, current: PasswordProfile, next: PasswordProfile) {
  return adminRequest(sessionActor(req)!, "POST", "/api/_admin/auth/update", { expectedVersion: current.version, profile: next });
}
// Two-factor enrolment: the secret lives only in this session until a code proves the app has it.
router.post("/auth/totp/setup", requireOwner, async (req, res) => {
  const current = await passwordProfile();
  if (!current || current.id !== req.user!.id) { res.status(403).json({ error: "Owner session required." }); return; }
  if (current.totp) { res.status(409).json({ error: "Two-factor sign-in is already enabled. Disable it first to enrol a new device." }); return; }
  const secret = newSecret();
  const uri = otpauthUri(secret, current.email);
  const sid = getSessionId(req)!;
  const session = await getSession(sid);
  if (!session) { res.status(401).json({ error: "Sign in to continue." }); return; }
  await updateSession(sid, { ...session, pendingTotp: secret } as SessionData);
  let qr = "";
  try {
    const rendered = await adminRequest(sessionActor(req)!, "POST", "/api/_admin/auth/qr", { uri });
    if (rendered.ok) qr = String(((await rendered.json()) as { qr?: string }).qr ?? "");
  } catch { /* the secret can still be typed by hand */ }
  res.json(SetupTotpResponse.parse({ secret, uri, qr }));
});
router.post("/auth/totp/enable", requireOwner, async (req, res) => {
  const parsed = EnableTotpBody.safeParse(req.body);
  if (!parsed.success) { res.status(400).json({ error: "Enter the 6-digit code from your authenticator app." }); return; }
  if (!await attempt(req, res, "update", req.user!.id)) return;
  const sid = getSessionId(req)!;
  const session = await getSession(sid) as (SessionData & { pendingTotp?: string }) | null;
  const current = await passwordProfile();
  if (!session?.pendingTotp || !current || current.id !== req.user!.id) { res.status(409).json({ error: "Start enrolment again." }); return; }
  if (!verifyTotp(session.pendingTotp, parsed.data.code)) { res.status(400).json({ error: "That code did not match. Check the time on your phone and try again." }); return; }
  const profile: PasswordProfile = { ...current, version: current.version + 1, totp: { secret: session.pendingTotp, enabledAt: Math.floor(Date.now() / 1000) } };
  const result = await saveProfile(req, current, profile);
  if (!result.ok) { res.status(result.status === 409 ? 409 : 503).json({ error: "Account changed or unavailable. Sign in again." }); return; }
  await deleteUserSessions(profile.id);
  await newSession(req, res, profile);
  res.json(account(profile));
});
router.post("/auth/totp/disable", requireOwner, async (req, res) => {
  const parsed = DisableTotpBody.safeParse(req.body);
  if (!parsed.success) { res.status(400).json({ error: "Enter your password and a current authenticator code." }); return; }
  if (!await attempt(req, res, "update", req.user!.id)) return;
  const current = await passwordProfile();
  if (!current || current.id !== req.user!.id || !current.totp) { res.status(409).json({ error: "Two-factor sign-in is not enabled." }); return; }
  if (!await verifyPassword(parsed.data.currentPassword, current.passwordHash) || !verifyTotp(current.totp.secret, parsed.data.code)) {
    res.status(403).json({ error: "Your password or authenticator code was not accepted." }); return;
  }
  const { totp: _removed, ...rest } = current;
  const profile: PasswordProfile = { ...rest, version: current.version + 1 };
  const result = await saveProfile(req, current, profile);
  if (!result.ok) { res.status(result.status === 409 ? 409 : 503).json({ error: "Account changed or unavailable. Sign in again." }); return; }
  await deleteUserSessions(profile.id);
  await newSession(req, res, profile);
  res.json(account(profile));
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
  res.json(account(profile));
});
// Bookmarks and old callbacks never start an external provider flow.
router.get(["/login", "/callback", "/logout"], (_req, res) => { res.redirect("/admin/sign-in"); });
export default router;
