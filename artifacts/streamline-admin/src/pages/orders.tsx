import { useEffect, useRef, useState } from "react";
import { useSearch } from "wouter";
import { useListAdminOrders, getListAdminOrdersQueryKey, type ListAdminOrdersParams } from "@workspace/api-client-react";
import { ChevronLeft, ChevronRight, Hourglass, Search, SearchX, X } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { EmptyState, ErrorState, PageHeader, Panel } from "@/components/admin/bits";
import { OrdersTable } from "@/components/admin/orders-table";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

const STATUSES = ["", "pending", "queued", "review", "fulfilled"];
const STATUS_LABEL: Record<string, string> = { "": "All", pending: "Pending", queued: "Queued", review: "Needs review", fulfilled: "Fulfilled" };

function OrdersList({ trialsOnly }: { trialsOnly?: boolean }) {
  usePageMeta(
    trialsOnly ? "Trials" : "Orders",
    trialsOnly ? "Every trial order, with status, so stuck trials are easy to spot and recover." : "Search and filter every UKCTV order by status, kind and customer.",
  );
  const ready = useAdminReady();
  const search = useSearch();
  const initialParams = new URLSearchParams(search);
  const initialStatus = initialParams.get("status") ?? "";
  const initialQuery = (initialParams.get("q") ?? "").slice(0, 80);
  const [status, setStatus] = useState(STATUSES.includes(initialStatus) ? initialStatus : "");
  const initialKind = initialParams.get("kind") ?? "";
  const [kind, setKind] = useState(initialKind === "trial" || initialKind === "paid" ? initialKind : "");
  const [text, setText] = useState(initialQuery);
  const [q, setQ] = useState(initialQuery);
  const [page, setPage] = useState(1);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (initialQuery && text !== initialQuery) setText(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setQ(text.trim().slice(0, 80));
      setPage(1);
    }, 300);
    return () => clearTimeout(timer.current);
  }, [text]);

  const params: ListAdminOrdersParams = { page };
  if (q) params.q = q;
  if (status) params.status = status;
  const effKind = trialsOnly ? "trial" : kind;
  if (effKind) params.kind = effKind;

  const list = useListAdminOrders(params, {
    query: { enabled: ready, queryKey: getListAdminOrdersQueryKey(params), placeholderData: (p) => p, ...LIVE },
  });
  const d = list.data;
  const pages = d ? Math.max(1, Math.ceil(d.total / Math.max(1, d.pageSize))) : 1;
  const from = d && d.total ? (d.page - 1) * d.pageSize + 1 : 0;
  const to = d ? Math.min(d.total, d.page * d.pageSize) : 0;
  const filtered = !!(q || status || (!trialsOnly && kind));

  return (
    <>
      <PageHeader
        title={trialsOnly ? "Trials" : "Orders"}
        description={
          trialsOnly
            ? "Trial orders only. Review means account delivery could not be confirmed. Inspect the original request before deciding whether it is safe to recover."
            : "Every order from the Telegram checkout. Click a row for the full status explanation."
        }
      />
      <Panel flush>
        <div className="flex flex-col gap-3 border-b border-border p-3 md:flex-row md:items-center">
          <div className="flex flex-wrap gap-1" role="tablist">
            {STATUSES.map((s) => (
              <button
                key={s || "all"}
                role="tab"
                aria-selected={status === s}
                data-testid={`tab-status-${s || "all"}`}
                onClick={() => { setStatus(s); setPage(1); }}
                className={cn(
                  "rounded-lg px-2.5 py-1 text-[13px] font-medium transition-colors",
                  status === s ? "bg-[#f1f1f1] text-foreground" : "text-muted-foreground hover:bg-[#f7f7f7] hover:text-foreground",
                )}
              >
                {STATUS_LABEL[s]}
              </button>
            ))}
          </div>
          <div className="flex flex-1 items-center gap-2 md:justify-end">
            {!trialsOnly && (
              <select
                value={kind}
                onChange={(e) => { setKind(e.target.value); setPage(1); }}
                data-testid="select-kind"
                className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]"
              >
                <option value="">All kinds</option>
                <option value="trial">Trial</option>
                <option value="paid">Paid</option>
              </select>
            )}
            <div className="relative w-full md:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={text}
                maxLength={80}
                onChange={(e) => setText(e.target.value)}
                placeholder="Order ID, Telegram ID, @username or TXID"
                className="h-8 pl-8 pr-8 text-[13px]"
                data-testid="input-search"
              />
              {text && (
                <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear" data-testid="button-clear-search">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        </div>

        {list.isError ? (
          <div className="p-4"><ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} /></div>
        ) : d && d.items.length === 0 ? (
          filtered ? (
            <EmptyState icon={<SearchX className="h-5 w-5" />} title="No orders match these filters">
              <button className="font-medium text-primary hover:underline" onClick={() => { setText(""); setStatus(""); setKind(""); }} data-testid="button-reset-filters">Reset filters</button>
            </EmptyState>
          ) : (
            <EmptyState icon={<Hourglass className="h-5 w-5" />} title={trialsOnly ? "No trial orders yet" : "No orders yet"}>
              {trialsOnly ? "Trials requested through the bot appear here." : "Orders appear here as soon as checkout creates them."}
            </EmptyState>
          )
        ) : (
          <div className={cn("transition-opacity", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
            <OrdersTable orders={d?.items} loading={list.isLoading} />
          </div>
        )}

        {d && d.total > 0 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-sm">
            <span className="num text-muted-foreground" data-testid="text-pagination">
              {from.toLocaleString()}–{to.toLocaleString()} of {d.total.toLocaleString()}
            </span>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" className="h-8 w-8" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} data-testid="button-prev-page"><ChevronLeft className="h-4 w-4" /></Button>
              <span className="num px-2 text-muted-foreground">{d.page} / {pages}</span>
              <Button variant="outline" size="icon" className="h-8 w-8" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} data-testid="button-next-page"><ChevronRight className="h-4 w-4" /></Button>
            </div>
          </div>
        )}
      </Panel>
    </>
  );
}

export function OrdersPage() {
  return <AdminShell><OrdersList /></AdminShell>;
}

export function TrialsPage() {
  return <AdminShell><OrdersList trialsOnly /></AdminShell>;
}
