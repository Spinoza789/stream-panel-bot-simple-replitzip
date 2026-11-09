import express, { type Express } from "express";
import pinoHttp from "pino-http";
import cookieParser from "cookie-parser";
import { authMiddleware } from "./middlewares/authMiddleware";
import authRouter from "./routes/auth";
import adminRouter from "./routes/admin";
import { legacyProxy } from "./lib/python-bridge";
import { logger } from "./lib/logger";

const app: Express = express();
app.disable("x-powered-by");
app.use(pinoHttp({ logger, serializers: {
  req: req => ({ id: req.id, method: req.method, url: req.url?.split("?")[0] }),
  res: res => ({ statusCode: res.statusCode }),
} }));
// Explicitly block the private bridge, including URL-encoded alternate paths.
app.use((req, res, next) => {
  let path = req.path;
  try { path = decodeURIComponent(path); } catch { res.sendStatus(400); return; }
  if (path.toLowerCase().startsWith("/api/_admin")) { res.sendStatus(404); return; }
  next();
});
// Existing checkout stays byte-for-byte proxied BEFORE body parsing.
app.use((req, res, next) => {
  if (req.path === "/api/admin" || req.path.startsWith("/api/admin/") ||
      ["/api/auth/user", "/api/login", "/api/callback", "/api/logout"].includes(req.path)) next();
  else legacyProxy(req, res);
});
app.use(cookieParser());
app.use(express.json({ limit: "4kb" }));
app.use(authMiddleware);
app.use("/api", authRouter);
app.use("/api/admin", adminRouter);
app.use((_err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  res.status(503).json({ error: "Authentication or operations are temporarily unavailable." });
});
export default app;
