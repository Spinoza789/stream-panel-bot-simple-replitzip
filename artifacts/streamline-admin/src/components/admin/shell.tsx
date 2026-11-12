import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { useAuth, displayName } from "@/lib/auth";
import { useGetAdminOverview, getGetAdminOverviewQueryKey } from "@workspace/api-client-react";
import { BarChart3, Home, Hourglass, LifeBuoy, LogOut, Menu, Moon, Package, ScrollText, Search, Settings2, Sun, Tv, Users, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { prefetchLikelyScreens, prefetchScreen } from "@/lib/prefetch";
import { Logo } from "./bits";
import { AccessGate, LIVE, useAdminReady } from "./access";

export function AdminShell({ children }: { children: ReactNode }) {
  return (
    <AccessGate>
      <Frame>{children}</Frame>
    </AccessGate>
  );
}

function useTheme() {
  const [dark, setDark] = useState(() => { try { return localStorage.getItem("admin-theme") === "dark"; } catch { return false; } });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("admin-theme", dark ? "dark" : "light"); } catch { /* private mode */ }
  }, [dark]);
  return [dark, setDark] as const;
}

function Frame({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useTheme();
  const [, setLocation] = useLocation();
  const [query, setQuery] = useState("");
  const { user, logout } = useAuth();
  const name = displayName(user);
  const initials = (name[0] ?? "O").toUpperCase();
  const search = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim().slice(0, 80);
    setLocation(q ? `/orders?q=${encodeURIComponent(q)}` : "/orders");
  };
  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 bg-[#1a1a1a] px-3 text-[#e3e3e3] md:px-4">
        <button className="rounded-md p-1.5 hover:bg-white/10 lg:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu" data-testid="button-menu">
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
        <Link href="/dashboard" data-testid="link-logo" className="shrink-0 lg:w-56"><Logo /></Link>
        <form onSubmit={search} role="search" className="relative mx-auto hidden min-w-0 max-w-xl flex-1 sm:block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#b5b5b5]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={80}
            placeholder="Search orders by ID, Telegram ID or @username"
            aria-label="Search orders"
            data-testid="input-global-search"
            className="h-8 w-full rounded-lg border border-[#4a4a4a] bg-[#303030] pl-9 pr-3 text-sm text-white placeholder:text-[#b5b5b5] focus:border-white focus:outline-none"
          />
        </form>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <button onClick={() => setDark(!dark)} className="rounded-md p-1.5 text-[#b5b5b5] transition-colors hover:bg-white/10 hover:text-white" title={dark ? "Switch to light" : "Switch to dark"} aria-label="Toggle dark mode" data-testid="button-theme">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <span className="hidden text-sm text-[#e3e3e3] sm:inline" data-testid="text-user-email">{name}</span>
          {user?.profileImageUrl ? (
            <img src={user.profileImageUrl} alt="" className="h-7 w-7 rounded-md object-cover" />
          ) : (
            <span className="grid h-7 w-7 place-items-center rounded-md bg-[#ffd79d] text-xs font-semibold text-[#5e4200]">{initials}</span>
          )}
          <button
            onClick={logout}
            className="rounded-md p-1.5 text-[#b5b5b5] transition-colors hover:bg-white/10 hover:text-white"
            title="Sign out"
            data-testid="button-signout"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>
      <div className="flex">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 top-14 z-20 w-64 max-w-[85vw] overflow-y-auto border-r border-sidebar-border bg-sidebar p-2 transition-transform duration-200 lg:sticky lg:h-[calc(100dvh-3.5rem)] lg:w-60 lg:translate-x-0",
            open ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <form onSubmit={(e) => { search(e); setOpen(false); }} role="search" className="relative mb-2 sm:hidden">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} maxLength={80} placeholder="Search orders" aria-label="Search orders" data-testid="input-drawer-search"
              className="h-9 w-full rounded-lg border border-input bg-card pl-8 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
          </form>
          <Nav onNavigate={() => setOpen(false)} />
        </aside>
        {open && <div className="fixed inset-0 top-14 z-10 bg-black/30 lg:hidden" onClick={() => setOpen(false)} />}
        <main className="min-w-0 flex-1 px-3 py-4 sm:px-5 sm:py-5 lg:px-6 lg:py-6">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}

function Nav({ onNavigate }: { onNavigate: () => void }) {
  const [loc] = useLocation();
  const ready = useAdminReady();
  const ov = useGetAdminOverview({ query: { enabled: ready, queryKey: getGetAdminOverviewQueryKey(), ...LIVE } });
  const qc = useQueryClient();
  // Once this page has its own data, fetch the screens most often opened next so the first click
  // on each shows straight away. Hovering a link fetches that screen too.
  const loaded = ready && ov.isSuccess;
  useEffect(() => {
    if (!loaded) return;
    let stop = false;
    const timer = setTimeout(() => { void prefetchLikelyScreens(qc, loc, () => stop); }, 400);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, qc]);
  const warm = (href: string) => { if (ready) void prefetchScreen(qc, href); };
  const items = [
    { href: "/dashboard", label: "Home", icon: Home, count: undefined as number | undefined, hot: false },
    { href: "/orders", label: "Orders", icon: Package, count: ov.data?.review, hot: true },
    { href: "/trials", label: "Trials", icon: Hourglass, count: undefined, hot: false },
    { href: "/subscriptions", label: "Subscriptions", icon: Tv, count: undefined, hot: false },
    { href: "/resellers", label: "Resellers", icon: Users, count: ov.data?.activeResellers, hot: false },
    { href: "/tickets", label: "Tickets", icon: LifeBuoy, count: ov.data?.openTickets, hot: true },
    { href: "/reports", label: "Reports", icon: BarChart3, count: undefined, hot: false },
    { href: "/logs", label: "Logs", icon: ScrollText, count: undefined, hot: false },
    { href: "/settings", label: "Settings", icon: Settings2, count: undefined, hot: false },
  ];
  return (
    <nav className="flex flex-col gap-0.5 lg:h-full">
      {items.map((it) => {
        const active = loc === it.href || ((it.href === "/orders" || it.href === "/resellers") && loc.startsWith(it.href + "/"));
        return (
          <Link
            key={it.href}
            href={it.href}
            onClick={onNavigate}
            onMouseEnter={() => warm(it.href)}
            onFocus={() => warm(it.href)}
            data-testid={`link-nav-${it.label.toLowerCase()}`}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-2.5 py-2.5 text-[14px] font-medium transition-colors lg:py-1.5 lg:text-[13px]",
              active ? "bg-white text-foreground shadow-[0_1px_0_rgba(0,0,0,0.05)] dark:bg-white/10 dark:text-white" : "text-sidebar-foreground hover:bg-black/5 dark:hover:bg-white/5",
            )}
          >
            <it.icon className={cn("h-[18px] w-[18px]", active ? "text-[#29845a]" : "text-[#4a4a4a] dark:text-[#a3a3a3]")} />
            {it.label}
            {!!it.count && (
              <span className={cn("ml-auto rounded-md px-1.5 py-px text-[11px] font-semibold", it.hot ? "bg-[#ffd79d] text-[#5e4200]" : "bg-[#e3e3e3] text-foreground dark:bg-white/10")} title={it.label === "Orders" ? "In review" : it.label === "Resellers" ? "Active resellers" : it.label === "Tickets" ? "Waiting for a reply" : "Trials"}>
                {it.count}
              </span>
            )}
          </Link>
        );
      })}
      <p className="mt-6 px-2.5 pb-1 text-[11px] lg:mt-auto leading-snug text-muted-foreground">Live from the checkout database. Refreshes every 30 seconds and when you return to this tab.</p>
    </nav>
  );
}
