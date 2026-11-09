import { Router, type IRouter } from "express";
import {
  ConfirmTrialRecoveryBody, ClaimAdminOwnerBody, GetAdminAccessResponse, GetAdminOverviewResponse,
  ListAdminOrdersQueryParams, ListAdminOrdersResponse, GetAdminOrderResponse,
  GetAdminStatusResponse, PreviewTrialRecoveryResponse, ConfirmTrialRecoveryResponse,
} from "@workspace/api-zod";
import { authConfigured, sessionActor, ownerEmails, allowedEmail, bootstrapMatches, ownerState, requireOwner } from "../lib/admin-auth";
import { adminRequest } from "../lib/python-bridge";

const router: IRouter = Router();
router.use((_req, res, next) => {
  res.set({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
  next();
});
router.get("/access", async (req, res) => {
  try {
    const actor = sessionActor(req);
    const state = actor ? await ownerState(actor) : { claimed: false, matches: false };
    const emailAllowed = allowedEmail(req.user?.email);
    res.json(GetAdminAccessResponse.parse({
      authenticated: req.isAuthenticated(),
      authorized: state.matches && emailAllowed,
      ownerConfigured: !!ownerEmails().length && (state.claimed ||
        (process.env.STREAMBOT_WEB_BOOTSTRAP_CODE?.length ?? 0) >= 20),
      authConfigured: authConfigured(),
      canClaimOwner: !!actor && emailAllowed && !state.claimed &&
        (process.env.STREAMBOT_WEB_BOOTSTRAP_CODE?.length ?? 0) >= 20,
    }));
  } catch { res.status(503).json({ error: "Sign-in status is temporarily unavailable." }); }
});
router.use((req, res, next) => {
  if (req.method === "POST") {
    const origin = req.get("origin");
    // Browser requests must be same-origin and JSON; no credentialed wildcard CORS.
    let matches = false;
    try {
      const url = new URL(origin ?? "");
      matches = ["http:", "https:"].includes(url.protocol) && url.host === req.get("host");
    } catch { /* deny */ }
    if (!matches || req.get("sec-fetch-site") === "cross-site" || !req.is("application/json")) {
      res.status(403).json({ error: "A same-origin JSON request is required." }); return;
    }
  }
  next();
});
const attempts = new Map<string, { count: number; until: number }>();
router.post("/claim-owner", async (req, res) => {
  const actor = sessionActor(req);
  if (!actor) { res.status(401).json({ error: "Sign in before owner setup." }); return; }
  if (!allowedEmail(req.user?.email)) { res.status(403).json({ error: "Owner email does not match." }); return; }
  const key = req.user!.id;
  let attempt = attempts.get(key);
  if (!attempt || attempt.until < Date.now()) {
    attempt = { count: 0, until: Date.now() + 15 * 60 * 1000 }; attempts.set(key, attempt);
  }
  if (++attempt.count > 5) { res.status(429).json({ error: "Wait 15 minutes before trying owner setup again." }); return; }
  const parsed = ClaimAdminOwnerBody.safeParse(req.body);
  if (!parsed.success || !bootstrapMatches(parsed.data.code)) {
    res.status(403).json({ error: "The owner setup code is invalid." }); return;
  }
  try {
    const result = await adminRequest(actor, "POST", "/api/_admin/owner/claim", {});
    if (!result.ok) { res.status(result.status).json({ error: "Owner setup is already completed or unavailable." }); return; }
    res.json(GetAdminAccessResponse.parse({ authenticated: true, authorized: true,
      ownerConfigured: true, authConfigured: true, canClaimOwner: false }));
  } catch { res.status(503).json({ error: "Owner setup is temporarily unavailable." }); }
});
router.use(requireOwner);

// All downstream paths are fixed allowlisted routes; no caller controls a target URL.
router.use(async (req, res) => {
  try {
    let target = "";
    let schema: { parse: (value: unknown) => unknown };
    let body: unknown = undefined;
    if (req.method === "GET" && req.path === "/overview") {
      target = "/overview"; schema = GetAdminOverviewResponse;
    } else if (req.method === "GET" && req.path === "/status") {
      target = "/status"; schema = GetAdminStatusResponse;
    } else if (req.method === "GET" && req.path === "/orders") {
      const parsed = ListAdminOrdersQueryParams.safeParse(req.query);
      if (!parsed.success) { res.status(400).json({ error: "Invalid order filters." }); return; }
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(parsed.data)) if (value !== undefined) params.set(key, String(value));
      target = "/orders?" + params.toString(); schema = ListAdminOrdersResponse;
    } else if (req.method === "GET" && /^\/orders\/[a-f0-9]{24}$/.test(req.path)) {
      target = req.path; schema = GetAdminOrderResponse;
    } else if (req.method === "POST" && /^\/orders\/[a-f0-9]{24}\/recovery$/.test(req.path)) {
      if (!req.body || Object.keys(req.body).length) { res.status(400).json({ error: "Invalid preview." }); return; }
      target = req.path; schema = PreviewTrialRecoveryResponse; body = {};
    } else if (req.method === "POST" && req.path === "/recovery/confirm") {
      const parsed = ConfirmTrialRecoveryBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Invalid recovery confirmation." }); return; }
      target = req.path; schema = ConfirmTrialRecoveryResponse; body = parsed.data;
    } else { res.status(404).json({ error: "Admin operation not found." }); return; }
    const upstream = await adminRequest(res.locals.adminActor, req.method, "/api/_admin" + target, body);
    const data = await upstream.json();
    if (!upstream.ok) {
      // Only our internal safe CheckoutError strings, never raw provider errors.
      const error = data && typeof data === "object" && "error" in data ? data.error : null;
      res.status(upstream.status).json({ error: typeof error === "string" ? error : "Operation unavailable." }); return;
    }
    res.json(schema.parse(data));
  } catch {
    res.status(503).json({ error: "The operations service is unavailable. No automatic retry was submitted." });
  }
});
export default router;
