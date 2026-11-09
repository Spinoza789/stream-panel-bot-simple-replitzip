import { GetCurrentAuthUserResponse } from "@workspace/api-zod";
import { db, usersTable } from "@workspace/db";
import { Router, type IRouter, type Request, type Response } from "express";
import * as oidc from "openid-client";
import {
  clearSession, createSession, getOidcConfig, getSessionId,
  SESSION_COOKIE, SESSION_TTL, type SessionData,
} from "../lib/auth";

const router: IRouter = Router();
router.use((_req, res, next) => { res.set("Cache-Control", "no-store"); next(); });
function origin(): string {
  const value = process.env.NODE_ENV === "production" ? process.env.STREAMBOT_PUBLIC_URL :
    `https://${process.env.REPLIT_DEV_DOMAIN}`;
  const url = new URL(value ?? "");
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("HTTPS origin required.");
  return url.origin;
}
export function safeReturnTo(value: unknown): string {
  if (value === "/admin") return "/admin/";
  return typeof value === "string" && /^\/admin(?:\/[a-zA-Z0-9/_-]*)?$/.test(value) ? value : "/admin/";
}
function cookie(res: Response, name: string, value: string, maxAge: number) {
  res.cookie(name, value, { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge });
}
function clearFlow(res: Response) {
  for (const key of ["code_verifier", "nonce", "state", "return_to"]) res.clearCookie(key, { path: "/" });
}

router.get("/auth/user", (req, res) => {
  res.json(GetCurrentAuthUserResponse.parse({ user: req.isAuthenticated() ? req.user : null }));
});
router.get("/login", async (req, res) => {
  const config = await getOidcConfig();
  const state = oidc.randomState();
  const nonce = oidc.randomNonce();
  const verifier = oidc.randomPKCECodeVerifier();
  const challenge = await oidc.calculatePKCECodeChallenge(verifier);
  const redirect = oidc.buildAuthorizationUrl(config, {
    redirect_uri: `${origin()}/api/callback`, scope: "openid email profile offline_access",
    code_challenge: challenge, code_challenge_method: "S256", prompt: "login consent", state, nonce,
  });
  cookie(res, "code_verifier", verifier, 600000);
  cookie(res, "nonce", nonce, 600000);
  cookie(res, "state", state, 600000);
  cookie(res, "return_to", safeReturnTo(req.query.returnTo), 600000);
  res.redirect(redirect.href);
});
router.get("/callback", async (req: Request, res: Response) => {
  const codeVerifier = req.cookies?.code_verifier;
  const nonce = req.cookies?.nonce;
  const expectedState = req.cookies?.state;
  const returnTo = safeReturnTo(req.cookies?.return_to);
  clearFlow(res);
  if (!codeVerifier || !nonce || !expectedState) { res.redirect("/admin/"); return; }
  try {
    const config = await getOidcConfig();
    const current = new URL(`${origin()}/api/callback`);
    new URL(req.originalUrl, origin()).searchParams.forEach((value, key) => current.searchParams.append(key, value));
    const tokens = await oidc.authorizationCodeGrant(config, current, {
      pkceCodeVerifier: codeVerifier, expectedNonce: nonce, expectedState, idTokenExpected: true,
    });
    const claims = tokens.claims();
    if (!claims || !/^[a-zA-Z0-9_-]{1,128}$/.test(claims.sub)) throw new Error("Invalid identity");
    const profile = {
      id: claims.sub,
      email: typeof claims.email === "string" ? claims.email : null,
      firstName: typeof claims.first_name === "string" ? claims.first_name : null,
      lastName: typeof claims.last_name === "string" ? claims.last_name : null,
      profileImageUrl: typeof claims.profile_image_url === "string" ? claims.profile_image_url : null,
    };
    // Prevent an explicitly unverified provider email from matching the allowlist.
    if (claims.email_verified === false) profile.email = null;
    await db.insert(usersTable).values(profile).onConflictDoUpdate({
      target: usersTable.id, set: { ...profile, updatedAt: new Date() },
    });
    const now = Math.floor(Date.now() / 1000);
    const data: SessionData = {
      user: profile, access_token: tokens.access_token, refresh_token: tokens.refresh_token,
      expires_at: tokens.expiresIn() ? now + tokens.expiresIn()! : claims.exp,
    };
    // Login always rotates the local session identifier.
    await clearSession(res, getSessionId(req));
    const sid = await createSession(data);
    cookie(res, SESSION_COOKIE, sid, SESSION_TTL);
    res.redirect(returnTo);
  } catch {
    // Never log authorization codes, token bodies, cookies or provider responses.
    res.redirect("/admin/?auth=failed");
  }
});
router.get("/logout", async (req, res) => {
  await clearSession(res, getSessionId(req));
  const config = await getOidcConfig();
  res.redirect(oidc.buildEndSessionUrl(config, {
    client_id: process.env.REPL_ID!,
    post_logout_redirect_uri: new URL(safeReturnTo(req.query.returnTo), origin()).href,
  }).href);
});
export default router;
