import { ArrowRight } from "lucide-react";
import { Logo } from "@/components/admin/bits";
import { usePageMeta } from "@/lib/meta";
import { useLocation } from "wouter";

export default function Welcome() {
  const [, setLocation] = useLocation();
  usePageMeta("Welcome", "Owner operations desk for the Streamline Telegram membership business. Sign in to view orders and trials.");
  return (
    <div className="min-h-[100dvh] bg-background">
      <main className="mx-auto flex max-w-md flex-col px-5 pb-16 pt-14">
        <Logo />
        <h1 className="mt-7 text-[22px] font-semibold tracking-tight">Log in to Streamline Admin</h1>
        <p className="mt-1 text-sm text-muted-foreground">Orders, stuck trials and server readiness in one place.</p>
        <div className="card-shadow mt-6 rounded-xl bg-card p-5">
          <button onClick={() => setLocation("/sign-in")} className="group inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground shadow-[inset_0_-1px_0_rgba(0,0,0,.3)] hover:bg-[#1a1a1a]" data-testid="button-login-hero">
            Log in <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          <p className="mt-4 text-xs leading-relaxed text-muted-foreground">Use the owner username or email and password. First time here? Use the setup page with the server setup code.</p>
        </div>
      </main>
    </div>
  );
}
