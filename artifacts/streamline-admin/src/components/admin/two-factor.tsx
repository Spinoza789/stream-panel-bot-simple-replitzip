import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useGetPasswordAccount, getGetPasswordAccountQueryKey, useSetupTotp, useEnableTotp, useDisableTotp, type TotpSetup } from "@workspace/api-client-react";
import { ShieldCheck, ShieldOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Bar, ErrorState, Panel } from "./bits";
import { useAdminReady } from "./access";
import { useToast } from "@/hooks/use-toast";
import { errorMessage } from "@/lib/format";

/** Authenticator-app second factor for the owner login. Enrolment is confirmed with a live code before it is saved. */
export function TwoFactorPanel() {
  const ready = useAdminReady();
  const qc = useQueryClient();
  const { toast } = useToast();
  const acc = useGetPasswordAccount({ query: { enabled: ready, queryKey: getGetPasswordAccountQueryKey() } });
  const setup = useSetupTotp();
  const enable = useEnableTotp();
  const disable = useDisableTotp();
  const [pending, setPending] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const done = (title: string) => { setPending(null); setCode(""); setPassword(""); qc.invalidateQueries({ queryKey: getGetPasswordAccountQueryKey() }); toast({ title, description: "Other sessions were signed out." }); };
  const start = () => setup.mutate({ data: {} }, { onSuccess: (s) => setPending(s) });
  const confirm = (e: FormEvent) => { e.preventDefault(); if (!/^[0-9]{6}$/.test(code)) return; enable.mutate({ data: { code } }, { onSuccess: () => done("Two-factor sign-in enabled") }); };
  const off = (e: FormEvent) => { e.preventDefault(); if (!/^[0-9]{6}$/.test(code) || !password) return; disable.mutate({ data: { currentPassword: password, code } }, { onSuccess: () => done("Two-factor sign-in disabled") }); };
  const enabled = acc.data?.totpEnabled;
  return (
    <Panel title="Two-factor sign-in">
      {acc.isError ? <ErrorState message={errorMessage(acc.error)} onRetry={() => acc.refetch()} /> : !acc.data ? <Bar className="h-16" /> : (
        <div className="text-sm">
          <div className="flex items-start gap-3">
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${enabled ? "bg-[#cdfee1] text-[#0c5132]" : "bg-[#ffd79d] text-[#5e4200]"}`}>{enabled ? <ShieldCheck className="h-5 w-5" /> : <ShieldOff className="h-5 w-5" />}</span>
            <div>
              <p className="font-medium" data-testid="text-totp-status">{enabled ? "On: a code from your authenticator app is required at sign-in." : "Off: anyone with the password can sign in."}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">Works with Google Authenticator, Authy, 1Password and similar apps. This desk controls payouts and the panel, so turning it on is strongly recommended.</p>
            </div>
          </div>
          {!enabled && !pending && (
            <Button className="mt-4" size="sm" onClick={start} disabled={setup.isPending} data-testid="button-totp-start">{setup.isPending ? "Preparing…" : "Set up authenticator"}</Button>
          )}
          {setup.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(setup.error)}</p>}
          {!enabled && pending && (
            <form onSubmit={confirm} className="mt-4 space-y-3">
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                <li>Open your authenticator app and add an account.</li>
                <li>Scan this code, or type the key by hand.</li>
                <li>Enter the 6-digit code the app shows to finish.</li>
              </ol>
              <div className="flex flex-wrap items-center gap-4">
                {pending.qr ? <img src={pending.qr} alt="Authenticator enrolment QR code" width={160} height={160} className="rounded-lg border border-border bg-white p-1" /> : null}
                <div className="min-w-0">
                  <p className="text-xs text-muted-foreground">Key</p>
                  <code className="block break-all rounded-md bg-muted px-2 py-1 font-mono text-xs" data-testid="text-totp-secret">{pending.secret.match(/.{1,4}/g)?.join(" ")}</code>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="h-9 w-32 font-mono tracking-widest" data-testid="input-totp-code" />
                <Button type="submit" size="sm" disabled={enable.isPending || code.length !== 6} data-testid="button-totp-enable">{enable.isPending ? "Checking…" : "Turn on"}</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => { setPending(null); setCode(""); }}>Cancel</Button>
              </div>
              {enable.isError && <p className="text-xs text-destructive">{errorMessage(enable.error)}</p>}
            </form>
          )}
          {enabled && (
            <form onSubmit={off} className="mt-4 space-y-2 border-t border-border pt-3">
              <p className="text-xs text-muted-foreground">To turn it off, confirm your password and a current code.</p>
              <div className="flex flex-wrap items-center gap-2">
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" placeholder="Current password" className="h-9 w-48" data-testid="input-totp-password" />
                <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="h-9 w-32 font-mono tracking-widest" data-testid="input-totp-disable-code" />
                <Button type="submit" size="sm" variant="destructive" disabled={disable.isPending || code.length !== 6 || !password} data-testid="button-totp-disable">{disable.isPending ? "Checking…" : "Turn off"}</Button>
              </div>
              {disable.isError && <p className="text-xs text-destructive">{errorMessage(disable.error)}</p>}
            </form>
          )}
        </div>
      )}
    </Panel>
  );
}
