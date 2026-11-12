import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { useListAdminSubscriptionGroups, getListAdminSubscriptionGroupsQueryKey, type AdminSubscription, type ListAdminSubscriptionGroupsParams } from "@workspace/api-client-react";
import { ChevronDown, ChevronRight, Search, SearchX, Tv, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/lib/format";
import { LIVE, useAdminReady } from "./access";
import { Bar, EmptyState, ErrorState } from "./bits";
import { SubscriptionDialog, SubscriptionsTable } from "@/pages/subscriptions";

/** A titled block that opens and closes. Rows are only rendered while it is open. */
function Section({ id, title, subtitle, count, open, onToggle, tone, children }: {
  id: string; title: ReactNode; subtitle?: ReactNode; count: number; open: boolean; onToggle: () => void; tone?: "muted"; children: ReactNode;
}) {
  return (
    <section className="rise card-shadow overflow-hidden rounded-xl bg-card" data-testid={`section-${id}`}>
      <button type="button" onClick={onToggle} aria-expanded={open} data-testid={`toggle-${id}`}
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-[#f7f7f7] dark:hover:bg-white/5">
        {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
        <span className={cn("text-[14px] font-semibold", tone === "muted" && "text-muted-foreground")}>{title}</span>
        {subtitle && <span className="truncate text-xs text-muted-foreground">{subtitle}</span>}
        <span className="ml-auto rounded-md bg-[#e3e3e3] px-1.5 py-px text-[11px] font-semibold text-foreground dark:bg-white/10">{count}</span>
      </button>
      {open && <div className="border-t border-border">{children}</div>}
    </section>
  );
}

/**
 * Trials or subscriptions in collapsible sections: your direct customers, then one section per
 * reseller, then everything that has expired at the bottom. One search box filters all of them.
 * With `reseller` set it shows just that reseller's accounts.
 */
export function AccountGroups({ kind, reseller }: { kind: "trial" | "paid"; reseller?: number }) {
  const ready = useAdminReady();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const [expiredOpen, setExpiredOpen] = useState(false);
  const [open, setOpen] = useState<AdminSubscription | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setQ(text.trim().slice(0, 80)), 300);
    return () => clearTimeout(timer.current);
  }, [text]);
  const params: ListAdminSubscriptionGroupsParams = { kind };
  if (q) params.q = q;
  if (reseller) params.reseller = reseller;
  const list = useListAdminSubscriptionGroups(params, { query: { enabled: ready, queryKey: getListAdminSubscriptionGroupsQueryKey(params), placeholderData: (p) => p, ...LIVE } });
  const d = list.data;
  const noun = kind === "trial" ? "trial" : "subscription";
  const plural = (n: number) => `${n.toLocaleString()} ${noun}${n === 1 ? "" : "s"}`;
  // While searching, every section with a match is shown open, including Expired.
  const isOpen = (key: string) => (q ? true : !closed[key]);
  return (
    <div className="space-y-3" data-testid={`groups-${kind}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)}
            placeholder={reseller ? `Search this reseller's ${noun}s` : `Search ${noun}s: username, customer, Telegram ID or reseller`}
            className="h-9 bg-card pl-8 pr-8 text-[13px]" data-testid={`input-search-${kind}`} />
          {text && <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear"><X className="h-4 w-4" /></button>}
        </div>
        {d && <p className="num text-sm text-muted-foreground" data-testid={`text-summary-${kind}`}>{plural(d.active)} active · {d.expired.length.toLocaleString()} expired</p>}
      </div>
      {list.isError ? <ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} />
        : !d ? <div className="card-shadow space-y-3 rounded-xl bg-card p-4"><Bar className="h-4" /><Bar className="h-4 w-2/3" /><Bar className="h-4 w-1/2" /></div>
        : d.total === 0 ? (
          <div className="card-shadow rounded-xl bg-card">
            {q ? <EmptyState icon={<SearchX className="h-5 w-5" />} title={`No ${noun}s match "${q}"`}><button className="font-medium text-primary hover:underline" onClick={() => setText("")}>Clear search</button></EmptyState>
              : <EmptyState icon={<Tv className="h-5 w-5" />} title={`No ${noun}s yet`}>{kind === "trial" ? "Trials appear here once their login has been created." : "Subscriptions appear here once their login has been created."}</EmptyState>}
          </div>
        ) : (
          <div className={cn("space-y-3 transition-opacity", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
            {d.groups.map((g) => (
              <Section key={g.key} id={g.key} count={g.items.length} open={isOpen(g.key)} onToggle={() => setClosed({ ...closed, [g.key]: !closed[g.key] })}
                title={reseller ? "Active" : g.source === "retail" ? "Direct customers" : g.resellerUsername ? "@" + g.resellerUsername : "Reseller " + g.resellerTelegramId}
                subtitle={g.source === "retail" ? "Sold by you through the bot or added here" : !reseller ? <>Reseller · <span className="font-mono">{g.resellerTelegramId}</span></> : undefined}>
                <SubscriptionsTable items={g.items} onOpen={setOpen} />
                {g.source === "reseller" && !reseller && (
                  <div className="border-t border-border px-4 py-2 text-xs"><Link href={`/resellers/${g.resellerTelegramId}`} className="font-medium text-primary hover:underline">Open this reseller</Link></div>
                )}
              </Section>
            ))}
            {d.groups.length === 0 && <p className="px-1 text-sm text-muted-foreground">No active {noun}s{q ? " match this search" : ""}. Expired ones are below.</p>}
            {d.expired.length > 0 && (
              <Section id="expired" tone="muted" count={d.expired.length} open={q ? true : expiredOpen} onToggle={() => setExpiredOpen(!expiredOpen)}
                title="Expired" subtitle={`${noun[0].toUpperCase()}${noun.slice(1)}s past their expiry or disabled`}>
                <SubscriptionsTable items={d.expired} onOpen={setOpen} />
              </Section>
            )}
          </div>
        )}
      {open && <SubscriptionDialog s={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
