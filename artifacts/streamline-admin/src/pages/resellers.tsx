import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useListAdminResellers, getListAdminResellersQueryKey, useGetAdminReseller, getGetAdminResellerQueryKey,
  useSetAdminResellerStatus, useAdjustAdminResellerCredits, getGetAdminOverviewQueryKey,
  useSetAdminResellerTrialLimits, useListAdminSubscriptions, getListAdminSubscriptionsQueryKey,
  type AdminReseller, type AdminSubscription, type ListAdminResellersParams, type ResellerTrials, type TrialLimitOverrides,
} from "@workspace/api-client-react";
import { Link } from "wouter";
import { LimitField, UNLIMITED } from "@/components/admin/subscriptions";
import { SubscriptionDialog, SubscriptionsTable } from "@/pages/subscriptions";
import { ChevronLeft, ChevronRight, Search, Users, X } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, CopyId, EmptyState, ErrorState, PageHeader, Panel, StatusBadge } from "@/components/admin/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, formatDateTime, relativeTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";
import { cn } from "@/lib/utils";

function ResellersList() {
  usePageMeta("Resellers", "Every reseller with balance, customers and last activity. Suspend, reactivate or adjust credits.");
  const ready = useAdminReady();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setQ(text.trim().slice(0, 80)); setPage(1); }, 300);
    return () => clearTimeout(timer.current);
  }, [text]);
  const params: ListAdminResellersParams = { page };
  if (q) params.q = q;
  const list = useListAdminResellers(params, { query: { enabled: ready, queryKey: getListAdminResellersQueryKey(params), placeholderData: (p) => p, ...LIVE } });
  const d = list.data;
  return (
    <>
      <PageHeader title="Resellers" description="Who sells for you, what they hold in credits and how many customers they look after. Actions are logged in the audit trail." />
      <Panel flush>
        <div className="flex flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
          <p className="text-sm text-muted-foreground">{d ? `${d.items.length}${d.more ? "+" : ""} on this page` : ""}</p>
          <div className="relative w-full md:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)} placeholder="Telegram ID, username or status" className="h-8 pl-8 pr-8 text-[13px]" data-testid="input-reseller-search" />
            {text && <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear"><X className="h-4 w-4" /></button>}
          </div>
        </div>
        {list.isError ? (
          <div className="p-4"><ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} /></div>
        ) : d && d.items.length === 0 ? (
          <EmptyState icon={<Users className="h-5 w-5" />} title={q ? "No resellers match" : "No resellers yet"}>
            {q ? "Try a Telegram ID or username." : "Anyone who buys a credit pack in the bot becomes a reseller and appears here."}
          </EmptyState>
        ) : (
          <div className={cn("overflow-x-auto transition-opacity", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Reseller</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Available</th>
                  <th className="px-3 py-2 text-right font-medium">Reserved</th>
                  <th className="px-3 py-2 text-right font-medium">Customers</th>
                  <th className="px-3 py-2 text-right font-medium">Credits bought</th>
                  <th className="px-3 py-2 font-medium">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {list.isLoading && Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="border-b border-border last:border-0">{Array.from({ length: 7 }).map((_, j) => <td key={j} className="px-3 py-3 first:px-4"><Bar className="h-3.5" /></td>)}</tr>
                ))}
                {!list.isLoading && d?.items.map((r) => (
                  <tr key={r.telegramId} onClick={() => setOpen(r.telegramId)} data-testid={`row-reseller-${r.telegramId}`} className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5">
                    <td className="px-4 py-2.5"><div className="font-medium">{r.username ? "@" + r.username : "ID " + r.telegramId}</div><div className="font-mono text-[11px] text-muted-foreground">{r.telegramId}</div></td>
                    <td className="px-3 py-2.5"><StatusBadge status={r.status} tone={r.status === "active" ? "success" : r.status === "pending" ? "attention" : "critical"} /></td>
                    <td className="num px-3 py-2.5 text-right font-medium">{r.available}</td>
                    <td className="num px-3 py-2.5 text-right text-muted-foreground">{r.reserved}</td>
                    <td className="num px-3 py-2.5 text-right">{r.activeCustomers} <span className="text-xs text-muted-foreground">/ {r.customers}</span></td>
                    <td className="num px-3 py-2.5 text-right">{r.creditsBought}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap"><div className="num">{formatDateTime(r.lastActivity)}</div><div className="text-xs text-muted-foreground">{relativeTime(r.lastActivity)}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d && (d.more || page > 1) && (
          <div className="flex items-center justify-end gap-1 border-t border-border px-4 py-2.5 text-sm">
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
            <span className="num px-2 text-muted-foreground">Page {page}</span>
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={!d.more} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        )}
      </Panel>
      {open !== null && <ResellerDialog id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

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

/** The accounts this reseller created: subscriptions and trials, newest first. */
function ResellerAccounts({ id }: { id: number }) {
  const params = { reseller: id, page: 1 };
  const list = useListAdminSubscriptions(params, { query: { queryKey: getListAdminSubscriptionsQueryKey(params) } });
  const [open, setOpen] = useState<AdminSubscription | null>(null);
  const d = list.data;
  return (
    <div className="md:col-span-2">
      <div className="mb-1 flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Subscriptions and trials{d ? ` (${d.total})` : ""}</h3>
        {d && d.total > d.items.length && <Link href={`/subscriptions?reseller=${id}`} className="text-xs font-medium text-primary hover:underline">View all {d.total}</Link>}
      </div>
      {list.isError ? <ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} />
        : d && d.items.length === 0 ? <p className="text-sm text-muted-foreground">This reseller has not created any accounts yet.</p>
        : <div className="card-shadow overflow-hidden rounded-xl bg-card"><SubscriptionsTable items={d?.items} loading={list.isLoading} onOpen={setOpen} compact /></div>}
      {d && d.total > 0 && <p className="mt-1 text-xs text-muted-foreground">{d.active} active · {d.trials} trial{d.trials === 1 ? "" : "s"} · {d.total - d.trials} subscription{d.total - d.trials === 1 ? "" : "s"}</p>}
      {open && <SubscriptionDialog s={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function ResellerDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useGetAdminReseller(String(id), { query: { queryKey: getGetAdminResellerQueryKey(String(id)) } });
  const status = useSetAdminResellerStatus();
  const adjust = useAdjustAdminResellerCredits();
  const [reason, setReason] = useState("");
  const [movement, setMovement] = useState("");
  const [creditReason, setCreditReason] = useState("");
  const [requestKey] = useState(() => Math.random().toString(36).slice(2) + Date.now().toString(36));
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
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-h-[90dvh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{r ? (r.username ? "@" + r.username : "Reseller " + r.telegramId) : "Reseller"}</DialogTitle>
          <DialogDescription>Telegram ID <CopyId value={String(id)} label="Telegram ID" /> · <Link href={`/logs?reseller=${id}`} className="font-medium text-primary hover:underline" data-testid="link-reseller-activity">Activity log</Link> · <Link href={`/logs?tab=credits&reseller=${id}`} className="font-medium text-primary hover:underline" data-testid="link-reseller-credits">Credit log</Link></DialogDescription>
        </DialogHeader>
        {q.isError && <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />}
        {!d ? <div className="space-y-2"><Bar className="h-4" /><Bar className="h-4 w-2/3" /></div> : (
          <div className="grid gap-5 md:grid-cols-2">
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm"><StatusBadge status={r!.status} tone={r!.status === "active" ? "success" : r!.status === "pending" ? "attention" : "critical"} /><span className="text-muted-foreground">since {formatDateTime(r!.createdAt)}</span></div>
              <Stat label="Available credits" value={r!.available} />
              <Stat label="Reserved" value={r!.reserved} />
              <Stat label="Customers (active / all)" value={`${r!.activeCustomers} / ${r!.customers}`} />
              <Stat label="Credits bought" value={r!.creditsBought} />
              <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">This month</h3>
              <Stat label="Credits used" value={d.stats.this_month.credits_used} />
              <Stat label="Tests created" value={d.stats.this_month.tests_created} />
              <Stat label="Tests converted" value={`${d.stats.this_month.tests_converted} (${d.stats.this_month.conversion_rate}%)`} />
              <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">All time</h3>
              <Stat label="Credits used" value={d.stats.all_time.credits_used} />
              <Stat label="Tests converted" value={`${d.stats.all_time.tests_converted} of ${d.stats.all_time.tests_created}`} />
              <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Free trials allowed</h3>
              {WINDOWS.map(([key, label]) => <Stat key={key} label={label} value={`${d.trials.effective[key] === UNLIMITED ? d.trials.usage[key] + " used · unlimited" : d.trials.usage[key] + " of " + d.trials.effective[key]}${d.trials.limits[key] === null ? "" : " (own limit)"}`} />)}
            </div>
            <div className="space-y-4">
              <form onSubmit={suspend} className="card-shadow rounded-xl bg-card p-3 text-sm">
                <p className="font-semibold">{r!.status === "suspended" ? "Reactivate" : "Suspend"} this reseller</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{r!.status === "suspended" ? "They will be able to buy, create and extend again." : "They keep their records but cannot buy, create or extend. The bot tells them."}</p>
                <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Reason (kept in the audit log)" className="mt-2 h-9" data-testid="input-status-reason" />
                {status.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(status.error)}</p>}
                <Button type="submit" variant={r!.status === "suspended" ? "default" : "destructive"} size="sm" className="mt-2" disabled={status.isPending || reason.trim().length < 3} data-testid="button-toggle-status">
                  {status.isPending ? "Saving…" : r!.status === "suspended" ? "Reactivate" : "Suspend"}
                </Button>
              </form>
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
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Recent credit history</h3>
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
              </div>
            </div>
            <ResellerAccounts id={id} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function ResellersPage() {
  return <AdminShell><ResellersList /></AdminShell>;
}
