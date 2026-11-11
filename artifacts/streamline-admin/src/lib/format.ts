export function toDate(unix: number): Date {
  return new Date(unix > 1e12 ? unix : unix * 1000);
}

export function formatDateTime(unix: number): string {
  if (!unix) return "—";
  return toDate(unix).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(unix: number): string {
  if (!unix) return "";
  const diff = (Date.now() - toDate(unix).getTime()) / 1000;
  const abs = Math.abs(diff);
  const fmt = (n: number, u: string) => `${Math.round(n)}${u} ${diff >= 0 ? "ago" : "from now"}`;
  if (abs < 60) return "just now";
  if (abs < 3600) return fmt(abs / 60, "m");
  if (abs < 86400) return fmt(abs / 3600, "h");
  return fmt(abs / 86400, "d");
}

export function humanize(s: string): string {
  if (!s) return "—";
  return s.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function errorStatus(err: unknown): number | undefined {
  const s = (err as { status?: unknown })?.status;
  return typeof s === "number" ? s : undefined;
}

export function errorMessage(err: unknown): string {
  if (!err) return "Unknown error";
  const data = (err as { data?: unknown })?.data as { error?: string; message?: string } | null | undefined;
  if (data && typeof data === "object") {
    if (typeof data.error === "string") return data.error;
    if (typeof data.message === "string") return data.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

export type Tone = "success" | "attention" | "critical" | "info" | "neutral";

export function statusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (/(fulfill|deliver|complete|active|paid|success)/.test(s)) return "success";
  if (/(review|stuck|hold|manual)/.test(s)) return "attention";
  if (/(fail|error|cancel|expire|refund|reject)/.test(s)) return "critical";
  if (/(queue|process|provision)/.test(s)) return "info";
  return "neutral";
}

export function gbp(value: number): string {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 2 }).format(value);
}
export function formatDate(unix: number): string {
  if (!unix) return "—";
  return toDate(unix).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
