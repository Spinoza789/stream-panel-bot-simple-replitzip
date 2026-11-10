import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Redirect, useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetPasswordAuthStatus,
  getGetPasswordAuthStatusQueryKey,
  usePasswordLogin,
  useSetupPasswordOwner,
  getGetCurrentAuthUserQueryKey,
  getGetAdminAccessQueryKey,
  type AuthUserEnvelope,
} from "@workspace/api-client-react";
import { ArrowRight, KeyRound, ServerCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Bar, ErrorState, Logo } from "@/components/admin/bits";
import { Field, FormAlert, emailError, newPasswordError, usernameError } from "@/components/auth/fields";
import { useAuth } from "@/lib/auth";
import { errorMessage, errorStatus } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

function Frame({ title, sub, children }: { title: string; sub: ReactNode; children: ReactNode }) {
  return (
    <div className="grain relative min-h-[100dvh] overflow-hidden bg-background">
      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Link href="/" data-testid="link-home"><Logo /></Link>
      </header>
      <main className="rise relative z-10 mx-auto max-w-md px-5 pb-16 pt-6 md:pt-14">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{sub}</p>
        <div className="mt-7 rounded-xl border border-card-border bg-card p-5 shadow-[0_1px_3px_hsl(176_20%_20%/0.06)]">{children}</div>
      </main>
      <div className="pointer-events-none absolute -right-40 top-40 h-[520px] w-[520px] rounded-full bg-[hsl(42_74%_66%/0.18)] blur-3xl" />
    </div>
  );
}

function useStatus() {
  return useGetPasswordAuthStatus({ query: { queryKey: getGetPasswordAuthStatusQueryKey(), retry: 1 } });
}

function useAfterAuth() {
  const qc = useQueryClient();
  const [, setLocation] = useLocation();
  return async (env: AuthUserEnvelope) => {
    qc.setQueryData(getGetCurrentAuthUserQueryKey(), env);
    await Promise.all([
      qc.invalidateQueries({ queryKey: getGetCurrentAuthUserQueryKey() }),
      qc.invalidateQueries({ queryKey: getGetAdminAccessQueryKey() }),
      qc.invalidateQueries({ queryKey: getGetPasswordAuthStatusQueryKey() }),
    ]);
    setLocation("/dashboard");
  };
}

function StatusSkeleton() {
  return <div className="space-y-3" data-testid="state-status-loading"><Bar className="h-10" /><Bar className="h-10" /><Bar className="h-10 w-1/2" /></div>;
}

function Unavailable() {
  return (
    <div data-testid="text-setup-unavailable">
      <div className="mb-4 grid h-10 w-10 place-items-center rounded-xl bg-[hsl(42_85%_84%)] text-[hsl(32_70%_22%)]"><ServerCog className="h-5 w-5" /></div>
      <p className="font-semibold">Server configuration needed</p>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
        No owner account exists yet, and owner setup is not enabled on the server. Configure the approved owner email and the workspace setup code on the server, restart it, then reload this page. There is no way around this from the browser.
      </p>
    </div>
  );
}

export function SignInPage() {
  usePageMeta("Sign in", "Sign in to the Streamline owner desk.");
  const { isAuthenticated, isLoading } = useAuth();
  const status = useStatus();
  const login = usePasswordLogin();
  const after = useAfterAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);

  if (!isLoading && isAuthenticated) return <Redirect to="/dashboard" />;

  const idErr = touched && identifier.trim().length < 3 ? "Enter your username or email." : undefined;
  const pwErr = touched && !password ? "Enter your password." : undefined;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (identifier.trim().length < 3 || !password || login.isPending) return;
    login.mutate(
      { data: { identifier: identifier.trim(), password } },
      { onSuccess: (env) => { setPassword(""); void after(env); }, onError: () => setPassword("") },
    );
  };

  const st = login.isError ? errorStatus(login.error) : undefined;
  const fail = st === 401 || st === 403 ? "That username, email or password isn't right." : st === 429 ? "Too many attempts. Wait a few minutes and try again." : login.isError ? errorMessage(login.error) : "";

  const s = status.data;
  return (
    <Frame title="Sign in" sub="Use the owner account for this desk: username or email, and password.">
      {status.isLoading ? <StatusSkeleton /> : status.isError ? (
        <ErrorState title="Couldn't reach the server" message={errorMessage(status.error)} onRetry={() => status.refetch()} />
      ) : s && !s.configured ? (
        s.setupAvailable ? (
          <div data-testid="text-setup-required">
            <div className="mb-4 grid h-10 w-10 place-items-center rounded-xl bg-[hsl(176_40%_90%)] text-primary"><KeyRound className="h-5 w-5" /></div>
            <p className="font-semibold">Setup required</p>
            <p className="mt-1 text-sm text-muted-foreground">No owner account exists yet. Create it once with the server setup code.</p>
            <Link href="/setup" className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" data-testid="link-setup">
              Set up owner <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        ) : <Unavailable />
      ) : (
        <form onSubmit={submit} noValidate className="space-y-4" data-testid="form-sign-in">
          <Field label="Username or email" testid="input-identifier" name="username" autoComplete="username" value={identifier} maxLength={254} onChange={(e) => setIdentifier(e.target.value)} error={idErr} autoFocus />
          <Field label="Password" testid="input-password" name="password" secret autoComplete="current-password" value={password} maxLength={128} onChange={(e) => setPassword(e.target.value)} error={pwErr} />
          {fail && <FormAlert testid="text-login-error">{fail}</FormAlert>}
          <Button type="submit" className="h-10 w-full" disabled={login.isPending} data-testid="button-sign-in">
            {login.isPending ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      )}
    </Frame>
  );
}

export function SetupPage() {
  usePageMeta("Owner setup", "Create the single owner account for Streamline Admin.");
  const { isAuthenticated, isLoading } = useAuth();
  const status = useStatus();
  const setup = useSetupPasswordOwner();
  const after = useAfterAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [code, setCode] = useState("");
  const [touched, setTouched] = useState(false);

  if (!isLoading && isAuthenticated) return <Redirect to="/dashboard" />;
  if (status.data?.configured) return <Redirect to="/sign-in" />;

  const errs = {
    username: usernameError(username),
    email: emailError(email.trim()),
    password: newPasswordError(password),
    confirm: confirm !== password ? "Passwords don't match." : undefined,
    code: code.length < 20 || code.length > 200 ? "The setup code is 20 to 200 characters." : undefined,
  };
  const valid = !Object.values(errs).some(Boolean);
  const show = (k: keyof typeof errs) => (touched ? errs[k] : undefined);
  const clearSecrets = () => { setPassword(""); setConfirm(""); setCode(""); };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || setup.isPending) return;
    setup.mutate(
      { data: { username, email: email.trim(), password, setupCode: code } },
      { onSuccess: (env) => { clearSecrets(); void after(env); }, onError: () => { clearSecrets(); setTouched(false); } },
    );
  };

  const st = setup.isError ? errorStatus(setup.error) : undefined;
  const fail = st === 401 || st === 403 ? "The setup code wasn't accepted, or this email isn't the approved owner email." : st === 409 ? "An owner account already exists. Sign in instead." : st === 429 ? "Too many attempts. Wait a few minutes and try again." : setup.isError ? errorMessage(setup.error) : "";

  return (
    <Frame title="Set up the owner" sub="Create the one local account that opens this desk. You need the approved owner email and the setup code stored on the server.">
      {status.isLoading ? <StatusSkeleton /> : status.isError ? (
        <ErrorState title="Couldn't reach the server" message={errorMessage(status.error)} onRetry={() => status.refetch()} />
      ) : !status.data?.setupAvailable ? <Unavailable /> : (
        <form onSubmit={submit} noValidate className="space-y-4" data-testid="form-setup">
          <Field label="Username" testid="input-username" name="username" autoComplete="username" value={username} maxLength={32} onChange={(e) => setUsername(e.target.value)} error={show("username")} hint="3 to 32 characters." autoFocus />
          <Field label="Email" testid="input-email" type="email" name="email" autoComplete="email" value={email} maxLength={254} onChange={(e) => setEmail(e.target.value)} error={show("email")} />
          <Field label="Password" testid="input-new-password" name="new-password" secret autoComplete="new-password" value={password} maxLength={128} onChange={(e) => setPassword(e.target.value)} error={show("password")} hint="12 to 128 characters." />
          <Field label="Confirm password" testid="input-confirm-password" name="confirm-password" secret autoComplete="new-password" value={confirm} maxLength={128} onChange={(e) => setConfirm(e.target.value)} error={show("confirm")} />
          <Field label="Setup code" testid="input-setup-code" name="setup-code" secret autoComplete="off" className="font-mono" value={code} maxLength={200} onChange={(e) => setCode(e.target.value)} error={show("code")} hint="Sent once. Never stored in this browser." />
          {fail && <FormAlert testid="text-setup-error">{fail}</FormAlert>}
          <Button type="submit" className="h-10 w-full" disabled={setup.isPending} data-testid="button-setup">
            {setup.isPending ? "Creating account..." : "Create owner account"}
          </Button>
          <p className="text-center text-xs text-muted-foreground">Already set up? <Link href="/sign-in" className="font-medium text-primary underline-offset-2 hover:underline" data-testid="link-sign-in">Sign in</Link></p>
        </form>
      )}
    </Frame>
  );
}

/** /sign-up has no public signup: route to setup when available, otherwise sign in. */
export function SignUpRedirect() {
  const status = useStatus();
  if (status.isLoading) return <div className="grid min-h-[100dvh] place-items-center"><div className="w-72"><StatusSkeleton /></div></div>;
  const s = status.data;
  return <Redirect to={s && !s.configured && s.setupAvailable ? "/setup" : "/sign-in"} />;
}
