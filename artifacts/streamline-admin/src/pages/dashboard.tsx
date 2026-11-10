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
        eyebrow={d ? <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-[#29845a]" /> Mode <b className="font-mono text-xs text-foreground">{d.mode}</b></span> : undefined}
      />
      {q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : (
        <>
          <div className="card-shadow grid grid-cols-2 overflow-hidden rounded-xl bg-card md:grid-cols-3 lg:grid-cols-6">
            {q.isLoading &&
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="border-b border-border p-4 md:border-r"><Bar className="h-3 w-16" /><Bar className="mt-3 h-7 w-12" /></div>
              ))}
            {tiles.map((t, i) => (
              <Link
                key={t.k}
                href={t.href}
                data-testid={`card-count-${t.k.toLowerCase().replace(/\s/g, "-")}`}
                className={`rise rise-${Math.min(i, 4)} group border-b border-border p-4 transition-colors hover:bg-[#f7f7f7] md:border-r lg:border-b-0 lg:last:border-r-0`}
              >
                <div className="flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground underline decoration-dotted decoration-[#c9c9c9] underline-offset-4 group-hover:text-foreground">
                  {t.k}
                  <ArrowRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
                <div className="num mt-2 flex items-baseline gap-2 text-2xl font-semibold leading-none tracking-tight">
                  {t.v.toLocaleString()}
                  {t.hot && <span className="rounded-md bg-[#ffd79d] px-1.5 py-0.5 text-[11px] font-semibold text-[#5e4200]">action</span>}
                </div>
                <div className="mt-1.5 text-[11px] text-muted-foreground">{t.hint}</div>
              </Link>
            ))}
          </div>

          <Panel
            className="mt-4"
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
