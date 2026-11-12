import { Router, type IRouter } from "express";
import {
  ConfirmTrialRecoveryBody, GetAdminAccessResponse, GetAdminOverviewResponse,
  ListAdminOrdersQueryParams, ListAdminOrdersResponse, GetAdminOrderResponse,
  GetAdminStatusResponse, PreviewTrialRecoveryResponse, ConfirmTrialRecoveryResponse,
  ListAdminResellersQueryParams, ListAdminResellersResponse, GetAdminResellerResponse,
  SetAdminResellerStatusBody, AdjustAdminResellerCreditsBody, GetAdminReportsQueryParams, GetAdminReportsResponse,
  GetAdminRateCardResponse, UpdateAdminRateCardBody, GetAdminFaqResponse, UpdateAdminFaqBody,
  ListAdminTicketsQueryParams, ListAdminTicketsResponse, GetAdminTicketResponse, ReplyAdminTicketBody, SetAdminTicketStatusBody,
  SetAdminResellerTrialLimitsBody, ListAdminSubscriptionsQueryParams, ListAdminSubscriptionsResponse,
  AddAdminSubscriptionBody, AddAdminSubscriptionResponse, DeleteAdminSubscriptionBody, DeleteAdminSubscriptionResponse,
  ListAdminActivityLogQueryParams, ListAdminActivityLogResponse, ListAdminCreditLogQueryParams, ListAdminCreditLogResponse,
} from "@workspace/api-zod";
import { authConfigured, sessionActor, ownerState, requireOwner } from "../lib/admin-auth";
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
    res.json(GetAdminAccessResponse.parse({
      authenticated: req.isAuthenticated(),
      authorized: state.matches,
      ownerConfigured: state.claimed,
      authConfigured: authConfigured(),
      canClaimOwner: false,
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
    } else if (req.method === "GET" && req.path === "/resellers") {
      const parsed = ListAdminResellersQueryParams.safeParse(req.query);
      if (!parsed.success) { res.status(400).json({ error: "Invalid reseller filters." }); return; }
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(parsed.data)) if (value !== undefined) params.set(key, String(value));
      target = "/resellers?" + params.toString(); schema = ListAdminResellersResponse;
    } else if (req.method === "GET" && /^\/resellers\/[1-9][0-9]{0,18}$/.test(req.path)) {
      target = req.path; schema = GetAdminResellerResponse;
    } else if (req.method === "POST" && /^\/resellers\/[1-9][0-9]{0,18}\/status$/.test(req.path)) {
      const parsed = SetAdminResellerStatusBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Choose active or suspended and give a reason." }); return; }
      target = req.path; schema = GetAdminResellerResponse; body = parsed.data;
    } else if (req.method === "POST" && /^\/resellers\/[1-9][0-9]{0,18}\/credits$/.test(req.path)) {
      const parsed = AdjustAdminResellerCreditsBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Enter whole credits, a reason and a request key." }); return; }
      target = req.path; schema = GetAdminResellerResponse; body = parsed.data;
    } else if (req.method === "POST" && /^\/resellers\/[1-9][0-9]{0,18}\/trial-limits$/.test(req.path)) {
      const parsed = SetAdminResellerTrialLimitsBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Each limit is a whole number, -1 for unlimited or empty for the default, with a reason." }); return; }
      target = req.path; schema = GetAdminResellerResponse; body = parsed.data;
    } else if (req.method === "GET" && req.path === "/subscriptions") {
      const parsed = ListAdminSubscriptionsQueryParams.safeParse(req.query);
      if (!parsed.success) { res.status(400).json({ error: "Invalid subscription filters." }); return; }
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(parsed.data)) if (value !== undefined) params.set(key, String(value));
      target = "/subscriptions?" + params.toString(); schema = ListAdminSubscriptionsResponse;
    } else if (req.method === "POST" && req.path === "/subscriptions") {
      const parsed = AddAdminSubscriptionBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Enter a numeric Telegram ID, choose a plan and give a reason." }); return; }
      target = "/subscriptions"; schema = AddAdminSubscriptionResponse; body = parsed.data;
    } else if (req.method === "POST" && /^\/subscriptions\/(retail|reseller)\/[a-f0-9]{24}\/delete$/.test(req.path)) {
      const parsed = DeleteAdminSubscriptionBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Confirm the deletion and give a reason." }); return; }
      target = req.path; schema = DeleteAdminSubscriptionResponse; body = parsed.data;
    } else if (req.method === "GET" && (req.path === "/logs/activity" || req.path === "/logs/credits")) {
      const activity = req.path === "/logs/activity";
      const parsed = (activity ? ListAdminActivityLogQueryParams : ListAdminCreditLogQueryParams).safeParse(req.query);
      if (!parsed.success) { res.status(400).json({ error: "Invalid log filters." }); return; }
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(parsed.data)) if (value !== undefined) params.set(key, String(value));
      target = req.path + "?" + params.toString(); schema = activity ? ListAdminActivityLogResponse : ListAdminCreditLogResponse;
    } else if (req.method === "GET" && req.path === "/reports") {
      const parsed = GetAdminReportsQueryParams.safeParse(req.query);
      if (!parsed.success) { res.status(400).json({ error: "Invalid report range." }); return; }
      target = "/reports?months=" + String(parsed.data.months ?? 12); schema = GetAdminReportsResponse;
    } else if (req.method === "GET" && req.path === "/tickets") {
      const parsed = ListAdminTicketsQueryParams.safeParse(req.query);
      if (!parsed.success) { res.status(400).json({ error: "Invalid ticket filters." }); return; }
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(parsed.data)) if (value !== undefined) params.set(key, String(value));
      target = "/tickets?" + params.toString(); schema = ListAdminTicketsResponse;
    } else if (req.method === "GET" && /^\/tickets\/T[A-HJ-NP-Z2-9]{6}$/.test(req.path)) {
      target = req.path; schema = GetAdminTicketResponse;
    } else if (req.method === "POST" && /^\/tickets\/T[A-HJ-NP-Z2-9]{6}\/reply$/.test(req.path)) {
      const parsed = ReplyAdminTicketBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Write a reply of up to 2000 characters." }); return; }
      target = req.path; schema = GetAdminTicketResponse; body = parsed.data;
    } else if (req.method === "POST" && /^\/tickets\/T[A-HJ-NP-Z2-9]{6}\/status$/.test(req.path)) {
      const parsed = SetAdminTicketStatusBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Status must be open or closed." }); return; }
      target = req.path; schema = GetAdminTicketResponse; body = parsed.data;
    } else if (req.method === "GET" && req.path === "/faq") {
      target = "/faq"; schema = GetAdminFaqResponse;
    } else if (req.method === "POST" && req.path === "/faq") {
      const parsed = UpdateAdminFaqBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Each FAQ entry needs a question (up to 120 characters) and an answer (up to 1500)." }); return; }
      target = "/faq"; schema = GetAdminFaqResponse; body = parsed.data;
    } else if (req.method === "GET" && req.path === "/ratecard") {
      target = "/ratecard"; schema = GetAdminRateCardResponse;
    } else if (req.method === "POST" && req.path === "/ratecard") {
      const parsed = UpdateAdminRateCardBody.safeParse(req.body);
      if (!parsed.success) { res.status(400).json({ error: "Invalid rate card change." }); return; }
      target = "/ratecard"; schema = GetAdminRateCardResponse; body = parsed.data;
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
