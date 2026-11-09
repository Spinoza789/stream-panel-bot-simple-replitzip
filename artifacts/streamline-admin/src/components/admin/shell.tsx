import { useState, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { useAuth, displayName } from "@/lib/auth";
import { useGetAdminOverview, getGetAdminOverviewQueryKey } from "@workspace/api-client-react";
import { Home, Hourglass, LogOut, Menu, Package, Settings2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "./bits";
import { AccessGate, LIVE, useAdminReady } from "./access";

export function AdminShell({ children }: { children: ReactNode }) {
  return (
    <AccessGate>
      <Frame>{children}</Frame>
    </AccessGate>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { user, logout } = useAuth();
  const email = user?.email ?? "";
  const initials = (displayName(user)[0] ?? "O").toUpperCase();
  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 bg-[hsl(176_45%_11%)] px-3 text-[hsl(60_25%_92%)] md:px-4">
        <button className="rounded-md p-1.5 hover:bg-white/10 md:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu" data-testid="button-menu">
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
        <Link href="/dashboard" data-testid="link-logo"><Logo /></Link>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-sm text-white/60 sm:inline" data-testid="text-user-email">{email}</span>
          {user?.profileImageUrl ? (
            <img src={user.profileImageUrl} alt="" className="h-8 w-8 rounded-lg object-cover" />
          ) : (
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-[hsl(42_74%_66%)] text-sm font-semibold text-[hsl(30_50%_14%)]">{initials}</span>
          )}
          <button
            onClick={logout}
            className="rounded-md p-1.5 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
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
            "fixed inset-y-0 left-0 top-14 z-20 w-60 border-r border-sidebar-border bg-sidebar p-3 transition-transform duration-200 md:sticky md:h-[calc(100dvh-3.5rem)] md:translate-x-0",
            open ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <Nav onNavigate={() => setOpen(false)} />
        </aside>
        {open && <div className="fixed inset-0 top-14 z-10 bg-black/20 md:hidden" onClick={() => setOpen(false)} />}
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">
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
  const items = [
    { href: "/dashboard", label: "Home", icon: Home, count: undefined as number | undefined },
    { href: "/orders", label: "Orders", icon: Package, count: ov.data?.review },
    { href: "/trials", label: "Trials", icon: Hourglass, count: ov.data?.trials },
    { href: "/settings", label: "Settings", icon: Settings2, count: undefined },
  ];
  return (
    <nav className="flex h-full flex-col gap-0.5">
      {items.map((it) => {
        const active = loc === it.href || (it.href === "/orders" && loc.startsWith("/orders/"));
        return (
          <Link
            key={it.href}
            href={it.href}
            onClick={onNavigate}
            data-testid={`link-nav-${it.label.toLowerCase()}`}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors",
              active ? "bg-sidebar-accent text-foreground shadow-[0_1px_2px_hsl(176_20%_20%/0.1)]" : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-foreground",
            )}
          >
            <it.icon className={cn("h-4 w-4", active ? "text-primary" : "")} />
            {it.label}
            {!!it.count && (
              <span className="ml-auto rounded-full bg-[hsl(42_85%_84%)] px-1.5 font-mono text-[11px] text-[hsl(32_70%_22%)]" title={it.label === "Orders" ? "In review" : "Trials"}>
                {it.count}
              </span>
            )}
          </Link>
        );
      })}
      <p className="mt-auto px-2.5 pb-1 text-[11px] leading-snug text-muted-foreground">Live from the checkout database. Refreshes every 30 seconds and when you return to this tab.</p>
    </nav>
  );
}
