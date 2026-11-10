import type { AuthUser } from "@workspace/api-zod";
import type { NextFunction, Request, Response } from "express";
import { clearSession, getSession, getSessionId } from "../lib/auth";
import { passwordProfile, publicUser } from "../lib/password-auth";

declare global {
  namespace Express {
    interface User extends AuthUser {}
    interface Request {
      isAuthenticated(): this is AuthedRequest;
      user?: User;
    }
    interface AuthedRequest { user: User }
  }
}
export async function authMiddleware(req: Request, res: Response, next: NextFunction) {
  req.isAuthenticated = function(this: Request) { return this.user != null; } as Request["isAuthenticated"];
  const sid = getSessionId(req);
  if (!sid) { next(); return; }
  const session = await getSession(sid);
  // Old OIDC sessions are intentionally not valid local-password sessions.
  if (!session || session.kind !== "password-v1" || !session.user?.id ||
      !Number.isInteger(session.credentialVersion)) {
    await clearSession(res, sid); next(); return;
  }
  const profile = await passwordProfile();
  if (!profile || profile.id !== session.user.id || profile.version !== session.credentialVersion) {
    await clearSession(res, sid); next(); return;
  }
  req.user = publicUser(profile);
  next();
}
