import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useGetAdminRateCard, getGetAdminRateCardQueryKey, useUpdateAdminRateCard, type AdminRateCard } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Bar, ErrorState, Panel } from "./bits";
import { useAdminReady } from "./access";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, gbp } from "@/lib/format";

/** Subscription prices, credit packs (add, edit, remove), credit costs and trial limits, edited in place. Every change needs a reason and is audited. */
export function RateCardPanel() {
  const ready = useAdminReady();
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useGetAdminRateCard({ query: { enabled: ready, queryKey: getGetAdminRateCardQueryKey() } });
  const upd = useUpdateAdminRateCard();
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const d = q.data;
  const value = (key: string, fallback: number | string) => (key in draft ? draft[key] : String(fallback));
  const save = (category: "package" | "package_add" | "package_delete" | "plan" | "cost" | "trials", values: (string | number | boolean)[]) => {
    if (reason.trim().length < 3) { toast({ title: "Give a reason first", description: "A short note goes into the audit log with every price change.", variant: "destructive" }); return; }
    upd.mutate({ data: { category, values, reason: reason.trim() } }, {
      onSuccess: (card: AdminRateCard) => { qc.setQueryData(getGetAdminRateCardQueryKey(), card); setDraft({}); toast({ title: "Rate card updated" }); },
      onError: (e) => toast({ title: "Not saved", description: errorMessage(e), variant: "destructive" }),
    });
  };
  const savePackage = (e: FormEvent, id: string) => {
    e.preventDefault();
    const p = d!.packages.find((x) => x.id === id)!;
    const pounds = parseFloat(value("p-price-" + id, p.pricePence / 100));
    const credits = parseInt(value("p-credits-" + id, p.credits), 10);
    const active = value("p-active-" + id, p.active ? "1" : "0") === "1";
    if (!(pounds > 0) || !(credits > 0)) return;
    save("package", [id, Math.round(pounds * 100), credits, active]);
  };
  return (
    <Panel title="Rate card" aside={<span className="text-xs text-muted-foreground">Changes apply to new orders only</span>}>
      {q.isError ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : !d ? <div className="space-y-3"><Bar className="h-8" /><Bar className="h-8" /><Bar className="h-8" /></div> : (
        <div className="space-y-5 text-sm">
          <div>
            <label className="text-xs font-medium text-muted-foreground" htmlFor="rate-reason">Reason for the change (audited)</label>
            <Input id="rate-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. Spring price update" className="mt-1 h-9" data-testid="input-rate-reason" />
          </div>
          <div>
            <h3 className="mb-1 font-semibold">Subscription prices</h3>
            <p className="mb-2 text-xs text-muted-foreground">What customers pay in the bot and on the website, in pounds. Hidden plans disappear from the menus; existing customers are not affected.</p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px]">
                <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1 pr-2 font-medium">Plan</th><th className="py-1 pr-2 font-medium">Devices</th><th className="py-1 pr-2 font-medium">Price (£)</th><th className="py-1 pr-2 font-medium">Per month</th><th className="py-1 pr-2 font-medium">On sale</th><th /></tr></thead>
                <tbody>
                  {(d.plans ?? []).map((p) => {
                    const price = parseFloat(value("pl-price-" + p.id, p.gbpPrice)) || 0;
                    return (
                      <tr key={p.id} className="border-t border-border">
                        <td className="py-1.5 pr-2">{p.name}</td>
                        <td className="py-1.5 pr-2 text-muted-foreground">{p.connections}</td>
                        <td className="py-1.5 pr-2"><Input value={value("pl-price-" + p.id, p.gbpPrice)} onChange={(e) => setDraft({ ...draft, ["pl-price-" + p.id]: e.target.value })} inputMode="decimal" className="h-8 w-24" data-testid={`input-plan-price-${p.id}`} /></td>
                        <td className="num py-1.5 pr-2 text-muted-foreground">{p.months ? gbp(price / p.months) : "—"}</td>
                        <td className="py-1.5 pr-2">
                          <select value={value("pl-active-" + p.id, p.active ? "1" : "0")} onChange={(e) => setDraft({ ...draft, ["pl-active-" + p.id]: e.target.value })} className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]"><option value="1">Yes</option><option value="0">Hidden</option></select>
                        </td>
                        <td className="py-1.5 text-right"><Button size="sm" variant="outline" disabled={upd.isPending || !(price >= 1)} onClick={() => save("plan", [p.id, price.toFixed(2), value("pl-active-" + p.id, p.active ? "1" : "0") === "1"])} data-testid={`button-save-plan-${p.id}`}>Save</Button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <h3 className="mb-2 font-semibold">Credit packs</h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px]">
                <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1 pr-2 font-medium">Pack</th><th className="py-1 pr-2 font-medium">Price (£)</th><th className="py-1 pr-2 font-medium">Credits</th><th className="py-1 pr-2 font-medium">Per credit</th><th className="py-1 pr-2 font-medium">On sale</th><th /></tr></thead>
                <tbody>
                  {d.packages.map((p) => (
                    <tr key={p.id} className="border-t border-border">
                      <td className="py-1.5 pr-2 font-mono text-xs">{p.id}</td>
                      <td className="py-1.5 pr-2"><Input value={value("p-price-" + p.id, (p.pricePence / 100).toFixed(2))} onChange={(e) => setDraft({ ...draft, ["p-price-" + p.id]: e.target.value })} inputMode="decimal" className="h-8 w-24" data-testid={`input-pack-price-${p.id}`} /></td>
                      <td className="py-1.5 pr-2"><Input value={value("p-credits-" + p.id, p.credits)} onChange={(e) => setDraft({ ...draft, ["p-credits-" + p.id]: e.target.value })} inputMode="numeric" className="h-8 w-20" data-testid={`input-pack-credits-${p.id}`} /></td>
                      <td className="num py-1.5 pr-2 text-muted-foreground">{gbp((parseFloat(value("p-price-" + p.id, p.pricePence / 100)) || 0) / Math.max(1, parseInt(value("p-credits-" + p.id, p.credits), 10) || 1))}</td>
                      <td className="py-1.5 pr-2">
                        <select value={value("p-active-" + p.id, p.active ? "1" : "0")} onChange={(e) => setDraft({ ...draft, ["p-active-" + p.id]: e.target.value })} className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]"><option value="1">Yes</option><option value="0">Hidden</option></select>
                      </td>
                      <td className="py-1.5 text-right whitespace-nowrap"><Button size="sm" variant="outline" onClick={(e) => savePackage(e, p.id)} disabled={upd.isPending} data-testid={`button-save-pack-${p.id}`}>Save</Button> <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" disabled={upd.isPending} onClick={() => { if (confirm(`Remove the ${gbp(p.pricePence / 100)} pack? Past purchases keep their own record.`)) save("package_delete", [p.id]); }} data-testid={`button-delete-pack-${p.id}`}>Remove</Button></td>
                    </tr>
                  ))}
                  <tr className="border-t border-border">
                    <td className="py-1.5 pr-2 text-xs text-muted-foreground">New pack</td>
                    <td className="py-1.5 pr-2"><Input value={value("np-price", "")} onChange={(e) => setDraft({ ...draft, "np-price": e.target.value })} inputMode="decimal" placeholder="50" className="h-8 w-24" data-testid="input-new-pack-price" /></td>
                    <td className="py-1.5 pr-2"><Input value={value("np-credits", "")} onChange={(e) => setDraft({ ...draft, "np-credits": e.target.value })} inputMode="numeric" placeholder="16" className="h-8 w-20" data-testid="input-new-pack-credits" /></td>
                    <td className="num py-1.5 pr-2 text-muted-foreground">{parseFloat(value("np-price", "")) > 0 && parseInt(value("np-credits", ""), 10) > 0 ? gbp(parseFloat(value("np-price", "")) / parseInt(value("np-credits", ""), 10)) : "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-muted-foreground">On sale</td>
                    <td className="py-1.5 text-right"><Button size="sm" disabled={upd.isPending || !(parseFloat(value("np-price", "")) > 0 && parseInt(value("np-credits", ""), 10) > 0)} onClick={() => save("package_add", [Math.round(parseFloat(value("np-price", "")) * 100), parseInt(value("np-credits", ""), 10)])} data-testid="button-add-pack">Add pack</Button></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <h3 className="mb-2 font-semibold">Subscription cost in credits</h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px]">
                <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1 pr-2 font-medium">Duration</th>{[1, 2, 3].map((c) => <th key={c} className="py-1 pr-2 font-medium">{c} device{c > 1 ? "s" : ""}</th>)}</tr></thead>
                <tbody>
                  {[...new Set(d.costs.map((c) => c.months))].map((m) => (
                    <tr key={m} className="border-t border-border">
                      <td className="py-1.5 pr-2">{m} month{m > 1 ? "s" : ""}</td>
                      {[1, 2, 3].map((c) => {
                        const cost = d.costs.find((x) => x.months === m && x.connections === c);
                        const key = `c-${m}-${c}`;
                        return (
                          <td key={c} className="py-1.5 pr-2">
                            <form className="flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); const n = parseInt(value(key, cost?.credits ?? 0), 10); if (n > 0) save("cost", [m, c, n]); }}>
                              <Input value={value(key, cost?.credits ?? "")} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} inputMode="numeric" className="h-8 w-16" data-testid={`input-cost-${m}-${c}`} />
                              {key in draft && <Button type="submit" size="sm" variant="outline" disabled={upd.isPending}>Save</Button>}
                            </form>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); save("trials", [parseInt(value("t-daily", d.trialDaily), 10), parseInt(value("t-active", d.trialActive), 10)]); }}>
            <div><label className="text-xs font-medium text-muted-foreground">Free tests per reseller per day</label><Input value={value("t-daily", d.trialDaily)} onChange={(e) => setDraft({ ...draft, "t-daily": e.target.value })} inputMode="numeric" className="mt-1 h-8 w-24" data-testid="input-trial-daily" /></div>
            <div><label className="text-xs font-medium text-muted-foreground">Tests running at once</label><Input value={value("t-active", d.trialActive)} onChange={(e) => setDraft({ ...draft, "t-active": e.target.value })} inputMode="numeric" className="mt-1 h-8 w-24" data-testid="input-trial-active" /></div>
            <Button type="submit" size="sm" variant="outline" disabled={upd.isPending}>Save limits</Button>
          </form>
        </div>
      )}
    </Panel>
  );
}
