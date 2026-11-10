import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetCurrentAuthUser,
  getGetCurrentAuthUserQueryKey,
  usePasswordLogout,
  type AuthUser,
} from "@workspace/api-client-react";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, errorStatus } from "@/lib/format";

type AuthState = {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isError: boolean;
  isLoggingOut: boolean;
  login: () => void;
  logout: () => void;
};

const AuthCtx = createContext<AuthState | null>(null);
const base = import.meta.env.BASE_URL.endsWith("/") ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useGetCurrentAuthUser({ query: { queryKey: getGetCurrentAuthUserQueryKey(), retry: 1, refetchOnWindowFocus: true } });
  const { toast } = useToast();
  const out = usePasswordLogout();
  const outRef = useRef(out.mutate);
  outRef.current = out.mutate;
  const user = q.data?.user ?? null;
  const prev = useRef<string | null | undefined>(undefined);
  const unauth = q.isError && errorStatus(q.error) === 401;
  const hardError = q.isError && !unauth && !q.data;
  const userId = q.isLoading || hardError ? undefined : (user?.id ?? null);

  useEffect(() => {
    if (userId === undefined) return;
    if (prev.current !== undefined && prev.current !== userId) qc.clear();
    prev.current = userId;
  }, [userId, qc]);

  const login = useCallback(() => {
    window.location.assign(`${base}sign-in`);
  }, []);

  const logout = useCallback(() => {
    outRef.current({ data: {} }, {
      onSuccess: () => {
        qc.clear();
        window.location.assign(`${base}sign-in`);
      },
      onError: (err) => {
        toast({
          variant: "destructive",
          title: "Sign out failed",
          description: `You are still signed in. ${errorMessage(err)} Try again.`,
        });
      },
    });
  }, [qc, toast]);

  const value = useMemo<AuthState>(() => ({
    user,
    isLoading: q.isLoading || hardError,
    isAuthenticated: !!user,
    isError: hardError,
    isLoggingOut: out.isPending,
    login,
    logout,
  }), [user, q.isLoading, hardError, out.isPending, login, logout]);

  if (hardError) {
    return (
      <div className="grid min-h-[100dvh] place-items-center bg-background px-5" data-testid="state-auth-error">
        <div className="w-full max-w-sm rounded-xl border border-card-border bg-card p-5">
          <p className="font-semibold">Couldn't check your session</p>
          <p className="mt-1 text-sm text-muted-foreground">{errorMessage(q.error)} Nothing is shown until the server confirms who you are.</p>
          <button onClick={() => q.refetch()} disabled={q.isFetching} className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-60" data-testid="button-auth-retry">
            {q.isFetching ? "Checking..." : "Try again"}
          </button>
        </div>
      </div>
    );
  }

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}

export function displayName(user: AuthUser | null | undefined): string {
  if (!user) return "";
  const n = [user.firstName, user.lastName].filter(Boolean).join(" ");
  return n || user.email || "Owner";
}
