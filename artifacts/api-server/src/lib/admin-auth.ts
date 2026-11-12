import { createHash, timingSafeEqual } from "node:crypto";
import type { Request, Response, NextFunction } from "express";
import { getSessionId } from "./auth";
import { adminRequest, authEpoch } from "./python-bridge";

export function ownerEmails(): string[] {
  return (process.env.STREAMBOT_WEB_ADMIN_EMAILS ?? "").split(",")
    .map(email => email.trim().toLowerCase()).filter(Boolean);
}
export function allowedEmail(email: string | null | undefined, allowed = ownerEmails()): boolean {
  return typeof email === "string" && allowed.includes(email.trim().toLowerCase());
}
export function authConfigured(): boolean { return !!process.env.DATABASE_URL; }
export function sessionActor(req: Request): string | null {
  const sid = getSessionId(req);
  if (!req.isAuthenticated() || !sid || !/^[A-Za-z0-9_-]{1,128}$/.test(req.user.id)) return null;
  return `local:${req.user.id}:${createHash("sha256").update(sid).digest("hex")}`;
}
export function bootstrapMatches(value: unknown): boolean {
  const expected = process.env.STREAMBOT_WEB_BOOTSTRAP_CODE ?? "";
  if (expected.length < 20 || expected.length > 200 || typeof value !== "string" || value.length < 20 || value.length > 200) return false;
  return timingSafeEqual(createHash("sha256").update(expected).digest(),
    createHash("sha256").update(value).digest());
}
// A confirmed owner session is remembered briefly so each page does not repeat the check. Only a
// positive answer is kept, keyed by the exact session, and any sign-in change clears it (authEpoch).
const OWNER_TTL_MS = 15_000;
const confirmedOwners = new Map<string, { epoch: number; until: number }>();
export async function ownerState(actor: string): Promise<{ claimed: boolean; matches: boolean }> {
  const hit = confirmedOwners.get(actor);
  if (hit && hit.epoch === authEpoch() && hit.until > Date.now()) return { claimed: true, matches: true };
  const epoch = authEpoch();
  const value = await fetchOwnerState(actor);
  if (value.matches) {
    if (confirmedOwners.size > 100) confirmedOwners.clear();
    confirmedOwners.set(actor, { epoch, until: Date.now() + OWNER_TTL_MS });
  } else confirmedOwners.delete(actor);
  return value;
}
async function fetchOwnerState(actor: string): Promise<{ claimed: boolean; matches: boolean }> {
  const response = await adminRequest(actor, "GET", "/api/_admin/owner/status");
  if (!response.ok) throw new Error("Owner state unavailable");
  const value = await response.json() as { claimed: boolean; matches: boolean };
  if (typeof value.claimed !== "boolean" || typeof value.matches !== "boolean") throw new Error("Invalid owner state");
  return value;
}
export async function requireOwner(req: Request, res: Response, next: NextFunction) {
  if (!req.isAuthenticated()) {
    res.status(401).json({ error: "Sign in to continue." }); return;
  }
  const actor = sessionActor(req);
  if (!actor) {
    res.status(403).json({ error: "This account does not have administrator access." }); return;
  }
  try {
    if (!(await ownerState(actor)).matches) {
      res.status(403).json({ error: "Complete secure owner setup before opening the dashboard." }); return;
    }
    res.locals.adminActor = actor; next();
  } catch {
    res.status(503).json({ error: "Administrator identity could not be verified. Try again shortly." });
  }
}
