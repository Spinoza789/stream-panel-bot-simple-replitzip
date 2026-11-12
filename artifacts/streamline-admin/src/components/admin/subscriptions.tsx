import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useAddAdminSubscription, useDeleteAdminSubscription, useGetAdminRateCard, getGetAdminRateCardQueryKey,
  getListAdminSubscriptionsQueryKey, getListAdminOrdersQueryKey, getGetAdminOverviewQueryKey, getGetAdminOrderQueryKey,
  type SubscriptionAddResult,
} from "@workspace/api-client-react";
import { AlertTriangle, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, formatDateTime, gbp, relativeTime } from "@/lib/format";
import { CopyId } from "./bits";
import { useAdminReady } from "./access";

export const UNLIMITED = -1;

/** "Unlimited", "None" or the number, for a trial allowance. */
export function limitLabel(value: number): string {
  return value === UNLIMITED ? "Unlimited" : value === 0 ? "None" : String(value);
}

/**
 * One trial allowance: unlimited, or a whole number. With `fallback` set it can also follow the
 * default for all resellers (value null).
 */
export function LimitField({ label, hint, value, onChange, fallback, testId }: {
  label: string; hint?: string; value: number | null; onChange: (v: number | null) => void; fallback?: number; testId: string;
}) {
  const mode = value === null ? "default" : value === UNLIMITED ? "unlimited" : "number";
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      <div className="mt-1 flex items-center gap-1.5">
        <select
          value={mode}
          onChange={(e) => onChange(e.target.value === "default" ? null : e.target.value === "unlimited" ? UNLIMITED : Math.max(0, value ?? fallback ?? 1))}
          className="h-8 rounded-lg border border-input bg-card px-2 text-[13px]"
          data-testid={`select-${testId}`}
        >
          {fallback !== undefined && <option value="default">Default ({limitLabel(fallback)})</option>}
          <option value="unlimited">Unlimited</option>
          <option value="number">Limit to</option>
        </select>
        {mode === "number" && (
          <Input
            value={String(value)}
            onChange={(e) => { const n = parseInt(e.target.value.replace(/\D/g, ""), 10); onChange(Number.isFinite(n) ? Math.min(n, 100000) : 0); }}
            inputMode="numeric" className="h-8 w-20" data-testid={`input-${testId}`}
          />
        )}
      </div>
      {hint && <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Login details of a delivered account, each value copyable. */
export function AccountDetails({ username, password, serverUrl, expiresAt }: { username: string; password: string; serverUrl?: string; expiresAt?: number }) {
  const rows: [string, React.ReactNode][] = [
    ["Username", username ? <CopyId value={username} label="Username" /> : "—"],
    ["Password", password ? <CopyId value={password} label="Password" /> : "—"],
  ];
  if (serverUrl) rows.push(["Server", <CopyId value={serverUrl} label="Server" />]);
  if (expiresAt) rows.push(["Expires", <span><span className="num">{formatDateTime(expiresAt)}</span><span className="block text-xs text-muted-foreground">{relativeTime(expiresAt)}</span></span>]);
  return (
    <dl className="divide-y divide-border text-sm" data-testid="account-details">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-4 py-2">
          <dt className="shrink-0 text-muted-foreground">{k}</dt>
          <dd className="min-w-0 text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function useRefreshSubscriptions() {
  const qc = useQueryClient();
  return (orderId?: string) => {
    qc.invalidateQueries({ queryKey: getListAdminSubscriptionsQueryKey() });
    qc.invalidateQueries({ queryKey: getListAdminOrdersQueryKey() });
    qc.invalidateQueries({ queryKey: getGetAdminOverviewQueryKey() });
    if (orderId) qc.invalidateQueries({ queryKey: getGetAdminOrderQueryKey(orderId) });
  };
}

/** Confirmation before a subscription or trial is deleted. A reason is required and goes into the audit log. */
export function DeleteSubscriptionDialog({ target, onClose, onDeleted }: {
  target: { source: "retail" | "reseller"; id: string; kind: string; label: string } | null; onClose: () => void; onDeleted?: () => void;
}) {
  const { toast } = useToast();
  const refresh = useRefreshSubscriptions();
  const del = useDeleteAdminSubscription();
  const [reason, setReason] = useState("");
  useEffect(() => { if (target) { setReason(""); del.reset(); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [target?.id]);
  if (!target) return null;
  const what = target.kind === "trial" ? "trial" : "subscription";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (reason.trim().length < 3) return;
    del.mutate({ source: target.source, id: target.id, data: { confirm: true, reason: reason.trim() } }, {
      onSuccess: () => { toast({ title: `${what[0].toUpperCase()}${what.slice(1)} deleted`, description: target.label }); refresh(target.source === "retail" ? target.id : undefined); onDeleted?.(); onClose(); },
    });
  };
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Delete this {what}?</DialogTitle>
            <DialogDescription>Account <span className="font-mono text-foreground">{target.label}</span></DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-3 text-sm">
            <div className="rounded-lg border border-[#e8b86b] bg-[#fff5e4] p-3 text-[#5e4200]" data-testid="text-delete-warning">
              <div className="mb-1 flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" /> Please confirm</div>
              <ul className="list-disc space-y-1 pl-5">
                <li>It disappears from this list{target.source === "reseller" ? " and from the reseller's own list" : target.kind === "trial" ? "" : " and from the customer's bot"}.</li>
                <li>The line on the IPTV panel is <b>not</b> cancelled. Disable it on the panel if access should stop.</li>
                {target.source === "reseller"
                  ? <li>No credits are refunded. Use Adjust credits on the reseller if you want to give some back.</li>
                  : target.kind === "trial"
                    ? <li>The customer still counts as having used their one free trial.</li>
                    : <li>The order stays in Orders and in your reports.</li>}
              </ul>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="delete-reason">Reason (kept in the audit log)</label>
              <Input id="delete-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. Customer cancelled" className="mt-1 h-9" autoFocus data-testid="input-delete-reason" />
            </div>
            {del.isError && <p className="text-xs text-destructive">{errorMessage(del.error)}</p>}
          </div>
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={onClose} data-testid="button-cancel-delete">Keep it</Button>
            <Button type="submit" variant="destructive" disabled={del.isPending || reason.trim().length < 3} data-testid="button-confirm-delete">
              {del.isPending ? "Deleting…" : <><Trash2 className="mr-1.5 h-4 w-4" /> Delete {what}</>}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Give a Telegram user a membership without payment. The account is created by the normal worker and the bot sends the login. */
export function AddSubscriptionDialog({ open, onClose, telegramId, onAdded }: { open: boolean; onClose: () => void; telegramId?: string; onAdded?: (r: SubscriptionAddResult) => void }) {
  const ready = useAdminReady();
  const { toast } = useToast();
  const refresh = useRefreshSubscriptions();
  const card = useGetAdminRateCard({ query: { enabled: ready && open, queryKey: getGetAdminRateCardQueryKey() } });
  const add = useAddAdminSubscription();
  const [tid, setTid] = useState(telegramId ?? "");
  const [plan, setPlan] = useState("");
  const [reason, setReason] = useState("");
  useEffect(() => { if (open) { setTid(telegramId ?? ""); setPlan(""); setReason(""); add.reset(); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [open, telegramId]);
  const plans = card.data?.plans ?? [];
  const chosen = plans.find((p) => p.id === plan);
  const trial = plan === "trial";
  const valid = /^[1-9][0-9]{0,15}$/.test(tid.trim()) && (trial || !!chosen) && reason.trim().length >= 3;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    add.mutate({ data: { telegramId: Number(tid.trim()), planId: plan, reason: reason.trim() } }, {
      onSuccess: (r) => { toast({ title: trial ? "Trial added" : "Subscription added", description: r.message }); refresh(); onAdded?.(r); onClose(); },
    });
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Add a trial or subscription</DialogTitle>
            <DialogDescription>Creates a new account for this Telegram user without payment. The bot sends them the login when it is ready.</DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-3 text-sm">
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="add-tid">Customer's Telegram ID</label>
              <Input id="add-tid" value={tid} onChange={(e) => setTid(e.target.value.replace(/\D/g, ""))} inputMode="numeric" maxLength={16} placeholder="e.g. 6946255817" className="mt-1 h-9 font-mono" data-testid="input-add-telegram-id" />
              <p className="mt-1 text-[11px] text-muted-foreground">The number, not the @username. They must have started the bot to receive the login.</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="add-plan">Plan</label>
              <select id="add-plan" value={plan} onChange={(e) => setPlan(e.target.value)} className="mt-1 h-9 w-full rounded-lg border border-input bg-card px-2 text-[13px]" data-testid="select-add-plan">
                <option value="">{card.isLoading ? "Loading plans…" : "Choose a trial or plan"}</option>
                <option value="trial">24-hour free trial · 1 device</option>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.connections} device{p.connections > 1 ? "s" : ""} (normally {gbp(parseFloat(p.gbpPrice) || 0)})</option>)}
              </select>
              {card.isError && <p className="mt-1 text-xs text-destructive">{errorMessage(card.error)}</p>}
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="add-reason">Reason (kept in the audit log)</label>
              <Input id="add-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. Paid by bank transfer" className="mt-1 h-9" data-testid="input-add-reason" />
            </div>
            <p className="rounded-lg bg-muted/60 p-2.5 text-xs text-muted-foreground">{trial
              ? "This creates a real trial line on the IPTV panel. Each Telegram user gets one free trial ever, so this uses theirs."
              : "This creates a real line on the IPTV panel and uses panel credit. It is not counted as revenue."}</p>
            {add.isError && <p className="text-xs text-destructive">{errorMessage(add.error)}</p>}
          </div>
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={add.isPending || !valid} data-testid="button-confirm-add">{add.isPending ? "Adding…" : trial ? "Add trial" : "Add subscription"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
