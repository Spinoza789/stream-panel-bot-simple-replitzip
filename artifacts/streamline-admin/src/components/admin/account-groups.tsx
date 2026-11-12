import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { useListAdminSubscriptionGroups, getListAdminSubscriptionGroupsQueryKey, type AdminSubscription, type ListAdminSubscriptionGroupsParams } from "@workspace/api-client-react";
import { ChevronDown, ChevronRight, Clock, Search, SearchX, Store, Tv, UserRound, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/lib/format";
import { LIVE, useAdminReady } from "./access";
import { Bar, EmptyState, ErrorState, SELLER_STYLE } from "./bits";
import { SubscriptionDialog, SubscriptionsTable } from "@/pages/subscriptions";

type Tone = "retail" | "reseller" | "expired";
const ICON = { retail: UserRound, reseller: Store, expired: Clock };

/** A titled block that opens and closes, with a coloured edge saying whose accounts it holds. Rows render only while open. */
function Section({ id, tone, title, subtitle, count, open, onToggle, children }: {
  id: string; tone: Tone; title: ReactNode; subtitle?: ReactNode; count: number; open: boolean; onToggle: () => void; children: ReactNode;
}) {
  const Icon = ICON[tone];
  return (
    <section className={cn("rise card-shadow overflow-hidden rounded-xl border-l-4 bg-card", tone === "expired" ? "border-l-[#b5b5b5]" : SELLER_STYLE[tone].accent)} data-testid={`section-${id}`}>
      <button type="button" onClick={onToggle} aria-expanded={open} data-testid={`toggle-${id}`}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-[#f7f7f7] dark:hover:bg-white/5">
        <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-lg", tone === "expired" ? "bg-[#ebebeb] text-[#616161] dark:bg-white/10 dark:text-[#b5b5b5]" : SELLER_STYLE[tone].badge)}><Icon className="h-[18px] w-[18px]" /></span>
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate text-[15px] font-semibold", tone === "expired" && "text-muted-foreground")}>{title}</span>
          {subtitle && <span className="block truncate text-xs text-muted-foreground">{subtitle}</span>}
        </span>
        <span className="num shrink-0 rounded-md bg-[#ebebeb] px-2 py-0.5 text-xs font-semibold text-foreground dark:bg-white/10">{count}</span>
        {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
      </button>
      {open && <div className="border-t border-border">{children}</div>}
    </section>
  );
}

function Heading({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return <div className="flex items-end justify-between gap-3 px-1 pt-2"><h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{children}</h2>{aside}</div>;
}

type View = "all" | "direct" | "resellers" | "expired";

/**
 * Trials or subscriptions, kept visibly apart: your own customers (green), then one section per
 * reseller (violet), then everything expired. A row of filters narrows to one of those, and one
 * search box covers them all. With `reseller` set it shows just that reseller's accounts.
 */
export function AccountGroups({ kind, reseller }: { kind: "trial" | "paid"; reseller?: number }) {
  const ready = useAdminReady();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [view, setView] = useState<View>("all");
  // Sections remember being opened or closed by hand; otherwise your own customers start open and resellers start folded.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
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
  const direct = d?.groups.find((g) => g.source === "retail");
  const resellers = d?.groups.filter((g) => g.source === "reseller") ?? [];
  const resellerAccounts = resellers.reduce((n, g) => n + g.items.length, 0);
  const expiredCount = d?.expired.length ?? 0;
  const startsOpen = (key: string) => (key === "expired" ? view === "expired" : !!reseller || key === "direct" || resellers.length === 1);
  const isOpen = (key: string) => (q ? true : toggled[key] ?? startsOpen(key));
  const toggle = (key: string) => setToggled({ ...toggled, [key]: !isOpen(key) });
  const setAll = (value: boolean) => setToggled({ ...toggled, ...Object.fromEntries(resellers.map((g) => [g.key, value])) });
  const allOpen = resellers.length > 0 && resellers.every((g) => isOpen(g.key));
  const tabs: [View, string, number][] = [["all", "All", d?.total ?? 0], ["direct", "Your customers", direct?.items.length ?? 0], ["resellers", "Resellers", resellerAccounts], ["expired", "Expired", expiredCount]];
  const show = (part: View) => !!reseller || view === "all" || view === part;
  const nothingActive = !direct && resellers.length === 0;

  return (
    <div className="space-y-3" data-testid={`groups-${kind}`}>
      <div className="flex flex-col gap-2.5 md:flex-row md:items-center md:justify-between">
        {!reseller && (
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Whose accounts">
            {tabs.map(([value, label, count]) => (
              <button key={value} role="tab" aria-selected={view === value} onClick={() => setView(value)} data-testid={`tab-${kind}-${value}`}
                className={cn("flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors sm:px-3",
                  view === value ? "card-shadow bg-card text-foreground" : "text-muted-foreground hover:bg-black/5 hover:text-foreground dark:hover:bg-white/5")}>
                {value === "direct" && <span className={cn("h-2 w-2 rounded-full", SELLER_STYLE.retail.dot)} />}
                {value === "resellers" && <span className={cn("h-2 w-2 rounded-full", SELLER_STYLE.reseller.dot)} />}
                {label}<span className="num text-xs text-muted-foreground">{d ? count : ""}</span>
              </button>
            ))}
          </div>
        )}
        <div className={cn("relative w-full", reseller ? "md:max-w-sm" : "md:max-w-xs")}>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)}
            placeholder={reseller ? `Search this reseller's ${noun}s` : `Search ${noun}s`} aria-label={`Search ${noun}s by username, customer, Telegram ID or reseller`}
            className="h-10 bg-card pl-8 pr-8 text-sm md:h-9 md:text-[13px]" data-testid={`input-search-${kind}`} />
          {text && <button className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear"><X className="h-4 w-4" /></button>}
        </div>
      </div>
      {d && <p className="num px-1 text-sm text-muted-foreground" data-testid={`text-summary-${kind}`}>{d.active.toLocaleString()} {noun}{d.active === 1 ? "" : "s"} active · {expiredCount.toLocaleString()} expired{q ? ` · matching "${q}"` : ""}</p>}

      {list.isError ? <ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} />
        : !d ? <div className="card-shadow space-y-3 rounded-xl bg-card p-4"><Bar className="h-4" /><Bar className="h-4 w-2/3" /><Bar className="h-4 w-1/2" /></div>
        : d.total === 0 ? (
          <div className="card-shadow rounded-xl bg-card">
            {q ? <EmptyState icon={<SearchX className="h-5 w-5" />} title={`No ${noun}s match "${q}"`}><button className="font-medium text-primary hover:underline" onClick={() => setText("")}>Clear search</button></EmptyState>
              : <EmptyState icon={<Tv className="h-5 w-5" />} title={`No ${noun}s yet`}>{kind === "trial" ? "Trials appear here once their login has been created." : "Subscriptions appear here once their login has been created."}</EmptyState>}
          </div>
        ) : (
          <div className={cn("space-y-3 transition-opacity", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
            {reseller ? (
              resellers.map((g) => (
                <Section key={g.key} id={g.key} tone="reseller" count={g.items.length} open={isOpen(g.key)} onToggle={() => toggle(g.key)} title="Active" subtitle={`Running ${noun}s`}>
                  <SubscriptionsTable items={g.items} onOpen={setOpen} />
                </Section>
              ))
            ) : (
              <>
                {show("direct") && (
                  <>
                    <Heading>Your customers</Heading>
                    {direct ? (
                      <Section id="direct" tone="retail" count={direct.items.length} open={isOpen("direct")} onToggle={() => toggle("direct")}
                        title="Direct customers" subtitle="Sold by you through the bot, or added here">
                        <SubscriptionsTable items={direct.items} onOpen={setOpen} />
                      </Section>
                    ) : <p className="card-shadow rounded-xl bg-card px-4 py-3 text-sm text-muted-foreground">No active {noun}s of your own{q ? " match this search" : ""}.</p>}
                  </>
                )}
                {show("resellers") && (
                  <>
                    <Heading aside={resellers.length > 1 && !q ? <button className="text-xs font-medium text-primary hover:underline" onClick={() => setAll(!allOpen)} data-testid={`button-toggle-all-${kind}`}>{allOpen ? "Collapse all" : "Expand all"}</button> : undefined}>
                      Resellers{resellers.length ? ` · ${resellers.length}` : ""}
                    </Heading>
                    {resellers.length === 0 && <p className="card-shadow rounded-xl bg-card px-4 py-3 text-sm text-muted-foreground">No reseller has an active {noun}{q ? " matching this search" : ""}.</p>}
                    {resellers.map((g) => (
                      <Section key={g.key} id={g.key} tone="reseller" count={g.items.length} open={isOpen(g.key)} onToggle={() => toggle(g.key)}
                        title={g.resellerUsername ? "@" + g.resellerUsername : "Reseller " + g.resellerTelegramId}
                        subtitle={<>Reseller · Telegram ID <span className="font-mono">{g.resellerTelegramId}</span></>}>
                        <SubscriptionsTable items={g.items} onOpen={setOpen} />
                        <div className="border-t border-border px-4 py-2.5 text-sm"><Link href={`/resellers/${g.resellerTelegramId}`} className="font-medium text-primary hover:underline">Open this reseller's page</Link></div>
                      </Section>
                    ))}
                  </>
                )}
              </>
            )}
            {show("expired") && expiredCount > 0 && (
              <>
                {!reseller && <Heading>Expired</Heading>}
                <Section id="expired" tone="expired" count={expiredCount} open={isOpen("expired")} onToggle={() => toggle("expired")}
                  title="Expired" subtitle={`Past their expiry or disabled${reseller ? "" : ", from you and every reseller"}`}>
                  <SubscriptionsTable items={d.expired} onOpen={setOpen} showSeller={!reseller} />
                </Section>
              </>
            )}
            {view === "expired" && expiredCount === 0 && <p className="card-shadow rounded-xl bg-card px-4 py-3 text-sm text-muted-foreground">Nothing has expired{q ? " that matches this search" : ""}.</p>}
            {!!reseller && nothingActive && <p className="px-1 text-sm text-muted-foreground">No active {noun}s{q ? " match this search" : ""}.</p>}
          </div>
        )}
      {open && <SubscriptionDialog s={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
