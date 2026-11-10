import type { NextFunction, Request, Response } from "express";

export function sameOriginJson(req: Request, res: Response, next: NextFunction) {
  if (["GET", "HEAD", "OPTIONS"].includes(req.method)) { next(); return; }
  let valid = false;
  try {
    const origin = new URL(req.get("origin") ?? "");
    valid = ["http:", "https:"].includes(origin.protocol) && origin.host === req.get("host");
  } catch { /* No origin is not an authenticated browser mutation. */ }
  if (!valid || req.get("sec-fetch-site") === "cross-site" || !req.is("application/json")) {
    res.status(403).json({ error: "Use this website to submit the request." }); return;
  }
  next();
}
