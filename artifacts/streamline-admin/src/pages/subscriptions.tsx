import { useState } from "react";
import { Link } from "wouter";
import type { AdminSubscription } from "@workspace/api-client-react";
import { Plus, Trash2 } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { Bar, CopyId, KindTag, PageHeader, SellerBadge, StatusBadge } from "@/components/admin/bits";
import { AccountGroups } from "@/components/admin/account-groups";
import { AccountDetails, AddSubscriptionDialog, DeleteSubscriptionDialog } from "@/components/admin/subscriptions";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { formatDate, formatDateTime, relativeTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";


/** Who the account belongs to: a Telegram customer for direct sales, the reseller's own note for resold accounts. */
function customerName(s: AdminSubscription) {
  if (s.source === "retail") return s.telegramUsername ? "@" + s.telegramUsername : s.telegramId ? "No username set" : "Website checkout";
  return s.customerRef || "No customer note";
}
function resellerName(s: AdminSubscription) {
  return s.resellerUsername ? "@" + s.resellerUsername : String(s.resellerTelegramId);
}
function statusTone(s: AdminSubscription) {
  return s.status === "active" ? "success" as const : s.status === "disabled" ? "critical" as const : "neutral" as const;
}

/**
 * Accounts as a table from tablet width up and as cards on phones. `showSeller` adds a Direct /
 * Reseller badge to every row, for lists that mix both; `compact` drops the password column.
 */
export function SubscriptionsTable({ items, loading, onOpen, compact, showSeller }: {
  items?: AdminSubscription[]; loading?: boolean; onOpen: (s: AdminSubscription) => void; compact?: boolean; showSeller?: boolean;
}) {
  const columns = 5 + (compact ? 0 : 1) + (showSeller ? 1 : 0);
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className={cn("w-full text-sm", compact ? "min-w-[560px]" : "min-w-[720px]")}>
          <thead>
            <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
              <th className="px-4 py-2.5 font-medium">Customer</th>
              {showSeller && <th className="px-3 py-2.5 font-medium">Sold by</th>}
              <th className="px-3 py-2.5 font-medium">Type</th>
              <th className="px-3 py-2.5 font-medium">Account username</th>
              {!compact && <th className="px-3 py-2.5 font-medium">Password</th>}
              <th className="px-3 py-2.5 font-medium">Expires</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && Array.from({ length: 4 }).map((_, i) => (
              <tr key={i} className="border-b border-border last:border-0">{Array.from({ length: columns }).map((_, j) => <td key={j} className="px-3 py-3.5 first:px-4"><Bar className="h-3.5" /></td>)}</tr>
            ))}
            {!loading && items?.map((s) => (
              <tr key={s.source + s.id} onClick={() => onOpen(s)} data-testid={`row-subscription-${s.id}`} className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5">
                <td className="max-w-[240px] px-4 py-3">
                  <div className="truncate font-medium">{customerName(s)}</div>
                  {s.source === "retail" && !!s.telegramId && <div className="font-mono text-[11px] text-muted-foreground">{s.telegramId}</div>}
                </td>
                {showSeller && <td className="max-w-[200px] px-3 py-3"><SellerBadge source={s.source} name={s.source === "reseller" ? resellerName(s) : undefined} /></td>}
                <td className="px-3 py-3"><KindTag kind={s.kind === "trial" ? "trial" : "subscription"} /><div className="mt-0.5 text-[11px] text-muted-foreground">{s.connections} device{s.connections > 1 ? "s" : ""}</div></td>
                <td className="px-3 py-3">{s.accountUsername ? <CopyId value={s.accountUsername} label="Username" /> : "—"}</td>
                {!compact && <td className="px-3 py-3">{s.accountPassword ? <CopyId value={s.accountPassword} label="Password" /> : "—"}</td>}
                <td className="px-3 py-3 whitespace-nowrap"><div className="num">{formatDate(s.expiresAt)}</div><div className="text-xs text-muted-foreground">{relativeTime(s.expiresAt)}</div></td>
                <td className="px-3 py-3"><StatusBadge status={s.status} tone={statusTone(s)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-border md:hidden">
        {loading && Array.from({ length: 3 }).map((_, i) => <li key={i} className="space-y-2 p-4"><Bar className="h-4 w-1/2" /><Bar className="h-3.5 w-3/4" /></li>)}
        {!loading && items?.map((s) => (
          <li key={s.source + s.id}>
            <div role="button" tabIndex={0} onClick={() => onOpen(s)} onKeyDown={(e) => { if (e.key === "Enter") onOpen(s); }} data-testid={`row-subscription-${s.id}`}
              className="cursor-pointer space-y-2.5 p-4 transition-colors active:bg-[#f1f1f1] dark:active:bg-white/10">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-[15px] font-semibold">{customerName(s)}</div>
                  {s.source === "retail" && !!s.telegramId && <div className="font-mono text-xs text-muted-foreground">{s.telegramId}</div>}
                </div>
                <StatusBadge status={s.status} tone={statusTone(s)} />
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                {showSeller && <SellerBadge source={s.source} name={s.source === "reseller" ? resellerName(s) : undefined} />}
                <KindTag kind={s.kind === "trial" ? "trial" : "subscription"} />
                <span>{s.connections} device{s.connections > 1 ? "s" : ""}</span>
              </div>
              <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Username</dt><dd className="min-w-0 justify-self-end">{s.accountUsername ? <CopyId value={s.accountUsername} label="Username" /> : "—"}</dd>
                <dt className="text-muted-foreground">Password</dt><dd className="min-w-0 justify-self-end">{s.accountPassword ? <CopyId value={s.accountPassword} label="Password" /> : "—"}</dd>
                <dt className="text-muted-foreground">Expires</dt><dd className="num justify-self-end">{formatDate(s.expiresAt)} <span className="text-xs text-muted-foreground">· {relativeTime(s.expiresAt)}</span></dd>
              </dl>
            </div>
          </li>
        ))}
      </ul>
    </>
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
              <StatusBadge status={s.status} tone={statusTone(s)} />
              <SellerBadge source={s.source} name={s.source === "reseller" ? resellerName(s) : undefined} />
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
        description="Paid subscriptions, split into your own customers and each reseller's. Tap an account for its login details."
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
        description={<>24-hour trials, split into your own customers and each reseller's. Trials that got stuck before a login was created are under <Link href="/orders?kind=trial" className="font-medium text-primary hover:underline" data-testid="link-trial-orders">trial orders</Link>.</>}
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
