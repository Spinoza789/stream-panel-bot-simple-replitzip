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
      <img src={`${basePath}/logo.svg`} alt="" className="h-7 w-7 rounded-md" />
      {withWord && (
        <span className="text-[15px] font-semibold tracking-tight">
          Streamline <span className="font-normal opacity-60">Admin</span>
        </span>
      )}
    </span>
  );
}

const toneClass: Record<Tone, string> = {
  success: "bg-[#cdfee1] text-[#0c5132]",
  attention: "bg-[#ffd79d] text-[#5e4200]",
  critical: "bg-[#fed1cf] text-[#8e1f0b]",
  info: "bg-[#e0f0ff] text-[#00527c]",
  neutral: "bg-[#e3e3e3] text-[#303030]",
};

export function StatusBadge({ status, tone }: { status: string; tone?: Tone }) {
  const t = tone ?? statusTone(status);
  return (
    <span
      data-testid={`status-${status}`}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-lg px-2 py-0.5 text-xs font-medium",
        toneClass[t],
      )}
    >
      {humanize(status)}
    </span>
  );
}

export function KindTag({ kind }: { kind: string }) {
  return (
    <span className="rounded-md bg-[#f1f1f1] px-1.5 py-0.5 text-[11px] font-medium capitalize text-muted-foreground">
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
    <div className="rise mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-sm text-muted-foreground">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight" data-testid="text-page-title">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({ children, className, title, aside, flush }: { children: ReactNode; className?: string; title?: ReactNode; aside?: ReactNode; flush?: boolean }) {
  return (
    <section className={cn("rise card-shadow overflow-hidden rounded-xl bg-card", className)}>
      {title && (
        <header className="flex items-center justify-between gap-3 px-4 pb-2 pt-4">
          <h2 className="text-[13px] font-semibold">{title}</h2>
          {aside}
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export function ErrorState({ title = "Couldn't load this", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-[#f3b0ab] bg-[#fff4f4] p-4" data-testid="state-error">
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
