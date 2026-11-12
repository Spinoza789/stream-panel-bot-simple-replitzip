import { useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";
import { useListAdminResellers, getListAdminResellersQueryKey, type ListAdminResellersParams } from "@workspace/api-client-react";
import { ChevronLeft, ChevronRight, Plus, Search, Users, X } from "lucide-react";
import { CreateResellerDialog } from "@/components/admin/create";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, EmptyState, ErrorState, PageHeader, Panel, StatusBadge } from "@/components/admin/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage, formatDateTime, relativeTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";
import { cn } from "@/lib/utils";

function ResellersList() {
  usePageMeta("Resellers", "Every reseller with balance, customers and last activity. Suspend, reactivate or adjust credits.");
  const ready = useAdminReady();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [, setLocation] = useLocation();
  const [creating, setCreating] = useState(false);
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
      <PageHeader title="Resellers" description="Who sells for you, what they hold in credits and how many customers they look after. Click a reseller to open their page. Actions are logged in the audit trail."
        actions={<Button onClick={() => setCreating(true)} data-testid="button-add-reseller"><Plus className="mr-1.5 h-4 w-4" /> Add reseller</Button>} />
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
                  <tr key={r.telegramId} onClick={() => setLocation(`/resellers/${r.telegramId}`)} data-testid={`row-reseller-${r.telegramId}`} className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5">
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
      <CreateResellerDialog open={creating} onClose={() => setCreating(false)} onCreated={(r) => setLocation(`/resellers/${r.reseller.telegramId}`)} />
    </>
  );
}

export default function ResellersPage() {
  return <AdminShell><ResellersList /></AdminShell>;
}

