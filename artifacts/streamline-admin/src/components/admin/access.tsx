import { createContext, useContext, type ReactNode } from "react";
import {
  useGetAdminAccess,
  getGetAdminAccessQueryKey,
  type AdminAccess,
} from "@workspace/api-client-react";
import { KeyRound, LogOut, ShieldAlert, ShieldX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Bar, ErrorState, Logo } from "./bits";
import { errorMessage } from "@/lib/format";
import { useAuth } from "@/lib/auth";

const ReadyCtx = createContext(false);
export const useAdminReady = () => useContext(ReadyCtx);

export const LIVE = { refetchInterval: 30_000, refetchOnWindowFocus: true } as const;

export function AccessGate({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const access = useGetAdminAccess({
    query: { enabled: isAuthenticated, queryKey: getGetAdminAccessQueryKey(), refetchOnWindowFocus: true, retry: 1 },
  });

  if (!isAuthenticated || access.isLoading) return <GateSkeleton />;
  if (access.isError) {
    return (
      <GateFrame>
        <ErrorState title="Couldn't verify admin access" message={errorMessage(access.error)} onRetry={() => access.refetch()} />
        <p className="mt-4 text-sm text-muted-foreground">Access is checked on the server before any order data is shown. Nothing is displayed until that check succeeds.</p>
      </GateFrame>
    );
  }
  const a = access.data;
  if (!a) return <GateSkeleton />;
  if (!a.authorized) return <Denied access={a} />;
  return <ReadyCtx.Provider value={true}>{children}</ReadyCtx.Provider>;
}

function GateSkeleton() {
  return (
    <div className="grid min-h-[100dvh] place-items-center bg-background" data-testid="state-gate-loading">
      <div className="w-72 space-y-3">
        <Logo />
        <Bar className="h-2 w-full" />
        <Bar className="h-2 w-2/3" />
        <p className="text-xs text-muted-foreground">Checking owner access…</p>
      </div>
    </div>
  );
}

function GateFrame({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  return (
    <div className="grain min-h-[100dvh] bg-background">
      <header className="flex items-center justify-between border-b border-border bg-card px-5 py-3">
        <Logo />
        <div className="flex items-center gap-3">
          {user?.email && <span className="hidden text-sm text-muted-foreground sm:inline">{user.email}</span>}
          <Button variant="outline" size="sm" onClick={logout} data-testid="button-signout-gate">
            <LogOut className="mr-1.5 h-3.5 w-3.5" /> Sign out
          </Button>
        </div>
      </header>
      <main className="rise relative mx-auto max-w-xl px-5 py-16">{children}</main>
    </div>
  );
}

function Icon({ tone, children }: { tone: "gold" | "red" | "teal"; children: ReactNode }) {
  const c = tone === "gold" ? "bg-[hsl(42_85%_84%)] text-[hsl(32_70%_22%)]" : tone === "red" ? "bg-[hsl(4_75%_91%)] text-[hsl(4_65%_32%)]" : "bg-[hsl(176_40%_90%)] text-primary";
  return <div className={`mb-5 grid h-11 w-11 place-items-center rounded-xl ${c}`}>{children}</div>;
}

function Denied({ access }: { access: AdminAccess }) {
  const { user } = useAuth();
  const email = user?.email;
  // Access is never granted from the browser; canClaimOwner is ignored.

  if (!access.authConfigured || !access.ownerConfigured) {
    return (
      <GateFrame>
        <Icon tone="gold"><KeyRound className="h-5 w-5" /></Icon>
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-setup-required">Owner access isn't configured yet</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The desk stays locked until a first owner is set up on the server. It can't be granted from the browser, and signing in first does not make you the owner.
        </p>
        <ol className="mt-6 space-y-3 text-sm">
          <Step n={1} done={access.authConfigured}>Server-side sign-in is {access.authConfigured ? "configured" : <b>not configured</b>}.</Step>
          <Step n={2}>Configure the approved owner email and the workspace setup code on the server, then restart it.</Step>
          <Step n={3}>Sign out and open the setup page to create the owner's local account with that code.</Step>
        </ol>
      </GateFrame>
    );
  }
  return (
    <GateFrame>
      <Icon tone="red">{access.authenticated ? <ShieldX className="h-5 w-5" /> : <ShieldAlert className="h-5 w-5" />}</Icon>
      <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-unauthorized">This account can't open the desk</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {access.authenticated
          ? <>You're signed in{email ? <> as <b className="font-mono text-xs text-foreground">{email}</b></> : null}, but this account isn't authorized to open the desk. Sign out and sign in with the owner account.</>
          : "The server couldn't confirm your session. Sign out and sign in again."}
      </p>
    </GateFrame>
  );
}

function Step({ n, done, children }: { n: number; done?: boolean; children: ReactNode }) {
  return (
    <li className="flex gap-3 rounded-lg border border-border bg-card p-3">
      <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full font-mono text-xs ${done ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>{n}</span>
      <span className="leading-relaxed">{children}</span>
    </li>
  );
}
