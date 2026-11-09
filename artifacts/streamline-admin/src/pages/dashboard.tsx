import { Link } from "wouter";
import { useGetAdminOverview, getGetAdminOverviewQueryKey } from "@workspace/api-client-react";
import { ArrowRight, Inbox } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, EmptyState, ErrorState, PageHeader, Panel } from "@/components/admin/bits";
import { OrdersTable } from "@/components/admin/orders-table";
import { errorMessage, humanize } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

function Overview() {
  usePageMeta("Home", "Order counts, review queue and most recent orders for Streamline.");
  const ready = useAdminReady();
  const q = useGetAdminOverview({ query: { enabled: ready, queryKey: getGetAdminOverviewQueryKey(), ...LIVE } });
  const d = q.data;
  const tiles = d
    ? [
        { k: "Needs review", v: d.review, hint: "Orders waiting on you", href: "/orders?status=review", hot: d.review > 0 },
        { k: "Trials", v: d.trials, hint: "Trial orders on record", href: "/trials" },
        { k: "Queued", v: d.queued, hint: "Waiting for a worker", href: "/orders?status=queued" },
        { k: "Pending", v: d.pending, hint: "Awaiting payment", href: "/orders?status=pending" },
        { k: "Fulfilled", v: d.fulfilled, hint: "Completed orders", href: "/orders?status=fulfilled" },
        { k: "All orders", v: d.total, hint: "Every order, all states", href: "/orders" },
      ]
    : [];

  return (
    <>
      <PageHeader
        title="Home"
        description="Order counts across the checkout. These are counts of orders, not revenue."
        eyebrow={d ? <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-[hsl(140_50%_36%)]" /> Mode <b className="font-mono text-xs text-foreground">{d.mode}</b></span> : undefined}
      />
      {q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            {q.isLoading &&
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-xl border border-card-border bg-card p-4"><Bar className="h-3 w-16" /><Bar className="mt-3 h-7 w-12" /></div>
              ))}
            {tiles.map((t, i) => (
              <Link
                key={t.k}
                href={t.href}
                data-testid={`card-count-${t.k.toLowerCase().replace(/\s/g, "-")}`}
                className={`rise rise-${Math.min(i, 4)} group rounded-xl border bg-card p-4 transition-all hover:-translate-y-0.5 hover:shadow-md ${t.hot ? "border-[hsl(36_80%_60%)] bg-[hsl(42_90%_96%)]" : "border-card-border"}`}
              >
                <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
                  {t.k}
                  <ArrowRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
                <div className="num mt-1.5 text-[28px] font-semibold leading-none tracking-tight">{t.v.toLocaleString()}</div>
                <div className="mt-1.5 text-[11px] text-muted-foreground">{t.hint}</div>
              </Link>
            ))}
          </div>

          <Panel
            className="mt-6"
            flush
            title="Recent orders"
            aside={<Link href="/orders" className="text-sm font-medium text-primary hover:underline" data-testid="link-all-orders">View all</Link>}
          >
            {!q.isLoading && d && d.recent.length === 0 ? (
              <EmptyState icon={<Inbox className="h-5 w-5" />} title="No orders yet">
                When a customer starts checkout in the Telegram bot, the order shows up here within 30 seconds.
              </EmptyState>
            ) : (
              <OrdersTable orders={d?.recent} loading={q.isLoading} rows={5} />
            )}
          </Panel>
          {d && d.review > 0 && (
            <p className="mt-4 text-sm text-muted-foreground">
              {d.review} {d.review === 1 ? "order is" : "orders are"} {humanize("in review")}. Open one to read the status explanation and, for stuck trials, the recovery steps.
            </p>
          )}
        </>
      )}
    </>
  );
}

export default function DashboardPage() {
  return (
    <AdminShell>
      <Overview />
    </AdminShell>
  );
}
