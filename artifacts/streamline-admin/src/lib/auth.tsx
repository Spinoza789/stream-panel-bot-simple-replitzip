import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth as useReplitAuth } from "@workspace/replit-auth-web";

type AuthState = ReturnType<typeof useReplitAuth>;

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const auth = useReplitAuth();
  const qc = useQueryClient();
  const prev = useRef<string | null | undefined>(undefined);
  const userId = auth.isLoading ? undefined : (auth.user?.id ?? null);

  useEffect(() => {
    if (userId === undefined) return;
    if (prev.current !== undefined && prev.current !== userId) qc.clear();
    prev.current = userId;
  }, [userId, qc]);

  return <AuthCtx.Provider value={auth}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}

export function displayName(user: AuthState["user"]): string {
  if (!user) return "";
  const n = [user.firstName, user.lastName].filter(Boolean).join(" ");
  return n || user.email || "Owner";
}
