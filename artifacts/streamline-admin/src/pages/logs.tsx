import { useEffect, useRef, useState } from "react";
import { useSearch } from "wouter";
import {
  useListAdminActivityLog, getListAdminActivityLogQueryKey, useListAdminCreditLog, getListAdminCreditLogQueryKey,
  type ListAdminActivityLogParams, type ListAdminCreditLogParams, type LogReseller,
} from "@workspace/api-client-react";
import { ChevronLeft, ChevronRight, ScrollText, Search, X } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, CopyId, EmptyState, ErrorState, PageHeader, Panel, SellerBadge, StatusBadge } from "@/components/admin/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { errorMessage, formatDateTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

const ACTIONS: Record<string, string> = { create: "Created line", trial: "Created trial", extend: "Extended line" };
const KINDS: Record<string, string> = { purchase: "Credit pack bought", adjustment: "Manual adjustment", usage: "Credits used" };

function resellerName(username: string, id: number) {
  return username ? "@" + username : "Reseller " + id;
}

function Pager({ page, total, pageSize, onPage, summary }: { page: number; total: number; pageSize: number; onPage: (p: number) => void; summary: string }) {
  const pages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
      <span className="num text-muted-foreground" data-testid="text-log-summary">{summary}</span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon" className="h-8 w-8" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft className="h-4 w-4" /></Button>
        <span className="num px-2 text-muted-foreground">{page} / {pages}</span>
        <Button variant="outline" size="icon" className="h-8 w-8" disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

function Rows({ columns }: { columns: number }) {
  return <>{Array.from({ length: 6 }).map((_, i) => <tr key={i} className="border-b border-border last:border-0">{Array.from({ length: columns }).map((_, j) => <td key={j} className="px-3 py-3 first:px-4"><Bar className="h-3.5" /></td>)}</tr>)}</>;
}

const th = "px-3 py-2 font-medium first:px-4";
const row = "border-b border-border last:border-0";

/** Accounts created and extended, with the reseller's credits before and after each one. */
function ActivityTable({ reseller, source, q, page, onPage, onResellers }: { reseller?: number; source: string; q: string; page: number; onPage: (p: number) => void; onResellers: (r: LogReseller[]) => void }) {
  const ready = useAdminReady();
  const params: ListAdminActivityLogParams = { page };
  if (q) params.q = q;
  if (reseller) params.reseller = reseller;
  else if (source) params.source = source as "retail" | "reseller";
  const list = useListAdminActivityLog(params, { query: { enabled: ready, queryKey: getListAdminActivityLogQueryKey(params), placeholderData: (p) => p, ...LIVE } });
  const d = list.data;
  useEffect(() => { if (d) onResellers(d.resellers); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [d?.resellers.length]);
  if (list.isError) return <div className="p-4"><ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} /></div>;
  if (d && d.items.length === 0) return <EmptyState icon={<ScrollText className="h-5 w-5" />} title="No activity matches">Lines appear here as soon as they are created or extended.</EmptyState>;
  return (
    <>
      <ul className={cn("divide-y divide-border transition-opacity md:hidden", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")} data-testid="cards-activity">
        {list.isLoading && Array.from({ length: 3 }).map((_, i) => <li key={i} className="space-y-2 p-4"><Bar className="h-4 w-1/2" /><Bar className="h-3.5 w-3/4" /></li>)}
        {!list.isLoading && d?.items.map((a) => (
          <li key={a.source + a.id} className="space-y-2 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[15px] font-semibold">{ACTIONS[a.action] ?? a.action}</div>
                <div className="text-sm text-muted-foreground">{a.package}</div>
              </div>
              <div className="num shrink-0 text-right text-sm">
                {a.creditsBefore === null || a.creditsAfter === null
                  ? <span className="text-muted-foreground">{a.source === "retail" ? "" : a.status === "failed" ? "Not charged" : `${a.creditCost} held`}</span>
                  : <><span className="text-muted-foreground">{a.creditsBefore} →</span> <span className="font-semibold">{a.creditsAfter}</span><div className="text-[11px] text-muted-foreground">credits</div></>}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <SellerBadge source={a.source} name={a.source === "reseller" ? resellerName(a.resellerUsername, a.resellerTelegramId) : undefined} />
              {a.customer && <span className="truncate">{a.customer}</span>}
              {a.status !== "succeeded" && <StatusBadge status={a.status} tone={a.status === "failed" ? "critical" : "attention"} />}
            </div>
            {a.accountUsername && (
              <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Username</dt><dd className="min-w-0 justify-self-end"><CopyId value={a.accountUsername} label="Username" /></dd>
                {a.accountPassword && <><dt className="text-muted-foreground">Password</dt><dd className="min-w-0 justify-self-end"><CopyId value={a.accountPassword} label="Password" /></dd></>}
              </dl>
            )}
            <div className="num text-xs text-muted-foreground">{formatDateTime(a.date)}</div>
          </li>
        ))}
      </ul>
      <div className={cn("hidden overflow-x-auto transition-opacity md:block", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
        <table className="w-full min-w-[860px] text-sm" data-testid="table-activity">
          <thead><tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className={th}>Date</th><th className={th}>Owner</th><th className={th}>Username</th><th className={th}>Password</th><th className={th}>What happened</th><th className={cn(th, "text-right")}>Credits</th>
          </tr></thead>
          <tbody>
            {list.isLoading && <Rows columns={6} />}
            {!list.isLoading && d?.items.map((a) => (
              <tr key={a.source + a.id} className={row} data-testid={`row-activity-${a.id}`}>
                <td className="num whitespace-nowrap px-4 py-2.5">{formatDateTime(a.date)}</td>
                <td className="px-3 py-2.5">
                  <SellerBadge source={a.source} name={a.source === "reseller" ? resellerName(a.resellerUsername, a.resellerTelegramId) : undefined} />
                  <div className="mt-1 max-w-[200px] truncate text-[11px] text-muted-foreground">{a.customer || (a.source === "reseller" ? "No customer note" : "")}</div>
                </td>
                <td className="px-3 py-2.5">{a.accountUsername ? <CopyId value={a.accountUsername} label="Username" /> : <span className="text-muted-foreground">—</span>}</td>
                <td className="px-3 py-2.5">{a.accountPassword ? <CopyId value={a.accountPassword} label="Password" /> : <span className="text-muted-foreground">—</span>}</td>
                <td className="px-3 py-2.5">
                  <div><span className="font-medium">{ACTIONS[a.action] ?? a.action}</span> · {a.package}</div>
                  {a.status !== "succeeded" && <div className="mt-0.5"><StatusBadge status={a.status} tone={a.status === "failed" ? "critical" : "attention"} /></div>}
                </td>
                <td className="num whitespace-nowrap px-3 py-2.5 text-right">
                  {a.creditsBefore === null || a.creditsAfter === null
                    ? <span className="text-muted-foreground">{a.source === "retail" ? "—" : a.status === "failed" ? "Not charged" : `${a.creditCost} held`}</span>
                    : <><span className="text-[#0c5132] dark:text-[#9fe2b8]">{a.creditsBefore}</span> → <span className={a.creditsAfter < a.creditsBefore ? "text-[#8e1f0b] dark:text-[#f3b0ab]" : ""}>{a.creditsAfter}</span></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d && d.total > 0 && <Pager page={d.page} total={d.total} pageSize={d.pageSize} onPage={onPage} summary={`${d.total.toLocaleString()} entr${d.total === 1 ? "y" : "ies"}`} />}
    </>
  );
}

/** Every change to a reseller's credit balance: packs bought, manual adjustments and, optionally, credits spent. */
function CreditTable({ reseller, scope, q, page, onPage, onResellers }: { reseller?: number; scope: string; q: string; page: number; onPage: (p: number) => void; onResellers: (r: LogReseller[]) => void }) {
  const ready = useAdminReady();
  const params: ListAdminCreditLogParams = { page };
  if (q) params.q = q;
  if (reseller) params.reseller = reseller;
  if (scope) params.scope = scope as "usage" | "all";
  const list = useListAdminCreditLog(params, { query: { enabled: ready, queryKey: getListAdminCreditLogQueryKey(params), placeholderData: (p) => p, ...LIVE } });
  const d = list.data;
  useEffect(() => { if (d) onResellers(d.resellers); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [d?.resellers.length]);
  if (list.isError) return <div className="p-4"><ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} /></div>;
  if (d && d.items.length === 0) return <EmptyState icon={<ScrollText className="h-5 w-5" />} title="No credit movements match">Credit packs and manual adjustments appear here.</EmptyState>;
  return (
    <>
      <ul className={cn("divide-y divide-border transition-opacity md:hidden", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")} data-testid="cards-credits">
        {list.isLoading && Array.from({ length: 3 }).map((_, i) => <li key={i} className="space-y-2 p-4"><Bar className="h-4 w-1/2" /><Bar className="h-3.5 w-3/4" /></li>)}
        {!list.isLoading && d?.items.map((c) => (
          <li key={c.id} className="space-y-1.5 p-4" data-testid={`row-credit-${c.id}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0"><div className="truncate text-[15px] font-semibold">{resellerName(c.resellerUsername, c.resellerTelegramId)}</div><div className="text-sm">{c.reason || "—"}</div></div>
              <div className="shrink-0 text-right">
                <div className={cn("num text-[15px] font-semibold", c.movement > 0 ? "text-[#0c5132] dark:text-[#9fe2b8]" : c.movement < 0 ? "text-[#8e1f0b] dark:text-[#f3b0ab]" : "")}>{c.movement > 0 ? "+" : ""}{c.movement}</div>
                <div className="num text-xs text-muted-foreground">{c.balanceBefore} → {c.balanceAfter}</div>
              </div>
            </div>
            <div className="text-xs text-muted-foreground">{KINDS[c.kind] ?? c.kind} · {c.admin} · <span className="num">{formatDateTime(c.date)}</span></div>
          </li>
        ))}
      </ul>
      <div className={cn("hidden overflow-x-auto transition-opacity md:block", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
        <table className="w-full min-w-[720px] text-sm" data-testid="table-credits">
          <thead><tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className={th}>Date</th><th className={th}>Reseller</th><th className={th}>By</th><th className={th}>Reason</th><th className={cn(th, "text-right")}>Credits</th><th className={cn(th, "text-right")}>Balance</th>
          </tr></thead>
          <tbody>
            {list.isLoading && <Rows columns={6} />}
            {!list.isLoading && d?.items.map((c) => (
              <tr key={c.id} className={row} data-testid={`row-credit-${c.id}`}>
                <td className="num whitespace-nowrap px-4 py-2.5">{formatDateTime(c.date)}</td>
                <td className="px-3 py-2.5"><div className="font-medium">{resellerName(c.resellerUsername, c.resellerTelegramId)}</div><div className="font-mono text-[11px] text-muted-foreground">{c.resellerTelegramId}</div></td>
                <td className="px-3 py-2.5">{c.admin}</td>
                <td className="px-3 py-2.5"><div>{c.reason || "—"}</div><div className="text-[11px] text-muted-foreground">{KINDS[c.kind] ?? c.kind}</div></td>
                <td className={cn("num whitespace-nowrap px-3 py-2.5 text-right font-medium", c.movement > 0 ? "text-[#0c5132] dark:text-[#9fe2b8]" : c.movement < 0 ? "text-[#8e1f0b] dark:text-[#f3b0ab]" : "")}>{c.movement > 0 ? "+" : ""}{c.movement}</td>
                <td className="num whitespace-nowrap px-3 py-2.5 text-right text-muted-foreground">{c.balanceBefore} → <span className="text-foreground">{c.balanceAfter}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d && d.total > 0 && <Pager page={d.page} total={d.total} pageSize={d.pageSize} onPage={onPage} summary={`${d.total.toLocaleString()} entr${d.total === 1 ? "y" : "ies"} · +${d.added.toLocaleString()} added · −${d.removed.toLocaleString()} removed`} />}
    </>
  );
}

function Logs() {
  usePageMeta("Logs", "Activity and credit logs for direct sales and every reseller.");
  const initial = new URLSearchParams(useSearch());
  const initialReseller = parseInt(initial.get("reseller") ?? "", 10);
  const [tab, setTab] = useState<"activity" | "credits">(initial.get("tab") === "credits" ? "credits" : "activity");
  const [reseller, setReseller] = useState<number | undefined>(initialReseller > 0 ? initialReseller : undefined);
  const [source, setSource] = useState("");
  const [scope, setScope] = useState("");
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [resellers, setResellers] = useState<LogReseller[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setQ(text.trim().slice(0, 80)); setPage(1); }, 300);
    return () => clearTimeout(timer.current);
  }, [text]);
  const select = "h-9 min-w-0 flex-1 rounded-lg border border-input bg-card px-2 text-[13px] sm:h-8 sm:flex-none";
  return (
    <>
      <PageHeader title="Logs" description="What happened on your own system: every line created or extended, and every change to a reseller's credits. Pick a reseller to see only theirs." />
      <Panel flush>
        <div className="flex flex-col gap-3 border-b border-border p-3 lg:flex-row lg:items-center">
          <div className="flex gap-1" role="tablist">
            {([["activity", "Activity log"], ["credits", "Credit log"]] as const).map(([value, label]) => (
              <button key={value} role="tab" aria-selected={tab === value} data-testid={`tab-log-${value}`} onClick={() => { setTab(value); setPage(1); }}
                className={cn("rounded-lg px-2.5 py-1 text-[13px] font-medium transition-colors", tab === value ? "bg-[#f1f1f1] text-foreground dark:bg-white/10" : "text-muted-foreground hover:bg-[#f7f7f7] hover:text-foreground dark:hover:bg-white/5")}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex flex-1 flex-wrap items-center gap-2 lg:justify-end">
            <select value={reseller ?? ""} onChange={(e) => { setReseller(e.target.value ? Number(e.target.value) : undefined); setPage(1); }} className={select} data-testid="select-log-reseller" aria-label="Reseller">
              <option value="">All resellers</option>
              {reseller && !resellers.some((r) => r.telegramId === reseller) && <option value={reseller}>Reseller {reseller}</option>}
              {resellers.map((r) => <option key={r.telegramId} value={r.telegramId}>{resellerName(r.username, r.telegramId)} ({r.telegramId})</option>)}
            </select>
            {tab === "activity" ? (
              <select value={reseller ? "reseller" : source} disabled={!!reseller} onChange={(e) => { setSource(e.target.value); setPage(1); }} className={select} data-testid="select-log-source" aria-label="Sold by">
                <option value="">Direct and reseller</option><option value="reseller">Resellers only</option><option value="retail">Direct sales only</option>
              </select>
            ) : (
              <select value={scope} onChange={(e) => { setScope(e.target.value); setPage(1); }} className={select} data-testid="select-log-scope" aria-label="Movements">
                <option value="">Top-ups and adjustments</option><option value="usage">Credits used</option><option value="all">Everything</option>
              </select>
            )}
            <div className="relative w-full sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)} placeholder={tab === "activity" ? "Username, customer or package" : "Reseller or reason"} className="h-8 pl-8 pr-8 text-[13px]" data-testid="input-log-search" />
              {text && <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear"><X className="h-4 w-4" /></button>}
            </div>
          </div>
        </div>
        {tab === "activity"
          ? <ActivityTable reseller={reseller} source={source} q={q} page={page} onPage={setPage} onResellers={setResellers} />
          : <CreditTable reseller={reseller} scope={scope} q={q} page={page} onPage={setPage} onResellers={setResellers} />}
      </Panel>
    </>
  );
}

export default function LogsPage() {
  return <AdminShell><Logs /></AdminShell>;
}
