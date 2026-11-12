import { useEffect, useState } from "react";
import { Link, useParams } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetAdminOrder,
  getGetAdminOrderQueryKey,
  getListAdminOrdersQueryKey,
  getGetAdminOverviewQueryKey,
  usePreviewTrialRecovery,
  useConfirmTrialRecovery,
  type AdminOrder,
  type RecoveryDraft,
  type RecoveryResult,
} from "@workspace/api-client-react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Clock, FileSearch, KeyRound, LifeBuoy, Lock, MessageSquarePlus, Plus, Trash2 } from "lucide-react";
import { AccountDetails, AddSubscriptionDialog, DeleteSubscriptionDialog } from "@/components/admin/subscriptions";
import { NewTicketDialog } from "@/components/admin/create";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, CopyId, EmptyState, ErrorState, KindTag, PageHeader, Panel, StatusBadge } from "@/components/admin/bits";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, errorStatus, formatDateTime, relativeTime, toDate } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";

function Detail() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id ?? "");
  usePageMeta(`Order ${id.slice(0, 10)}`, "Order status explanation and trial recovery for a single UKCTV order.");
  const ready = useAdminReady();
  const q = useGetAdminOrder(id, { query: { enabled: ready && !!id, queryKey: getGetAdminOrderQueryKey(id), ...LIVE } });
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<RecoveryResult | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [messaging, setMessaging] = useState(false);

  const back = (
    <Link href="/orders" className="inline-flex items-center gap-1 hover:text-foreground" data-testid="link-back">
      <ArrowLeft className="h-3.5 w-3.5" /> Orders
    </Link>
  );

  if (q.isError) {
    const notFound = errorStatus(q.error) === 404;
    return (
      <>
        <PageHeader title={notFound ? "Order not found" : "Order"} eyebrow={back} />
        {notFound ? (
          <Panel><EmptyState icon={<FileSearch className="h-5 w-5" />} title="No order with this ID">Check the ID. It may have been copied with extra characters: <span className="font-mono">{id}</span></EmptyState></Panel>
        ) : (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        )}
      </>
    );
  }

  const d = q.data;
  return (
    <>
      <PageHeader
        eyebrow={back}
        title={d ? `Order ${d.order.id.length > 16 ? d.order.id.slice(0, 8) + "…" : d.order.id}` : "Loading order"}
        description={d ? <span className="inline-flex flex-wrap items-center gap-2"><StatusBadge status={d.order.status} /><KindTag kind={d.order.kind} /><span>{formatDateTime(d.order.createdAt)}</span></span> : undefined}
        actions={d ? (
          <>
            {/^[1-9][0-9]*$/.test(d.order.customer) && <Button variant="outline" onClick={() => setMessaging(true)} data-testid="button-message-customer"><MessageSquarePlus className="mr-1.5 h-4 w-4" /> New ticket</Button>}
            {/^[1-9][0-9]*$/.test(d.order.customer) && <Button variant="outline" onClick={() => setAdding(true)} data-testid="button-add-for-customer"><Plus className="mr-1.5 h-4 w-4" /> Add subscription</Button>}
            {d.canDelete && <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => setDeleting(true)} data-testid="button-delete-order-subscription"><Trash2 className="mr-1.5 h-4 w-4" /> Delete</Button>}
            {d.recoveryEligible && <Button onClick={() => setOpen(true)} data-testid="button-start-recovery"><LifeBuoy className="mr-1.5 h-4 w-4" /> Recover trial</Button>}
          </>
        ) : undefined}
      />

      {result && (
        <div className="rise mb-5 flex gap-3 rounded-xl border border-[#b3d2f5] bg-[#eaf4ff] p-4 text-sm" data-testid="status-recovery-result">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-[#00527c]" />
          <div>
            <p className="font-semibold text-[#00527c]">{result.queued ? "Order re-queued for processing" : "Recovery not queued"}</p>
            <p className="mt-0.5 text-[#303030]">{result.message}</p>
            {result.queued && <p className="mt-1 text-xs text-muted-foreground">This does not mean the trial was delivered. Watch this order's status; it updates every 30 seconds.</p>}
          </div>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <Panel title="What's happening">
            {q.isLoading || !d ? (
              <div className="space-y-2"><Bar className="h-3.5 w-full" /><Bar className="h-3.5 w-4/5" /></div>
            ) : (
              <p className="text-[15px] leading-relaxed" data-testid="text-order-message">{d.message || "No explanation available for this status."}</p>
            )}
          </Panel>
          <Panel title="Account details" aside={d && d.removedAt > 0 ? <span className="text-xs text-muted-foreground">Deleted {formatDateTime(d.removedAt)}</span> : undefined}>
            {q.isLoading || !d ? (
              <div className="space-y-2"><Bar className="h-4 w-full" /><Bar className="h-4 w-2/3" /></div>
            ) : d.account ? (
              <AccountDetails username={d.account.username} password={d.account.password} serverUrl={d.account.serverUrl} expiresAt={d.account.expiresAt} />
            ) : (
              <div className="flex gap-3 text-sm">
                <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div>
                  <p className="font-medium">No login yet</p>
                  <p className="text-muted-foreground">{d.order.status === "fulfilled" ? "This order did not create an account of its own (credit packs and renewals extend an existing one)." : "The username and password appear here once the account has been created."}</p>
                </div>
              </div>
            )}
          </Panel>
          <Panel title="Trial recovery">
            {q.isLoading || !d ? (
              <Bar className="h-10 w-full" />
            ) : d.recoveryEligible ? (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex gap-3 text-sm">
                  <LifeBuoy className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <p className="font-medium">Eligible for recovery</p>
                    <p className="text-muted-foreground" data-testid="text-recovery-reason">{d.recoveryReason}</p>
                  </div>
                </div>
                <Button variant="outline" onClick={() => setOpen(true)} data-testid="button-start-recovery-inline">Review recovery</Button>
              </div>
            ) : (
              <div className="flex gap-3 text-sm">
                <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div>
                  <p className="font-medium">Not available for this order</p>
                  <p className="text-muted-foreground" data-testid="text-recovery-reason">{d.recoveryReason || "Recovery only applies to trials stuck before account creation."}</p>
                </div>
              </div>
            )}
          </Panel>
        </div>
        <Panel title="Details" flush>
          {d ? <Facts o={d.order} /> : <div className="space-y-3 p-4">{Array.from({ length: 6 }).map((_, i) => <Bar key={i} className="h-4" />)}</div>}
        </Panel>
      </div>

      {d && (
        <>
          <DeleteSubscriptionDialog
            target={deleting && d.account ? { source: "retail", id: d.order.id, kind: d.order.kind, label: d.account.username } : null}
            onClose={() => setDeleting(false)}
          />
          <AddSubscriptionDialog open={adding} onClose={() => setAdding(false)} telegramId={/^[1-9][0-9]*$/.test(d.order.customer) ? d.order.customer : undefined} />
          <NewTicketDialog open={messaging} onClose={() => setMessaging(false)} telegramId={/^[1-9][0-9]*$/.test(d.order.customer) ? d.order.customer : undefined} recipient={d.order.username ? "@" + d.order.username : undefined} />
        </>
      )}
      {d && (
        <RecoveryDialog
          open={open}
          onOpenChange={setOpen}
          orderId={d.order.id}
          onDone={(r) => setResult(r)}
        />
      )}
    </>
  );
}

const EXPLORERS: Record<string, string> = {
  ethereum: "https://etherscan.io/tx/",
  solana: "https://solscan.io/tx/",
  bitcoin: "https://mempool.space/tx/",
};

/** The payment's transaction ID: copyable, with a link to the public block explorer for its network. */
function Txid({ o }: { o: AdminOrder }) {
  const explorer = EXPLORERS[o.network];
  const verified = ["paid", "provisioning", "fulfilled"].includes(o.status);
  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <CopyId value={o.txid} label="TXID" short />
      <span className="text-xs text-muted-foreground">
        {verified ? "Verified on-chain" : "Submitted, not verified yet"}
        {explorer && /^[A-Za-z0-9]+$/.test(o.txid) && <> · <a href={explorer + o.txid} target="_blank" rel="noopener noreferrer" className="font-medium text-primary hover:underline" data-testid="link-txid-explorer">View on explorer</a></>}
      </span>
    </span>
  );
}

function Facts({ o }: { o: AdminOrder }) {
  const rows: [string, React.ReactNode][] = [
    ["Order ID", <CopyId value={o.id} label="Order ID" />],
    ["Customer", o.customer ? <CopyId value={o.customer} label="Customer" /> : "—"],
    ["Telegram username", o.username ? <CopyId value={"@" + o.username} label="Username" /> : <span className="text-muted-foreground">{/^[1-9][0-9]*$/.test(o.customer) ? "No username set" : "—"}</span>],
    ["Plan", o.plan || "—"],
    ["Kind", <KindTag kind={o.kind} />],
    ["Amount", <span className="font-mono">{o.amount} <span className="font-sans font-medium">{o.symbol}</span></span>],
    ["Network", o.network || "—"],
    ["TXID", o.txid ? <Txid o={o} /> : <span className="text-muted-foreground">{o.network && o.network !== "none" ? "None submitted" : "No payment"}</span>],
    ["Created", <span><span className="num">{formatDateTime(o.createdAt)}</span><span className="block text-xs text-muted-foreground">{relativeTime(o.createdAt)}</span></span>],
  ];
  return (
    <dl className="divide-y divide-border text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-4 px-4 py-2.5">
          <dt className="shrink-0 text-muted-foreground">{k}</dt>
          <dd className="min-w-0 text-right" data-testid={`text-detail-${k.toLowerCase().replace(/\s/g, "-")}`}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function useCountdown(expiresAt?: number) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  if (!expiresAt) return { left: 0, label: "" };
  const left = Math.max(0, Math.floor((toDate(expiresAt).getTime() - now) / 1000));
  return { left, label: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` };
}

function RecoveryDialog({ open, onOpenChange, orderId, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; orderId: string; onDone: (r: RecoveryResult) => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const preview = usePreviewTrialRecovery();
  const confirm = useConfirmTrialRecovery();
  const [draft, setDraft] = useState<RecoveryDraft | null>(null);
  const [attest, setAttest] = useState(false);
  const { left, label } = useCountdown(draft?.expiresAt);
  const expired = !!draft && left === 0;
  const previewMutate = preview.mutate;

  useEffect(() => {
    if (open) {
      setDraft(null);
      setAttest(false);
      previewMutate({ id: orderId, data: {} }, { onSuccess: (r) => setDraft(r) });
    }
  }, [open, orderId, previewMutate]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: getGetAdminOrderQueryKey(orderId) });
    qc.invalidateQueries({ queryKey: getListAdminOrdersQueryKey() });
    qc.invalidateQueries({ queryKey: getGetAdminOverviewQueryKey() });
  };

  const cancel = () => {
    if (draft && !expired && !confirm.isPending) {
      confirm.mutate({ data: { nonce: draft.nonce, attestation: false, cancel: true } }, { onSettled: refresh });
    }
    onOpenChange(false);
  };

  const submit = () => {
    if (!draft || !attest) return;
    confirm.mutate(
      { data: { nonce: draft.nonce, attestation: true, cancel: false } },
      {
        onSuccess: (r) => {
          onDone(r);
          toast({ title: r.queued ? "Order re-queued" : "Not queued", description: r.message });
          onOpenChange(false);
        },
        onSettled: refresh,
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(o) : cancel())}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Recover stuck trial</DialogTitle>
          <DialogDescription>Re-queues this same order, <span className="font-mono">{orderId}</span>, for processing. No new order is created.</DialogDescription>
        </DialogHeader>

        {preview.isPending && <div className="space-y-2 py-2"><Bar className="h-16 w-full" /><Bar className="h-4 w-2/3" /></div>}
        {preview.isError && <ErrorState title="Couldn't prepare recovery" message={errorMessage(preview.error)} onRetry={() => previewMutate({ id: orderId, data: {} }, { onSuccess: (r) => setDraft(r) })} />}

        {draft && (
          <div className="space-y-4">
            <div className="rounded-lg border border-[#e8b86b] bg-[#fff5e4] p-3 text-sm text-[#5e4200]" data-testid="text-recovery-warning">
              <div className="mb-1 flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" /> Check before you continue</div>
              <p>Verify in the server logs that account creation <b>never started</b> for this order. Empty (NULL) credentials on the order are <b>not proof on their own</b>: a creation that started and failed midway can leave them empty too, and re-queuing would create a duplicate account.</p>
              {draft.warning && <p className="mt-2 border-t border-[#e8b86b] pt-2">{draft.warning}</p>}
            </div>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 text-sm transition-colors hover:bg-muted/40">
              <Checkbox checked={attest} onCheckedChange={(v) => setAttest(v === true)} disabled={expired} className="mt-0.5" data-testid="checkbox-attestation" />
              <span>I checked the logs and confirmed account creation never started for this order.</span>
            </label>
            <div className={`flex items-center gap-2 text-xs ${expired ? "text-destructive" : "text-muted-foreground"}`} data-testid="text-recovery-ttl">
              <Clock className="h-3.5 w-3.5" />
              {expired ? "This confirmation expired. Close and start again." : <>Confirmation expires in <span className="num font-mono font-medium text-foreground">{label}</span> ({formatDateTime(draft.expiresAt)})</>}
            </div>
            {confirm.isError && <ErrorState title="Recovery failed" message={errorMessage(confirm.error)} />}
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={cancel} data-testid="button-cancel-recovery">Cancel</Button>
          <Button onClick={submit} disabled={!draft || !attest || expired || confirm.isPending} data-testid="button-confirm-recovery">
            {confirm.isPending ? "Queuing…" : <><CheckCircle2 className="mr-1.5 h-4 w-4" /> Re-queue this order</>}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function OrderDetailPage() {
  return <AdminShell><Detail /></AdminShell>;
}
