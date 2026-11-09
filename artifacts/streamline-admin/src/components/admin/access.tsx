import { createContext, useContext, useState, type FormEvent, type ReactNode } from "react";
import { useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetAdminAccess,
  getGetAdminAccessQueryKey,
  useClaimAdminOwner,
  type AdminAccess,
} from "@workspace/api-client-react";
import { Eye, EyeOff, KeyRound, LogOut, ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Bar, ErrorState, Logo } from "./bits";
import { errorMessage, errorStatus } from "@/lib/format";
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

  if (access.canClaimOwner) return <ClaimOwner />;

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
          <Step n={2}>
            Store a one-time setup code as the workspace secret <code className="rounded bg-muted px-1 font-mono text-xs">STREAMBOT_WEB_BOOTSTRAP_CODE</code>, and add the owner's email to the server allowlist{email ? <> (you're signed in as <b className="font-mono text-xs">{email}</b>)</> : null}.
          </Step>
          <Step n={3}>Restart the API server and reload this page. If this account is allowed, a form to enter the setup code appears here.</Step>
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
          ? <>You're signed in{email ? <> as <b className="font-mono text-xs text-foreground">{email}</b></> : null}, but the owner is already set and it's a different account. Sign out and use the owner's Replit account.</>
          : "The server couldn't confirm your session. Sign out and sign in again."}
      </p>
    </GateFrame>
  );
}

function ClaimOwner() {
  const qc = useQueryClient();
  const [, setLocation] = useLocation();
  const claim = useClaimAdminOwner();
  const [code, setCode] = useState("");
  const [show, setShow] = useState(false);
  const len = code.length;
  const valid = len >= 20 && len <= 200;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || claim.isPending) return;
    claim.mutate(
      { data: { code } },
      {
        onSuccess: () => {
          setCode("");
          qc.invalidateQueries({ queryKey: getGetAdminAccessQueryKey() });
          setLocation("/dashboard");
        },
        onError: () => setCode(""),
      },
    );
  };

  const st = claim.isError ? errorStatus(claim.error) : undefined;
  const failMsg =
    st === 401 || st === 403
      ? "That code wasn't accepted, or this account isn't on the owner allowlist."
      : st === 409
        ? "An owner has already been set up."
        : st === 429
          ? "Too many attempts. Wait a few minutes and try again."
          : "The claim couldn't be completed. Try again.";

  return (
    <GateFrame>
      <Icon tone="teal"><ShieldCheck className="h-5 w-5" /></Icon>
      <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-claim-owner">Set up the first owner</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        This account is on the owner allowlist. Enter the setup code stored on the server to link the desk to this Replit account. After that, only this account can open it.
      </p>
      <form onSubmit={submit} className="mt-6 space-y-3 rounded-xl border border-border bg-card p-4" autoComplete="off">
        <label htmlFor="owner-code" className="text-sm font-medium">Setup code</label>
        <div className="relative">
          <Input
            id="owner-code"
            name="owner-setup-code"
            type={show ? "text" : "password"}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            minLength={20}
            maxLength={200}
            autoComplete="off"
            spellCheck={false}
            autoCapitalize="off"
            className="pr-10 font-mono"
            data-testid="input-owner-code"
          />
          <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground" aria-label={show ? "Hide code" : "Show code"} data-testid="button-toggle-code">
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        <p className="text-xs text-muted-foreground">{len > 0 && len < 20 ? `Too short. The code is at least 20 characters.` : "20 to 200 characters. It's sent once and not stored in this browser."}</p>
        {claim.isError && <p className="rounded-lg bg-[hsl(4_70%_97%)] px-3 py-2 text-sm text-[hsl(4_60%_30%)]" data-testid="text-claim-error">{failMsg}</p>}
        <Button type="submit" className="w-full" disabled={!valid || claim.isPending} data-testid="button-claim-owner">
          {claim.isPending ? "Verifying…" : "Claim ownership"}
        </Button>
      </form>
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
