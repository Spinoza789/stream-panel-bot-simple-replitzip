import { useEffect, useRef, useState } from "react";
import { Link, useSearch } from "wouter";
import { useListAdminSubscriptions, getListAdminSubscriptionsQueryKey, type AdminSubscription, type ListAdminSubscriptionsParams } from "@workspace/api-client-react";
import { ChevronLeft, ChevronRight, Plus, Search, SearchX, Trash2, Tv, X } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, CopyId, EmptyState, ErrorState, KindTag, PageHeader, Panel, StatusBadge } from "@/components/admin/bits";
import { AccountDetails, AddSubscriptionDialog, DeleteSubscriptionDialog } from "@/components/admin/subscriptions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { errorMessage, formatDate, formatDateTime, relativeTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

const SOURCES = [["", "All"], ["retail", "Direct customers"], ["reseller", "Resellers"]] as const;

/** Who the account belongs to: a Telegram customer for direct sales, the reseller's own note for resold accounts. */
function Customer({ s }: { s: AdminSubscription }) {
  if (s.source === "retail") {
    return (
      <div>
        <div className="font-medium">{s.telegramUsername ? "@" + s.telegramUsername : s.telegramId ? "No username yet" : "Website checkout"}</div>
        {!!s.telegramId && <div className="font-mono text-[11px] text-muted-foreground">{s.telegramId}</div>}
      </div>
    );
  }
  return (
    <div>
      <div className="font-medium">{s.customerRef || "No customer note"}</div>
      <div className="text-[11px] text-muted-foreground">via {s.resellerUsername ? "@" + s.resellerUsername : "reseller " + s.resellerTelegramId}</div>
    </div>
  );
}

/** `compact` drops the password column for narrow places; the row still opens the full details. */
export function SubscriptionsTable({ items, loading, onOpen, compact }: { items?: AdminSubscription[]; loading?: boolean; onOpen: (s: AdminSubscription) => void; compact?: boolean }) {
  const columns = compact ? 5 : 6;
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full text-sm", compact ? "min-w-[600px]" : "min-w-[780px]")}>
        <thead>
          <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
            <th className="px-4 py-2 font-medium">Customer</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Account username</th>
            {!compact && <th className="px-3 py-2 font-medium">Password</th>}
            <th className="px-3 py-2 font-medium">Expires</th>
            <th className="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {loading && Array.from({ length: 6 }).map((_, i) => (
            <tr key={i} className="border-b border-border last:border-0">{Array.from({ length: columns }).map((_, j) => <td key={j} className="px-3 py-3 first:px-4"><Bar className="h-3.5" /></td>)}</tr>
          ))}
          {!loading && items?.map((s) => (
            <tr key={s.source + s.id} onClick={() => onOpen(s)} data-testid={`row-subscription-${s.id}`} className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5">
              <td className="max-w-[220px] truncate px-4 py-2.5"><Customer s={s} /></td>
              <td className="px-3 py-2.5"><KindTag kind={s.kind === "trial" ? "trial" : "subscription"} /><div className="mt-0.5 text-[11px] text-muted-foreground">{s.connections} device{s.connections > 1 ? "s" : ""}</div></td>
              <td className="px-3 py-2.5">{s.accountUsername ? <CopyId value={s.accountUsername} label="Username" /> : "—"}</td>
              {!compact && <td className="px-3 py-2.5">{s.accountPassword ? <CopyId value={s.accountPassword} label="Password" /> : "—"}</td>}
              <td className="px-3 py-2.5 whitespace-nowrap"><div className="num">{formatDate(s.expiresAt)}</div><div className="text-xs text-muted-foreground">{relativeTime(s.expiresAt)}</div></td>
              <td className="px-3 py-2.5"><StatusBadge status={s.status} tone={s.status === "active" ? "success" : s.status === "disabled" ? "critical" : "neutral"} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Everything about one account, with the delete button. */
export function SubscriptionDialog({ s, onClose }: { s: AdminSubscription; onClose: () => void }) {
  const [deleting, setDeleting] = useState(false);
  return (
    <>
      <Dialog open={!deleting} onOpenChange={(o) => { if (!o) onClose(); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{s.kind === "trial" ? "Trial" : "Subscription"} · {s.accountUsername || "account"}</DialogTitle>
            <DialogDescription className="flex flex-wrap items-center gap-2">
              <StatusBadge status={s.status} tone={s.status === "active" ? "success" : s.status === "disabled" ? "critical" : "neutral"} />
              <span>{s.plan} · {s.connections} device{s.connections > 1 ? "s" : ""}</span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Account details</h3>
              <AccountDetails username={s.accountUsername} password={s.accountPassword} serverUrl={s.serverUrl} expiresAt={s.expiresAt} />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{s.source === "retail" ? "Customer" : "Sold by"}</h3>
              <dl className="divide-y divide-border">
                {s.source === "retail" ? (
                  <>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Telegram username</dt><dd>{s.telegramUsername ? <CopyId value={"@" + s.telegramUsername} label="Username" /> : <span className="text-muted-foreground">Not seen yet</span>}</dd></div>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Telegram ID</dt><dd>{s.telegramId ? <CopyId value={String(s.telegramId)} label="Telegram ID" /> : "Website checkout"}</dd></div>
                  </>
                ) : (
                  <>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Reseller</dt><dd>{s.resellerUsername ? "@" + s.resellerUsername : "—"} <span className="font-mono text-xs text-muted-foreground">{s.resellerTelegramId}</span></dd></div>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Their customer note</dt><dd className="text-right">{s.customerRef || "—"}</dd></div>
                  </>
                )}
                <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Created</dt><dd className="num">{formatDateTime(s.createdAt)}</dd></div>
              </dl>
            </div>
          </div>
          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setDeleting(true)} data-testid="button-delete-subscription"><Trash2 className="mr-1.5 h-4 w-4" /> Delete</Button>
            <div className="flex gap-2">
              {s.source === "retail" && <Button variant="outline" asChild><Link href={`/orders/${s.id}`}>Open order</Link></Button>}
              <Button variant="outline" onClick={onClose}>Close</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <DeleteSubscriptionDialog
        target={deleting ? { source: s.source, id: s.id, kind: s.kind, label: s.accountUsername || s.id } : null}
        onClose={() => setDeleting(false)} onDeleted={onClose}
      />
    </>
  );
}

function SubscriptionsList() {
  usePageMeta("Subscriptions", "Every delivered account: direct and reseller subscriptions and trials, with login details.");
  const ready = useAdminReady();
  const initial = new URLSearchParams(useSearch());
  const resellerParam = parseInt(initial.get("reseller") ?? "", 10);
  const [source, setSource] = useState<string>(initial.get("source") === "reseller" || resellerParam > 0 ? "reseller" : "");
  const [reseller, setReseller] = useState<number | undefined>(resellerParam > 0 ? resellerParam : undefined);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<AdminSubscription | null>(null);
  const [adding, setAdding] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setQ(text.trim().slice(0, 80)); setPage(1); }, 300);
    return () => clearTimeout(timer.current);
  }, [text]);

  const params: ListAdminSubscriptionsParams = { page };
  if (q) params.q = q;
  if (source) params.source = source as "retail" | "reseller";
  if (kind) params.kind = kind as "trial" | "paid";
  if (status) params.status = status as "active" | "expired";
  if (reseller) params.reseller = reseller;
  const list = useListAdminSubscriptions(params, { query: { enabled: ready, queryKey: getListAdminSubscriptionsQueryKey(params), placeholderData: (p) => p, ...LIVE } });
  const d = list.data;
  const pages = d ? Math.max(1, Math.ceil(d.total / Math.max(1, d.pageSize))) : 1;
  const filtered = !!(q || source || kind || status || reseller);
  const reset = () => { setText(""); setSource(""); setKind(""); setStatus(""); setReseller(undefined); setPage(1); };

  return (
    <>
      <PageHeader
        title="Subscriptions"
        description="Every account that has been delivered: your own customers' subscriptions and trials, and the ones your resellers created. Click a row for the login details."
        actions={<Button onClick={() => setAdding(true)} data-testid="button-add-subscription"><Plus className="mr-1.5 h-4 w-4" /> Add subscription</Button>}
      />
      <Panel flush>
        <div className="flex flex-col gap-3 border-b border-border p-3 lg:flex-row lg:items-center">
          <div className="flex flex-wrap gap-1" role="tablist">
            {SOURCES.map(([value, label]) => (
              <button key={value || "all"} role="tab" aria-selected={source === value} data-testid={`tab-source-${value || "all"}`}
                onClick={() => { setSource(value); if (value !== "reseller") setReseller(undefined); setPage(1); }}
                className={cn("rounded-lg px-2.5 py-1 text-[13px] font-medium transition-colors", source === value ? "bg-[#f1f1f1] text-foreground dark:bg-white/10" : "text-muted-foreground hover:bg-[#f7f7f7] hover:text-foreground dark:hover:bg-white/5")}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex flex-1 flex-wrap items-center gap-2 lg:justify-end">
            <select value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }} className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]" data-testid="select-sub-kind">
              <option value="">Subscriptions and trials</option><option value="paid">Subscriptions</option><option value="trial">Trials</option>
            </select>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]" data-testid="select-sub-status">
              <option value="">Any status</option><option value="active">Active</option><option value="expired">Expired</option>
            </select>
            <div className="relative w-full sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)} placeholder="Username, Telegram ID or customer" className="h-8 pl-8 pr-8 text-[13px]" data-testid="input-sub-search" />
              {text && <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear"><X className="h-4 w-4" /></button>}
            </div>
          </div>
        </div>
        {reseller && (
          <div className="flex items-center justify-between gap-3 border-b border-border bg-muted/40 px-4 py-2 text-sm">
            <span>Showing accounts created by reseller <span className="font-mono">{reseller}</span></span>
            <button className="font-medium text-primary hover:underline" onClick={() => setReseller(undefined)}>Show all resellers</button>
          </div>
        )}
        {list.isError ? (
          <div className="p-4"><ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} /></div>
        ) : d && d.items.length === 0 ? (
          filtered ? (
            <EmptyState icon={<SearchX className="h-5 w-5" />} title="No accounts match these filters">
              <button className="font-medium text-primary hover:underline" onClick={reset} data-testid="button-reset-sub-filters">Reset filters</button>
            </EmptyState>
          ) : (
            <EmptyState icon={<Tv className="h-5 w-5" />} title="No accounts delivered yet">Trials and subscriptions appear here once their login has been created.</EmptyState>
          )
        ) : (
          <div className={cn("transition-opacity", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
            <SubscriptionsTable items={d?.items} loading={list.isLoading} onOpen={setOpen} />
          </div>
        )}
        {d && d.total > 0 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-sm">
            <span className="num text-muted-foreground" data-testid="text-sub-summary">{d.total.toLocaleString()} account{d.total === 1 ? "" : "s"} · {d.active.toLocaleString()} active · {d.trials.toLocaleString()} trial{d.trials === 1 ? "" : "s"}</span>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" className="h-8 w-8" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
              <span className="num px-2 text-muted-foreground">{d.page} / {pages}</span>
              <Button variant="outline" size="icon" className="h-8 w-8" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
            </div>
          </div>
        )}
      </Panel>
      {open && <SubscriptionDialog s={open} onClose={() => setOpen(null)} />}
      <AddSubscriptionDialog open={adding} onClose={() => setAdding(false)} />
    </>
  );
}

export default function SubscriptionsPage() {
  return <AdminShell><SubscriptionsList /></AdminShell>;
}
