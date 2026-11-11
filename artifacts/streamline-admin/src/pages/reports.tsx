import { useState } from "react";
import { useGetAdminReports, getGetAdminReportsQueryKey, type GetAdminReportsParams } from "@workspace/api-client-react";
import { Download } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, ErrorState, PageHeader, Panel } from "@/components/admin/bits";
import { Button } from "@/components/ui/button";
import { errorMessage, formatDateTime, gbp } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

function csvDownload(name: string, rows: (string | number)[][]) {
  const text = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Reports() {
  usePageMeta("Reports", "Revenue, credits sold and used, tests and conversions per month, with per-reseller totals.");
  const ready = useAdminReady();
  const [months, setMonths] = useState(12);
  const params: GetAdminReportsParams = { months };
  const q = useGetAdminReports(params, { query: { enabled: ready, queryKey: getGetAdminReportsQueryKey(params), ...LIVE } });
  const d = q.data;
  const totals = d?.months.reduce((t, m) => ({ gbp: t.gbp + m.totalGbp, sold: t.sold + m.creditsSold, used: t.used + m.creditsUsed, tests: t.tests + m.tests, converted: t.converted + m.testsConverted }), { gbp: 0, sold: 0, used: 0, tests: 0, converted: 0 });
  return (
    <>
      <PageHeader
        title="Reports"
        description="Revenue counts verified payments only: retail memberships at their GBP price and credit packs at the pack price. Credits used are deductions from reseller balances."
        actions={
          <div className="flex items-center gap-2">
            <select value={months} onChange={(e) => setMonths(parseInt(e.target.value, 10))} className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]" data-testid="select-report-months">
              {[3, 6, 12, 24, 36].map((n) => <option key={n} value={n}>Last {n} months</option>)}
            </select>
            <Button variant="outline" size="sm" disabled={!d} onClick={() => d && csvDownload("streamline-monthly.csv", [["month", "retail_orders", "retail_gbp", "credit_packs", "credit_gbp", "total_gbp", "credits_sold", "credits_used", "tests", "tests_converted"], ...d.months.map((m) => [m.month, m.retailOrders, m.retailGbp, m.creditPacks, m.creditGbp, m.totalGbp, m.creditsSold, m.creditsUsed, m.tests, m.testsConverted])])} data-testid="button-export-months">
              <Download className="mr-1.5 h-3.5 w-3.5" /> Months CSV
            </Button>
            <Button variant="outline" size="sm" disabled={!d} onClick={() => d && csvDownload("streamline-resellers.csv", [["telegram_id", "username", "status", "available", "reserved", "customers", "active_customers", "credits_bought", "last_activity"], ...d.resellers.map((r) => [r.telegramId, r.username, r.status, r.available, r.reserved, r.customers, r.activeCustomers, r.creditsBought, formatDateTime(r.lastActivity)])])} data-testid="button-export-resellers">
              <Download className="mr-1.5 h-3.5 w-3.5" /> Resellers CSV
            </Button>
          </div>
        }
      />
      {q.isError ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : (
        <>
          <div className="card-shadow mb-4 grid grid-cols-2 overflow-hidden rounded-xl bg-card md:grid-cols-5">
            {[["Revenue", totals ? gbp(totals.gbp) : "—"], ["Credits sold", totals?.sold ?? "—"], ["Credits used", totals?.used ?? "—"], ["Tests", totals?.tests ?? "—"], ["Converted", totals ? `${totals.converted}${totals.tests ? ` (${Math.round(100 * totals.converted / totals.tests)}%)` : ""}` : "—"]].map(([k, v]) => (
              <div key={String(k)} className="border-b border-border p-4 md:border-b-0 md:border-r md:last:border-r-0"><div className="text-[13px] font-medium text-muted-foreground">{k}</div><div className="num mt-2 text-2xl font-semibold tracking-tight">{v}</div></div>
            ))}
          </div>
          <Panel title="By month" flush>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead><tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Month</th><th className="px-3 py-2 text-right font-medium">Retail orders</th><th className="px-3 py-2 text-right font-medium">Retail</th>
                  <th className="px-3 py-2 text-right font-medium">Credit packs</th><th className="px-3 py-2 text-right font-medium">Packs</th><th className="px-3 py-2 text-right font-medium">Total</th>
                  <th className="px-3 py-2 text-right font-medium">Credits sold</th><th className="px-3 py-2 text-right font-medium">Credits used</th><th className="px-3 py-2 text-right font-medium">Tests</th><th className="px-3 py-2 text-right font-medium">Converted</th>
                </tr></thead>
                <tbody>
                  {q.isLoading && Array.from({ length: 4 }).map((_, i) => <tr key={i} className="border-b border-border">{Array.from({ length: 10 }).map((_, j) => <td key={j} className="px-3 py-3"><Bar className="h-3.5" /></td>)}</tr>)}
                  {d && d.months.length === 0 && <tr><td colSpan={10} className="px-4 py-10 text-center text-muted-foreground">No verified payments in this range yet.</td></tr>}
                  {d?.months.map((m) => (
                    <tr key={m.month} className="border-b border-border last:border-0" data-testid={`row-month-${m.month}`}>
                      <td className="px-4 py-2.5 font-medium">{m.month}</td>
                      <td className="num px-3 py-2.5 text-right">{m.retailOrders}</td><td className="num px-3 py-2.5 text-right">{gbp(m.retailGbp)}</td>
                      <td className="num px-3 py-2.5 text-right">{m.creditPacks}</td><td className="num px-3 py-2.5 text-right">{gbp(m.creditGbp)}</td>
                      <td className="num px-3 py-2.5 text-right font-semibold">{gbp(m.totalGbp)}</td>
                      <td className="num px-3 py-2.5 text-right">{m.creditsSold}</td><td className="num px-3 py-2.5 text-right">{m.creditsUsed}</td>
                      <td className="num px-3 py-2.5 text-right">{m.tests}</td><td className="num px-3 py-2.5 text-right">{m.testsConverted}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel title="By reseller" flush className="mt-4">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead><tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Reseller</th><th className="px-3 py-2 font-medium">Status</th><th className="px-3 py-2 text-right font-medium">Credits bought</th><th className="px-3 py-2 text-right font-medium">Available</th><th className="px-3 py-2 text-right font-medium">Customers</th><th className="px-3 py-2 font-medium">Last activity</th>
                </tr></thead>
                <tbody>
                  {d && d.resellers.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">No resellers yet.</td></tr>}
                  {d?.resellers.map((r) => (
                    <tr key={r.telegramId} className="border-b border-border last:border-0">
                      <td className="px-4 py-2.5">{r.username ? "@" + r.username : r.telegramId}</td><td className="px-3 py-2.5 capitalize">{r.status}</td>
                      <td className="num px-3 py-2.5 text-right">{r.creditsBought}</td><td className="num px-3 py-2.5 text-right">{r.available}</td>
                      <td className="num px-3 py-2.5 text-right">{r.activeCustomers} / {r.customers}</td><td className="px-3 py-2.5 whitespace-nowrap">{formatDateTime(r.lastActivity)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </>
  );
}

export default function ReportsPage() {
  return <AdminShell><Reports /></AdminShell>;
}
