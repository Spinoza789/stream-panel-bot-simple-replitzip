import { useGetAdminStatus, getGetAdminStatusQueryKey, useGetAdminAccess, getGetAdminAccessQueryKey } from "@workspace/api-client-react";
import { Check, Minus } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { OwnerLoginPanel } from "@/components/admin/owner-login";
import { RateCardPanel } from "@/components/admin/rate-card";
import { TwoFactorPanel } from "@/components/admin/two-factor";
import { Bar, ErrorState, PageHeader, Panel } from "@/components/admin/bits";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

function Row({ label, on, help, testid }: { label: string; on: boolean; help: string; testid: string }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3" data-testid={testid}>
      <span className={cn("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full", on ? "bg-[#cdfee1] text-[#0c5132]" : "bg-muted text-muted-foreground")}>
        {on ? <Check className="h-3 w-3" strokeWidth={3} /> : <Minus className="h-3 w-3" strokeWidth={3} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">{label}</p>
          <span className={cn("text-xs font-medium", on ? "text-[#0c5132]" : "text-muted-foreground")}>{on ? "Configured" : "Off"}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">{help}</p>
      </div>
    </div>
  );
}

function Settings() {
  usePageMeta("Settings", "Configuration readiness and owner login settings for UKCTV Admin.");
  const ready = useAdminReady();
  const st = useGetAdminStatus({ query: { enabled: ready, queryKey: getGetAdminStatusQueryKey(), ...LIVE } });
  const acc = useGetAdminAccess({ query: { enabled: ready, queryKey: getGetAdminAccessQueryKey() } });
  const s = st.data;
  return (
    <>
      <PageHeader title="Settings" description="Prices, sign-in security and what the server is configured to do. Readiness flags are configuration, not a live health check." />
      <div className="mb-5 grid gap-5 lg:grid-cols-[1fr_340px]">
        <RateCardPanel />
        <TwoFactorPanel />
      </div>
      {st.isError ? (
        <ErrorState message={errorMessage(st.error)} onRetry={() => st.refetch()} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
          <Panel title="Readiness" flush aside={s ? <span className="font-mono text-xs text-muted-foreground">mode: {s.mode}</span> : undefined}>
            {!s ? (
              <div className="space-y-4 p-4">{Array.from({ length: 6 }).map((_, i) => <Bar key={i} className="h-5" />)}</div>
            ) : (
              <div className="divide-y divide-border">
                <Row testid="status-workers" label="Background workers" on={s.workersActive} help="Workers pick up queued orders. When off, recovered trials stay queued." />
                <Row testid="status-panel-configured" label="Panel connection" on={s.panelConfigured} help="Credentials for the account panel are set. Values are never shown here." />
                <Row testid="status-panel-writes" label="Panel writes" on={s.panelWrites} help="Whether workers may create accounts on the panel." />
                <Row testid="status-telegram" label="Telegram bot" on={s.telegramEnabled} help="Bot delivery and messaging are enabled in configuration." />
                <Row testid="status-reseller-schema" label="Reseller schema" on={s.resellerSchema} help="Reseller tables are present in the database." />
                <Row testid="status-notification-schema" label="Notification schema" on={s.notificationSchema} help="Notification tables are present in the database." />
                <div className="flex items-center justify-between px-4 py-3 text-sm">
                  <span className="font-medium">Database</span>
                  <span className="font-mono text-xs" data-testid="text-database">{s.database}</span>
                </div>
              </div>
            )}
          </Panel>
          <div className="space-y-5">
          <Panel title="Owner access">
            {acc.data ? (
              <dl className="space-y-2 text-sm">
                {([["Signed in", acc.data.authenticated], ["Sign-in verification", acc.data.authConfigured], ["Owner configured", acc.data.ownerConfigured], ["Authorized", acc.data.authorized]] as const).map(([k, v]) => (
                  <div key={k} className="flex justify-between"><dt className="text-muted-foreground">{k}</dt><dd className={v ? "font-medium text-[#0c5132]" : "text-muted-foreground"}>{v ? "Yes" : "No"}</dd></div>
                ))}
              </dl>
            ) : <Bar className="h-20" />}
            <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
              The desk opens for one local owner account, created once with the server setup code. Access can't be granted from the browser. No Telegram admin role is required.
            </p>
          </Panel>
          <OwnerLoginPanel />
          </div>
        </div>
      )}
    </>
  );
}

export default function SettingsPage() {
  return <AdminShell><Settings /></AdminShell>;
}
