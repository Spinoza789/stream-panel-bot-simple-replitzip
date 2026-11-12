import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetAdminReseller, getGetAdminResellerQueryKey, getListAdminResellersQueryKey, useSetAdminResellerStatus, useAdjustAdminResellerCredits,
  getGetAdminOverviewQueryKey, useSetAdminResellerTrialLimits, type AdminReseller, type ResellerTrials, type TrialLimitOverrides,
} from "@workspace/api-client-react";
import { ArrowLeft, MessageSquarePlus, ScrollText, Users } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { AccountGroups } from "@/components/admin/account-groups";
import { Bar, CopyId, EmptyState, ErrorState, PageHeader, Panel, StatusBadge } from "@/components/admin/bits";
import { NewTicketDialog } from "@/components/admin/create";
import { LimitField, UNLIMITED } from "@/components/admin/subscriptions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, errorStatus, formatDateTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";
import { cn } from "@/lib/utils";

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="flex items-center justify-between border-b border-border py-1.5 text-sm last:border-0"><span className="text-muted-foreground">{label}</span><span className="num font-medium">{value}</span></div>;
}

const WINDOWS = [
  ["daily", "Per day", "last 24 hours"],
  ["weekly", "Per week", "last 7 days"],
  ["monthly", "Per month", "last 30 days"],
  ["active", "Running at once", "now"],
] as const;

/** This reseller's own trial allowance. Each window follows the default for all resellers unless set here. */
function TrialLimitsForm({ id, trials, onSaved }: { id: number; trials: ResellerTrials; onSaved: () => void }) {
  const { toast } = useToast();
  const save = useSetAdminResellerTrialLimits();
  const [draft, setDraft] = useState<TrialLimitOverrides>(trials.limits);
  const [reason, setReason] = useState("");
  useEffect(() => { setDraft(trials.limits); }, [trials.limits.daily, trials.limits.weekly, trials.limits.monthly, trials.limits.active]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = WINDOWS.some(([k]) => draft[k] !== trials.limits[k]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!changed || reason.trim().length < 3) return;
    save.mutate({ id: String(id), data: { ...draft, reason: reason.trim() } }, {
      onSuccess: () => { toast({ title: "Trial limits saved" }); setReason(""); onSaved(); },
    });
  };
  return (
    <form onSubmit={submit} className="card-shadow rounded-xl bg-card p-3 text-sm" data-testid="form-trial-limits">
      <p className="font-semibold">Free trial limits</p>
      <p className="mt-0.5 text-xs text-muted-foreground">Leave a row on Default to follow the limit for all resellers (Settings › Rate card), or set this reseller's own: unlimited, a number, or 0 to switch trials off.</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {WINDOWS.map(([key, label, span]) => {
          const cap = trials.effective[key];
          return (
            <LimitField key={key} label={label} testId={`trial-${key}`} value={draft[key]} fallback={trials.default[key]}
              onChange={(v) => setDraft({ ...draft, [key]: v })}
              hint={`Used ${trials.usage[key]}${cap === UNLIMITED ? "" : " of " + cap} (${span})`} />
          );
        })}
      </div>
      {changed && <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Reason (kept in the audit log)" className="mt-3 h-9" data-testid="input-trial-limit-reason" />}
      {save.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(save.error)}</p>}
      <Button type="submit" size="sm" className="mt-2" disabled={save.isPending || !changed || reason.trim().length < 3} data-testid="button-save-trial-limits">{save.isPending ? "Saving…" : "Save limits"}</Button>
    </form>
  );
}

function ResellerDetail() {
  const params = useParams<{ id: string }>();
  const id = /^[1-9][0-9]{0,18}$/.test(params.id ?? "") ? Number(params.id) : 0;
  const ready = useAdminReady();
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useGetAdminReseller(String(id), { query: { enabled: ready && id > 0, queryKey: getGetAdminResellerQueryKey(String(id)), ...LIVE } });
  const status = useSetAdminResellerStatus();
  const adjust = useAdjustAdminResellerCredits();
  const [reason, setReason] = useState("");
  const [movement, setMovement] = useState("");
  const [creditReason, setCreditReason] = useState("");
  const [requestKey] = useState(() => Math.random().toString(36).slice(2) + Date.now().toString(36));
  const [messaging, setMessaging] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: getGetAdminResellerQueryKey(String(id)) });
    qc.invalidateQueries({ queryKey: getListAdminResellersQueryKey() });
    qc.invalidateQueries({ queryKey: getGetAdminOverviewQueryKey() });
  };
  const d = q.data;
  const r: AdminReseller | undefined = d?.reseller;
  const suspend = (e: FormEvent) => {
    e.preventDefault();
    if (!r || reason.trim().length < 3) return;
    status.mutate({ id: String(id), data: { status: r.status === "suspended" ? "active" : "suspended", reason: reason.trim() } }, {
      onSuccess: (v) => { toast({ title: v.reseller.status === "suspended" ? "Reseller suspended" : "Reseller active" }); setReason(""); refresh(); },
    });
  };
  const credit = (e: FormEvent) => {
    e.preventDefault();
    const n = parseInt(movement, 10);
    if (!Number.isInteger(n) || n === 0 || creditReason.trim().length < 3) return;
    adjust.mutate({ id: String(id), data: { movement: n, reason: creditReason.trim(), requestKey } }, {
      onSuccess: () => { toast({ title: `${n > 0 ? "Added" : "Removed"} ${Math.abs(n)} credits` }); setMovement(""); setCreditReason(""); refresh(); },
    });
  };
  usePageMeta(r ? (r.username ? "@" + r.username : "Reseller " + r.telegramId) : "Reseller", "One reseller: credits, trial limits, subscriptions, trials and logs.");
  const back = <Link href="/resellers" className="inline-flex items-center gap-1 hover:text-foreground" data-testid="link-back-resellers"><ArrowLeft className="h-3.5 w-3.5" /> Resellers</Link>;
  if (!id || q.isError) {
    const missing = !id || errorStatus(q.error) === 404 || /not found/i.test(errorMessage(q.error));
    return (
      <>
        <PageHeader title={missing ? "Reseller not found" : "Reseller"} eyebrow={back} />
        {missing ? <Panel><EmptyState icon={<Users className="h-5 w-5" />} title="No reseller with this Telegram ID">Check the ID, or add them from the Resellers page.</EmptyState></Panel>
          : <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />}
      </>
    );
  }
  return (
    <>
      <PageHeader
        eyebrow={back}
        title={r ? (r.username ? "@" + r.username : "Reseller " + r.telegramId) : "Loading reseller"}
        description={<span className="inline-flex flex-wrap items-center gap-2">{r && <StatusBadge status={r.status} tone={r.status === "active" ? "success" : r.status === "pending" ? "attention" : "critical"} />}<span>Telegram ID</span><CopyId value={String(id)} label="Telegram ID" />{r && <span>· since {formatDateTime(r.createdAt)}</span>}</span>}
        actions={
          <>
            <Button variant="outline" asChild><Link href={`/logs?reseller=${id}`} data-testid="link-reseller-activity"><ScrollText className="mr-1.5 h-4 w-4" /> Activity log</Link></Button>
            <Button variant="outline" asChild><Link href={`/logs?tab=credits&reseller=${id}`} data-testid="link-reseller-credits"><ScrollText className="mr-1.5 h-4 w-4" /> Credit log</Link></Button>
            <Button onClick={() => setMessaging(true)} data-testid="button-reseller-ticket"><MessageSquarePlus className="mr-1.5 h-4 w-4" /> New ticket</Button>
          </>
        }
      />
      {!d ? <Panel><div className="space-y-2"><Bar className="h-4" /><Bar className="h-4 w-2/3" /><Bar className="h-4 w-1/2" /></div></Panel> : (
        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-3 lg:gap-5">
            <Panel title="Credits and customers">
              <Stat label="Available credits" value={r!.available} />
              <Stat label="Reserved" value={r!.reserved} />
              <Stat label="Customers (active / all)" value={`${r!.activeCustomers} / ${r!.customers}`} />
              <Stat label="Credits bought" value={r!.creditsBought} />
            </Panel>
            <Panel title="Activity">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">This month</h3>
              <Stat label="Credits used" value={d.stats.this_month.credits_used} />
              <Stat label="Tests created" value={d.stats.this_month.tests_created} />
              <Stat label="Tests converted" value={`${d.stats.this_month.tests_converted} (${d.stats.this_month.conversion_rate}%)`} />
              <h3 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">All time</h3>
              <Stat label="Credits used" value={d.stats.all_time.credits_used} />
              <Stat label="Tests converted" value={`${d.stats.all_time.tests_converted} of ${d.stats.all_time.tests_created}`} />
            </Panel>
            <Panel title="Free trials used">
              {WINDOWS.map(([key, label]) => <Stat key={key} label={label} value={`${d.trials.effective[key] === UNLIMITED ? d.trials.usage[key] + " used · unlimited" : d.trials.usage[key] + " of " + d.trials.effective[key]}${d.trials.limits[key] === null ? "" : " (own limit)"}`} />)}
            </Panel>
          </div>
          <div className="grid items-start gap-4 md:grid-cols-2 lg:gap-5 xl:grid-cols-3">
            <TrialLimitsForm id={id} trials={d.trials} onSaved={refresh} />
              <form onSubmit={credit} className="card-shadow rounded-xl bg-card p-3 text-sm">
                <p className="font-semibold">Adjust credits</p>
                <p className="mt-0.5 text-xs text-muted-foreground">Positive adds, negative removes. Reserved credits cannot be removed. Use this for bank transfers or goodwill.</p>
                <div className="mt-2 flex gap-2">
                  <Input value={movement} onChange={(e) => setMovement(e.target.value)} inputMode="numeric" placeholder="+10 or -5" className="h-9 w-28" data-testid="input-credit-movement" />
                  <Input value={creditReason} onChange={(e) => setCreditReason(e.target.value)} maxLength={500} placeholder="Reason, e.g. bank:REF123" className="h-9" data-testid="input-credit-reason" />
                </div>
                {adjust.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(adjust.error)}</p>}
                <Button type="submit" size="sm" className="mt-2" disabled={adjust.isPending || !/^[-+]?[1-9][0-9]*$/.test(movement) || creditReason.trim().length < 3} data-testid="button-adjust-credits">{adjust.isPending ? "Saving…" : "Apply"}</Button>
              </form>
              <form onSubmit={suspend} className="card-shadow rounded-xl bg-card p-3 text-sm">
                <p className="font-semibold">{r!.status === "suspended" ? "Reactivate" : "Suspend"} this reseller</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{r!.status === "suspended" ? "They will be able to buy, create and extend again." : "They keep their records but cannot buy, create or extend. The bot tells them."}</p>
                <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Reason (kept in the audit log)" className="mt-2 h-9" data-testid="input-status-reason" />
                {status.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(status.error)}</p>}
                <Button type="submit" variant={r!.status === "suspended" ? "default" : "destructive"} size="sm" className="mt-2" disabled={status.isPending || reason.trim().length < 3} data-testid="button-toggle-status">
                  {status.isPending ? "Saving…" : r!.status === "suspended" ? "Reactivate" : "Suspend"}
                </Button>
              </form>
          </div>
          <Panel title="Recent credit history" aside={<Link href={`/logs?tab=credits&reseller=${id}`} className="text-xs font-medium text-primary hover:underline">Full credit log</Link>}>
                {d.history.length === 0 ? <p className="text-sm text-muted-foreground">No movements yet.</p> : (
                  <ul className="divide-y divide-border text-sm">
                    {d.history.map((h, i) => (
                      <li key={i} className="flex items-start justify-between gap-3 py-1.5">
                        <div><div>{h.reason}</div><div className="text-xs text-muted-foreground">{formatDateTime(h.createdAt)}</div></div>
                        <span className={cn("num shrink-0 font-medium", h.movement > 0 ? "text-[#0c5132] dark:text-[#9fe2b8]" : "")}>{h.movement > 0 ? "+" : ""}{h.movement}</span>
                      </li>
                    ))}
                  </ul>
                )}
          </Panel>
          <div>
            <h2 className="mb-2 text-[15px] font-semibold">Subscriptions</h2>
            <AccountGroups kind="paid" reseller={id} />
          </div>
          <div>
            <h2 className="mb-2 text-[15px] font-semibold">Trials</h2>
            <AccountGroups kind="trial" reseller={id} />
          </div>
        </div>
      )}
      <NewTicketDialog open={messaging} onClose={() => setMessaging(false)} telegramId={String(id)} recipient={r?.username ? "@" + r.username : undefined} />
    </>
  );
}

export default function ResellerDetailPage() {
  return <AdminShell><ResellerDetail /></AdminShell>;
}
