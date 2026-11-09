import { useState, type ReactNode } from "react";
import { Check, Copy, AlertTriangle, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { humanize, statusTone, type Tone } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

const basePath = import.meta.env.BASE_URL.replace(/\/$/, "");

export function Logo({ className, withWord = true }: { className?: string; withWord?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <img src={`${basePath}/logo.svg`} alt="" className="h-7 w-7 rounded-[7px]" />
      {withWord && (
        <span className="text-[15px] font-semibold tracking-tight">
          Streamline <span className="font-normal opacity-60">Admin</span>
        </span>
      )}
    </span>
  );
}

const toneClass: Record<Tone, string> = {
  success: "bg-[hsl(140_40%_88%)] text-[hsl(140_55%_20%)] before:bg-[hsl(140_50%_36%)]",
  attention: "bg-[hsl(42_85%_84%)] text-[hsl(32_70%_22%)] before:bg-[hsl(36_85%_44%)]",
  critical: "bg-[hsl(4_75%_91%)] text-[hsl(4_65%_32%)] before:bg-[hsl(4_66%_46%)]",
  info: "bg-[hsl(190_45%_88%)] text-[hsl(196_60%_22%)] before:bg-[hsl(194_60%_38%)]",
  neutral: "bg-[hsl(80_10%_88%)] text-[hsl(176_15%_25%)] before:bg-[hsl(176_8%_50%)]",
};

export function StatusBadge({ status, tone }: { status: string; tone?: Tone }) {
  const t = tone ?? statusTone(status);
  return (
    <span
      data-testid={`status-${status}`}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium before:h-1.5 before:w-1.5 before:rounded-full before:content-['']",
        toneClass[t],
      )}
    >
      {humanize(status)}
    </span>
  );
}

export function KindTag({ kind }: { kind: string }) {
  return (
    <span className="rounded-md border border-border bg-background px-1.5 py-0.5 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
      {kind || "—"}
    </span>
  );
}

export function CopyId({ value, label = "ID", short = false }: { value: string; label?: string; short?: boolean }) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();
  const display = short && value.length > 14 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
  return (
    <button
      type="button"
      data-testid={`button-copy-${value}`}
      title={`Copy ${label}`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard
          .writeText(value)
          .then(() => {
            setCopied(true);
            toast({ title: `${label} copied`, description: value });
            setTimeout(() => setCopied(false), 1400);
          })
          .catch(() => toast({ title: "Copy failed", description: "Clipboard is not available in this browser.", variant: "destructive" }));
      }}
      className="group inline-flex max-w-full items-center gap-1.5 rounded-md px-1 py-0.5 font-mono text-[12.5px] text-foreground transition-colors hover:bg-muted"
    >
      <span className="truncate">{display}</span>
      <span className="relative h-3.5 w-3.5 shrink-0 text-muted-foreground">
        <Copy className={cn("absolute inset-0 h-3.5 w-3.5 transition-all duration-200", copied ? "scale-50 opacity-0" : "opacity-0 group-hover:opacity-100")} />
        <Check className={cn("absolute inset-0 h-3.5 w-3.5 text-[hsl(140_50%_32%)] transition-all duration-200", copied ? "scale-100 opacity-100" : "scale-50 opacity-0")} />
      </span>
    </button>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: string; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="rise mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-sm text-muted-foreground">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-tight" data-testid="text-page-title">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({ children, className, title, aside, flush }: { children: ReactNode; className?: string; title?: ReactNode; aside?: ReactNode; flush?: boolean }) {
  return (
    <section className={cn("rise overflow-hidden rounded-xl border border-card-border bg-card shadow-[0_1px_0_hsl(176_20%_20%/0.06),0_1px_3px_hsl(176_20%_20%/0.05)]", className)}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          {aside}
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export function ErrorState({ title = "Couldn't load this", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-[hsl(4_60%_82%)] bg-[hsl(4_70%_97%)] p-4" data-testid="state-error">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
        <div>
          <p className="text-sm font-semibold text-[hsl(4_60%_28%)]">{title}</p>
          <p className="mt-0.5 font-mono text-xs text-[hsl(4_40%_35%)]">{message}</p>
        </div>
      </div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry} data-testid="button-retry">
          <RotateCw className="mr-1.5 h-3.5 w-3.5" /> Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center" data-testid="state-empty">
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-full border border-dashed border-input bg-background text-muted-foreground">{icon}</div>
      <p className="text-sm font-semibold">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function Bar({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-muted", className)} />;
}
