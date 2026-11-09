/** Artifact routing distinguishes /admin from /admin/. Keep the canonical slash. */
export function canonicalBasePath(base: string): string {
  return base.replace(/\/+$/, "") + "/";
}
