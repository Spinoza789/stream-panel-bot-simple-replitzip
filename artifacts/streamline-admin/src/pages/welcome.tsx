import { ArrowRight, Hourglass, ListChecks, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/admin/bits";
import { usePageMeta } from "@/lib/meta";
import { useAuth } from "@/lib/auth";

const points = [
  { icon: ListChecks, t: "Order status in plain words", d: "Every order explains what it's waiting on, so you don't have to query the bot to find out." },
  { icon: Hourglass, t: "Stuck trials, recoverable", d: "Spot trials that never started account creation and re-queue the same order after a deliberate check." },
  { icon: ShieldCheck, t: "Owner only", d: "The desk opens only for the owner's Replit account, bound on the server. No credentials are ever shown." },
];

export default function Welcome() {
  const { login } = useAuth();
  usePageMeta("Welcome", "Owner operations desk for the Streamline Telegram membership business. Sign in to view orders and trials.");
  return (
    <div className="grain relative min-h-[100dvh] overflow-hidden bg-background">
      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Logo />
        <div className="flex items-center gap-2">
          <button onClick={login} className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90" data-testid="button-login-header">Sign in</button>
        </div>
      </header>
      <main className="relative z-10 mx-auto grid max-w-6xl gap-12 px-5 pb-16 pt-10 lg:grid-cols-[1.1fr_1fr] lg:pt-20">
        <div className="rise">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" /> Streamline operations desk
          </p>
          <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight md:text-[56px]">
            Your memberships,<br />without the bot commands.
          </h1>
          <p className="mt-5 max-w-md text-[17px] leading-relaxed text-muted-foreground">
            One place to see what every Telegram order is doing, which trials are stuck, and whether the server is set up to deliver.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button onClick={login} className="group inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-transform hover:-translate-y-0.5" data-testid="button-login-hero">
              Sign in <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </button>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">Signing in does not grant access by itself. The desk opens only for the owner's Replit account, set up once on the server.</p>
        </div>
        <div className="rise rise-2 space-y-3">
          {points.map((p, i) => (
            <div key={p.t} className={`rise rise-${i + 2} flex gap-4 rounded-xl border border-card-border bg-card p-5 shadow-[0_1px_3px_hsl(176_20%_20%/0.06)]`}>
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[hsl(176_40%_92%)] text-primary"><p.icon className="h-5 w-5" /></div>
              <div>
                <p className="font-semibold">{p.t}</p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{p.d}</p>
              </div>
            </div>
          ))}
        </div>
      </main>
      <div className="pointer-events-none absolute -right-40 top-40 h-[520px] w-[520px] rounded-full bg-[hsl(42_74%_66%/0.18)] blur-3xl" />
    </div>
  );
}
