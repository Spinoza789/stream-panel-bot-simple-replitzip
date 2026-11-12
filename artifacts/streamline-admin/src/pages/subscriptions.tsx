import { useState } from "react";
import { Link } from "wouter";
import type { AdminSubscription } from "@workspace/api-client-react";
import { Plus, Trash2 } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { Bar, CopyId, KindTag, PageHeader, StatusBadge } from "@/components/admin/bits";
import { AccountGroups } from "@/components/admin/account-groups";
import { AccountDetails, AddSubscriptionDialog, DeleteSubscriptionDialog } from "@/components/admin/subscriptions";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { formatDate, formatDateTime, relativeTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";


/** Who the account belongs to: a Telegram customer for direct sales, the reseller's own note for resold accounts. */
function Customer({ s }: { s: AdminSubscription }) {
  if (s.source === "retail") {
    return (
      <div>
        <div className="font-medium">{s.telegramUsername ? "@" + s.telegramUsername : s.telegramId ? "No username set" : "Website checkout"}</div>
        {!!s.telegramId && <div className="font-mono text-[11px] text-muted-foreground">{s.telegramId}</div>}
      </div>
    );
  }
  return (
    <div>
      <div className="font-medium">{s.customerRef || "No customer note"}</div>
      <div className="text-[11px] text-muted-foreground">via {s.resellerUsername ? "@" + s.resellerUsername : "reseller " + s.resellerTelegramId}</div>
    </div>
  );
}

/** `compact` drops the password column for narrow places; the row still opens the full details. */
export function SubscriptionsTable({ items, loading, onOpen, compact }: { items?: AdminSubscription[]; loading?: boolean; onOpen: (s: AdminSubscription) => void; compact?: boolean }) {
  const columns = compact ? 5 : 6;
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full text-sm", compact ? "min-w-[600px]" : "min-w-[780px]")}>
        <thead>
          <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
            <th className="px-4 py-2 font-medium">Customer</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Account username</th>
            {!compact && <th className="px-3 py-2 font-medium">Password</th>}
            <th className="px-3 py-2 font-medium">Expires</th>
            <th className="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {loading && Array.from({ length: 6 }).map((_, i) => (
            <tr key={i} className="border-b border-border last:border-0">{Array.from({ length: columns }).map((_, j) => <td key={j} className="px-3 py-3 first:px-4"><Bar className="h-3.5" /></td>)}</tr>
          ))}
          {!loading && items?.map((s) => (
            <tr key={s.source + s.id} onClick={() => onOpen(s)} data-testid={`row-subscription-${s.id}`} className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5">
              <td className="max-w-[220px] truncate px-4 py-2.5"><Customer s={s} /></td>
              <td className="px-3 py-2.5"><KindTag kind={s.kind === "trial" ? "trial" : "subscription"} /><div className="mt-0.5 text-[11px] text-muted-foreground">{s.connections} device{s.connections > 1 ? "s" : ""}</div></td>
              <td className="px-3 py-2.5">{s.accountUsername ? <CopyId value={s.accountUsername} label="Username" /> : "—"}</td>
              {!compact && <td className="px-3 py-2.5">{s.accountPassword ? <CopyId value={s.accountPassword} label="Password" /> : "—"}</td>}
              <td className="px-3 py-2.5 whitespace-nowrap"><div className="num">{formatDate(s.expiresAt)}</div><div className="text-xs text-muted-foreground">{relativeTime(s.expiresAt)}</div></td>
              <td className="px-3 py-2.5"><StatusBadge status={s.status} tone={s.status === "active" ? "success" : s.status === "disabled" ? "critical" : "neutral"} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Everything about one account, with the delete button. */
export function SubscriptionDialog({ s, onClose }: { s: AdminSubscription; onClose: () => void }) {
  const [deleting, setDeleting] = useState(false);
  return (
    <>
      <Dialog open={!deleting} onOpenChange={(o) => { if (!o) onClose(); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{s.kind === "trial" ? "Trial" : "Subscription"} · {s.accountUsername || "account"}</DialogTitle>
            <DialogDescription className="flex flex-wrap items-center gap-2">
              <StatusBadge status={s.status} tone={s.status === "active" ? "success" : s.status === "disabled" ? "critical" : "neutral"} />
              <span>{s.plan} · {s.connections} device{s.connections > 1 ? "s" : ""}</span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Account details</h3>
              <AccountDetails username={s.accountUsername} password={s.accountPassword} serverUrl={s.serverUrl} expiresAt={s.expiresAt} />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{s.source === "retail" ? "Customer" : "Sold by"}</h3>
              <dl className="divide-y divide-border">
                {s.source === "retail" ? (
                  <>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Telegram username</dt><dd>{s.telegramUsername ? <CopyId value={"@" + s.telegramUsername} label="Username" /> : <span className="text-muted-foreground">No username set</span>}</dd></div>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Telegram ID</dt><dd>{s.telegramId ? <CopyId value={String(s.telegramId)} label="Telegram ID" /> : "Website checkout"}</dd></div>
                  </>
                ) : (
                  <>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Reseller</dt><dd>{s.resellerUsername ? "@" + s.resellerUsername : "—"} <span className="font-mono text-xs text-muted-foreground">{s.resellerTelegramId}</span></dd></div>
                    <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Their customer note</dt><dd className="text-right">{s.customerRef || "—"}</dd></div>
                  </>
                )}
                <div className="flex justify-between gap-4 py-2"><dt className="text-muted-foreground">Created</dt><dd className="num">{formatDateTime(s.createdAt)}</dd></div>
              </dl>
            </div>
          </div>
          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setDeleting(true)} data-testid="button-delete-subscription"><Trash2 className="mr-1.5 h-4 w-4" /> Delete</Button>
            <div className="flex gap-2">
              {s.source === "retail" && <Button variant="outline" asChild><Link href={`/orders/${s.id}`}>Open order</Link></Button>}
              <Button variant="outline" onClick={onClose}>Close</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <DeleteSubscriptionDialog
        target={deleting ? { source: s.source, id: s.id, kind: s.kind, label: s.accountUsername || s.id } : null}
        onClose={() => setDeleting(false)} onDeleted={onClose}
      />
    </>
  );
}

function SubscriptionsList() {
  usePageMeta("Subscriptions", "Every paid subscription, your own and each reseller's, with login details.");
  const [adding, setAdding] = useState(false);
  return (
    <>
      <PageHeader
        title="Subscriptions"
        description="Paid subscriptions that are running: your direct customers first, then a section for each reseller. Expired ones are at the bottom. Click a row for the login details."
        actions={<Button onClick={() => setAdding(true)} data-testid="button-add-subscription"><Plus className="mr-1.5 h-4 w-4" /> Add trial or subscription</Button>}
      />
      <AccountGroups kind="paid" />
      <AddSubscriptionDialog open={adding} onClose={() => setAdding(false)} />
    </>
  );
}

function TrialsList() {
  usePageMeta("Trials", "Every 24-hour trial, your own and each reseller's, with login details.");
  const [adding, setAdding] = useState(false);
  return (
    <>
      <PageHeader
        title="Trials"
        description={<>24-hour trials that are running: your direct customers first, then a section for each reseller. Expired ones are at the bottom. Trials that got stuck before a login was created are under <Link href="/orders?kind=trial" className="font-medium text-primary hover:underline" data-testid="link-trial-orders">trial orders</Link>.</>}
        actions={<Button onClick={() => setAdding(true)} data-testid="button-add-trial"><Plus className="mr-1.5 h-4 w-4" /> Add trial or subscription</Button>}
      />
      <AccountGroups kind="trial" />
      <AddSubscriptionDialog open={adding} onClose={() => setAdding(false)} />
    </>
  );
}

export function TrialsPage() {
  return <AdminShell><TrialsList /></AdminShell>;
}

export default function SubscriptionsPage() {
  return <AdminShell><SubscriptionsList /></AdminShell>;
}
