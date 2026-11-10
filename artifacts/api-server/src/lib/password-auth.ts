import { createHash, randomBytes, scrypt, timingSafeEqual } from "node:crypto";
import { adminRequest } from "./python-bridge";

const options = { N: 32768, r: 8, p: 3, maxmem: 64 * 1024 * 1024 };
let hashing = 0;
export class PasswordBusy extends Error {}
async function hash(value: string, salt: string): Promise<Buffer> {
  if (hashing >= 4) throw new PasswordBusy("Sign-in is busy. Try again shortly.");
  hashing++;
  try {
    return await new Promise<Buffer>((resolve, reject) => {
      scrypt(value, salt, 64, options, (error, key) => error ? reject(error) : resolve(key));
    });
  }
  finally { hashing--; }
}
export async function hashPassword(value: string): Promise<string> {
  const salt = randomBytes(16).toString("hex");
  return `scrypt-v1$${salt}$${(await hash(value, salt)).toString("hex")}`;
}
export async function verifyPassword(value: string, encoded: string): Promise<boolean> {
  const parts = /^scrypt-v1\$([a-f0-9]{32})\$([a-f0-9]{128})$/.exec(encoded);
  // Still do equivalent work for a missing/malformed account.
  const result = await hash(value, parts?.[1] ?? "0".repeat(32));
  const expected = Buffer.from(parts?.[2] ?? "0".repeat(128), "hex");
  return timingSafeEqual(result, expected) && !!parts;
}
export interface PasswordProfile {
  id: string; username: string; email: string; passwordHash: string; version: number;
}
export function serviceActor(id = "auth_service"): string {
  return `local:${id}:${randomBytes(32).toString("hex")}`;
}
export async function passwordProfile(): Promise<PasswordProfile | null> {
  const response = await adminRequest(serviceActor(), "GET", "/api/_admin/auth/credentials");
  if (!response.ok) throw new Error("Password account unavailable");
  return (await response.json() as { profile: PasswordProfile | null }).profile;
}
export async function passwordStatus(): Promise<boolean> {
  const response = await adminRequest(serviceActor(), "GET", "/api/_admin/auth/status");
  if (!response.ok) throw new Error("Password account unavailable");
  return (await response.json() as { configured: boolean }).configured;
}
export async function allowPasswordAttempt(kind: "login" | "setup" | "update", ip: string, identity: string) {
  const digest = (value: string) => createHash("sha256").update(value).digest("hex");
  const result = await adminRequest(serviceActor(), "POST", "/api/_admin/auth/attempt", {
    kind, buckets: [digest("ip:" + ip), digest("identity:" + identity.trim().toLowerCase())],
  });
  if (!result.ok) throw new Error("Sign-in protection unavailable");
  return (await result.json() as { allowed: boolean }).allowed;
}
export function publicUser(profile: PasswordProfile) {
  return { id: profile.id, email: profile.email, firstName: profile.username,
    lastName: null, profileImageUrl: null };
}
