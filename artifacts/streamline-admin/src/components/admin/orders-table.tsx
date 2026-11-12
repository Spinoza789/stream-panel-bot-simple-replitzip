import { useLocation } from "wouter";
import type { AdminOrder } from "@workspace/api-client-react";
import { ChevronRight } from "lucide-react";
import { formatDateTime, relativeTime } from "@/lib/format";
import { Bar, CopyId, KindTag, StatusBadge } from "./bits";

export function OrdersTable({ orders, loading, rows = 8 }: { orders?: AdminOrder[]; loading?: boolean; rows?: number }) {
  const [, setLocation] = useLocation();
  return (
    <>
    <ul className="divide-y divide-border md:hidden">
      {loading && Array.from({ length: Math.min(rows, 4) }).map((_, i) => <li key={i} className="space-y-2 p-4"><Bar className="h-4 w-1/2" /><Bar className="h-3.5 w-3/4" /></li>)}
      {!loading && orders?.map((o) => (
        <li key={o.id}>
          <div role="button" tabIndex={0} data-testid={`row-order-${o.id}`} onClick={() => setLocation(`/orders/${encodeURIComponent(o.id)}`)}
            onKeyDown={(e) => { if (e.key === "Enter") setLocation(`/orders/${encodeURIComponent(o.id)}`); }}
            className="flex cursor-pointer items-start justify-between gap-3 p-4 transition-colors active:bg-[#f1f1f1] dark:active:bg-white/10">
            <div className="min-w-0 space-y-1">
              <div className="truncate text-[15px] font-semibold">{o.username ? "@" + o.username : o.customer || "—"}</div>
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground"><KindTag kind={o.kind} /><span>{o.plan || "—"}</span></div>
              <div className="num text-xs text-muted-foreground">{formatDateTime(o.createdAt)} · <span className="font-mono">{o.id.slice(0, 8)}…</span></div>
            </div>
            <div className="shrink-0 space-y-1 text-right">
              <StatusBadge status={o.status} />
              <div className="num text-sm"><span className="font-mono">{o.amount}</span> <span className="text-xs font-medium">{o.symbol}</span></div>
            </div>
          </div>
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
            <th className="px-4 py-2 font-medium">Order</th>
            <th className="px-3 py-2 font-medium">Created</th>
            <th className="px-3 py-2 font-medium">Customer</th>
            <th className="px-3 py-2 font-medium">Plan</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 text-right font-medium">Amount</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {loading &&
            Array.from({ length: rows }).map((_, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                {[28, 24, 20, 16, 14, 18].map((w, j) => (
                  <td key={j} className="px-3 py-3 first:px-4"><Bar className="h-3.5" /><span className="sr-only">{w}</span></td>
                ))}
                <td />
              </tr>
            ))}
          {!loading &&
            orders?.map((o) => (
              <tr
                key={o.id}
                data-testid={`row-order-${o.id}`}
                onClick={() => setLocation(`/orders/${encodeURIComponent(o.id)}`)}
                className="group cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5"
              >
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <CopyId value={o.id} label="Order ID" short />
                    <KindTag kind={o.kind} />
                  </div>
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <div className="num">{formatDateTime(o.createdAt)}</div>
                  <div className="text-xs text-muted-foreground">{relativeTime(o.createdAt)}</div>
                </td>
                <td className="max-w-[180px] truncate px-3 py-2.5">
                  {o.username && <div className="font-medium">@{o.username}</div>}
                  <div className={o.username ? "font-mono text-[11px] text-muted-foreground" : "font-mono text-[12.5px]"}>{o.customer || "—"}</div>
                </td>
                <td className="px-3 py-2.5">{o.plan || "—"}</td>
                <td className="px-3 py-2.5"><StatusBadge status={o.status} /></td>
                <td className="num px-3 py-2.5 text-right whitespace-nowrap">
                  <span className="font-mono">{o.amount}</span> <span className="text-xs font-medium">{o.symbol}</span>
                  <div className="text-[11px] text-muted-foreground">{o.network}</div>
                </td>
                <td className="pr-3 text-muted-foreground"><ChevronRight className="h-4 w-4 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" /></td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
