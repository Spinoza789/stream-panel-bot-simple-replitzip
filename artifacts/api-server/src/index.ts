import { spawn } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import app from "./app";
import { logger } from "./lib/logger";
import { bridgeKey, setPythonPort } from "./lib/python-bridge";

const port = Number(process.env.PORT);
if (!Number.isInteger(port) || port <= 0) throw new Error("A valid PORT is required.");
// Bind the business backend only to loopback, on a supervisor-allocated port.
const reserve = createServer();
reserve.listen(0, "127.0.0.1", () => {
  const address = reserve.address();
  if (!address || typeof address === "string") throw new Error("Cannot allocate backend port.");
  const childPort = address.port;
  reserve.close(() => {
    setPythonPort(childPort);
    const child = spawn("bash", ["start-python.sh", ...(process.env.NODE_ENV === "production" ? [] : ["--demo"])], {
      cwd: path.resolve(import.meta.dirname, ".."), stdio: "inherit",
      env: { ...process.env, PORT: String(childPort), STREAMBOT_HOST: "127.0.0.1",
        STREAMBOT_ADMIN_BRIDGE_KEY: bridgeKey },
    });
    const server = app.listen(port, "0.0.0.0", () => logger.info({ port }, "API gateway listening"));
    let shuttingDown = false;
    const close = () => {
      if (shuttingDown) return;
      shuttingDown = true; child.kill("SIGTERM");
      server.close();
      setTimeout(() => { child.kill("SIGKILL"); process.exit(0); }, 10000).unref();
    };
    for (const signal of ["SIGINT", "SIGTERM"] as const) process.on(signal, close);
    child.on("exit", code => { if (!shuttingDown) process.exit(code || 1); else process.exit(0); });
  });
});
