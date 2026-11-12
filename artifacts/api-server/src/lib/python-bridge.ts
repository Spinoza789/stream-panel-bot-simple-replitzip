import { createHmac, randomBytes, createHash } from "node:crypto";
import type { Request, Response } from "express";
import http from "node:http";

// Process-only capability; shared solely with the supervised Python child.
export const bridgeKey = randomBytes(32).toString("hex");
export let pythonPort = 0;
export function setPythonPort(port: number) { pythonPort = port; }

export function legacyProxy(req: Request, res: Response) {
  if (!pythonPort) { res.status(503).json({ error: "The service is starting." }); return; }
  const headers = { ...req.headers };
  // Internal capabilities are never forwarded from a browser.
  for (const key of Object.keys(headers)) {
    if (key.startsWith("x-streamline-") || ["connection", "transfer-encoding"].includes(key)) delete headers[key];
  }
  const upstream = http.request({ hostname: "127.0.0.1", port: pythonPort,
    method: req.method, path: req.originalUrl, headers, timeout: 30000 }, incoming => {
    const responseHeaders = { ...incoming.headers };
    delete responseHeaders["transfer-encoding"]; delete responseHeaders.connection;
    res.writeHead(incoming.statusCode ?? 502, responseHeaders);
    incoming.on("error", () => res.destroy()); incoming.pipe(res);
  });
  upstream.on("timeout", () => upstream.destroy());
  upstream.on("error", () => {
    if (res.headersSent) { res.destroy(); return; }
    res.status(503).json({ error: "The service is starting. Please retry shortly." });
  });
  req.on("aborted", () => upstream.destroy());
  req.pipe(upstream);
}

// Bumped whenever the gateway changes anything about the owner's sign-in (setup, password,
// username, two-factor, a counted attempt). Short-lived caches of sign-in state compare against it,
// so a change made here takes effect on the very next request.
let authEpochValue = 0;
export function authEpoch(): number { return authEpochValue; }

export async function adminRequest(actor: string, method: string, path: string, body?: unknown) {
  if (method !== "GET" && (path.startsWith("/api/_admin/auth/") || path.startsWith("/api/_admin/owner/"))) authEpochValue += 1;
  const raw = body === undefined ? "" : JSON.stringify(body);
  const time = String(Math.floor(Date.now() / 1000));
  const nonce = randomBytes(16).toString("hex");
  const signature = createHmac("sha256", bridgeKey).update([
    method, path, actor, time, nonce, createHash("sha256").update(raw).digest("hex"),
  ].join("\n")).digest("hex");
  return fetch(`http://127.0.0.1:${pythonPort}${path}`, {
    method, redirect: "error", signal: AbortSignal.timeout(15000),
    headers: { "Content-Type": "application/json", "X-Streamline-Actor": actor,
      "X-Streamline-Time": time, "X-Streamline-Nonce": nonce, "X-Streamline-Signature": signature },
    ...(body === undefined ? {} : { body: raw }),
  });
}
