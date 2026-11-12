import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCreateAdminReseller, useOpenAdminTicket, getListAdminResellersQueryKey, getListAdminTicketsQueryKey, getGetAdminOverviewQueryKey,
  type AdminResellerDetail, type AdminTicketDetail, type TicketCreateInputTopic,
} from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { errorMessage } from "@/lib/format";

const TELEGRAM_ID = /^[1-9][0-9]{0,15}$/;
const TOPICS: [TicketCreateInputTopic, string][] = [["other", "General message"], ["payment", "Payment"], ["login", "Login or app"], ["playback", "Playback"], ["reseller", "Reseller account"]];

/** Set someone up as an active reseller, optionally with starting credits, without them buying a pack first. */
export function CreateResellerDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: (r: AdminResellerDetail) => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const create = useCreateAdminReseller();
  const [tid, setTid] = useState("");
  const [username, setUsername] = useState("");
  const [credits, setCredits] = useState("0");
  const [reason, setReason] = useState("");
  const [requestKey, setRequestKey] = useState("");
  useEffect(() => {
    if (open) { setTid(""); setUsername(""); setCredits("0"); setReason(""); setRequestKey(Math.random().toString(36).slice(2) + Date.now().toString(36)); create.reset(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const name = username.trim().replace(/^@/, "");
  const amount = parseInt(credits, 10);
  const valid = TELEGRAM_ID.test(tid.trim()) && /^[0-9]{1,6}$/.test(credits) && amount <= 100000 && reason.trim().length >= 3 && (!name || /^[A-Za-z0-9_]{1,64}$/.test(name));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    create.mutate({ data: { telegramId: Number(tid.trim()), ...(name ? { username: name } : {}), credits: amount, reason: reason.trim(), requestKey } }, {
      onSuccess: (r) => {
        toast({ title: "Reseller created", description: amount ? `Active with ${amount} credits.` : "Active with no credits yet." });
        qc.invalidateQueries({ queryKey: getListAdminResellersQueryKey() }); qc.invalidateQueries({ queryKey: getGetAdminOverviewQueryKey() });
        onCreated?.(r); onClose();
      },
    });
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Add a reseller</DialogTitle>
            <DialogDescription>Makes this Telegram user an active reseller straight away, without buying a credit pack first. The bot tells them and shows the reseller dashboard.</DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-3 text-sm">
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="new-reseller-id">Their Telegram ID</label>
              <Input id="new-reseller-id" value={tid} onChange={(e) => setTid(e.target.value.replace(/\D/g, ""))} inputMode="numeric" maxLength={16} placeholder="e.g. 4441112223" className="mt-1 h-9 font-mono" data-testid="input-new-reseller-id" />
              <p className="mt-1 text-[11px] text-muted-foreground">The number, not the @username. They can get it by sending /myid to the bot.</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="text-xs font-medium text-muted-foreground" htmlFor="new-reseller-name">Telegram username (optional)</label>
                <Input id="new-reseller-name" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={65} placeholder="@name" className="mt-1 h-9" data-testid="input-new-reseller-username" />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground" htmlFor="new-reseller-credits">Starting credits</label>
                <Input id="new-reseller-credits" value={credits} onChange={(e) => setCredits(e.target.value.replace(/\D/g, ""))} inputMode="numeric" maxLength={6} className="mt-1 h-9" data-testid="input-new-reseller-credits" />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="new-reseller-reason">Reason (kept in the audit log)</label>
              <Input id="new-reseller-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. Paid by bank transfer REF123" className="mt-1 h-9" data-testid="input-new-reseller-reason" />
            </div>
            <p className="rounded-lg bg-muted/60 p-2.5 text-xs text-muted-foreground">Starting credits are added as a manual adjustment and appear in the credit log. They are not counted as revenue.</p>
            {create.isError && <p className="text-xs text-destructive">{errorMessage(create.error)}</p>}
          </div>
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={create.isPending || !valid} data-testid="button-confirm-new-reseller">{create.isPending ? "Creating…" : "Create reseller"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Start a conversation with a customer or reseller: a new ticket, delivered to them in Telegram. */
export function NewTicketDialog({ open, onClose, telegramId, recipient, onOpened }: { open: boolean; onClose: () => void; telegramId?: string; recipient?: string; onOpened?: (t: AdminTicketDetail) => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const send = useOpenAdminTicket();
  const [tid, setTid] = useState(telegramId ?? "");
  const [topic, setTopic] = useState<TicketCreateInputTopic>("other");
  const [body, setBody] = useState("");
  useEffect(() => {
    if (open) { setTid(telegramId ?? ""); setTopic("other"); setBody(""); send.reset(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, telegramId]);
  const valid = TELEGRAM_ID.test(tid.trim()) && body.trim().length > 0;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    send.mutate({ data: { telegramId: Number(tid.trim()), topic, body: body.trim() } }, {
      onSuccess: (r) => {
        toast(r.delivered === false
          ? { title: "Ticket saved, but Telegram could not deliver it", description: "They may not have started the bot, or have blocked it. The ticket is still on record.", variant: "destructive" }
          : { title: "Ticket sent", description: `Ticket ${r.ticket.id} was delivered in Telegram.` });
        qc.invalidateQueries({ queryKey: getListAdminTicketsQueryKey() }); qc.invalidateQueries({ queryKey: getGetAdminOverviewQueryKey() });
        onOpened?.(r); onClose();
      },
    });
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New ticket{recipient ? ` to ${recipient}` : ""}</DialogTitle>
            <DialogDescription>Sends your message to a customer or reseller in Telegram and opens a ticket, so their reply comes back here.</DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-3 text-sm">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="text-xs font-medium text-muted-foreground" htmlFor="new-ticket-id">Recipient's Telegram ID</label>
                <Input id="new-ticket-id" value={tid} onChange={(e) => setTid(e.target.value.replace(/\D/g, ""))} inputMode="numeric" maxLength={16} placeholder="e.g. 6946255817" className="mt-1 h-9 font-mono" data-testid="input-new-ticket-id" />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground" htmlFor="new-ticket-topic">Topic</label>
                <select id="new-ticket-topic" value={topic} onChange={(e) => setTopic(e.target.value as TicketCreateInputTopic)} className="mt-1 h-9 w-full rounded-lg border border-input bg-card px-2 text-[13px]" data-testid="select-new-ticket-topic">
                  {TOPICS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="new-ticket-body">Message</label>
              <Textarea id="new-ticket-body" value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} rows={5} placeholder="Write your message. They can reply from the bot." className="mt-1 text-sm" data-testid="input-new-ticket-body" />
            </div>
            <p className="text-[11px] text-muted-foreground">Works for customers and resellers alike. Telegram only delivers to people who have started the bot.</p>
            {send.isError && <p className="text-xs text-destructive">{errorMessage(send.error)}</p>}
          </div>
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={send.isPending || !valid} data-testid="button-confirm-new-ticket">{send.isPending ? "Sending…" : "Send ticket"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
