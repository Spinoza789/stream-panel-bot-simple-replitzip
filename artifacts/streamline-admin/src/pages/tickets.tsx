import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useListAdminTickets, getListAdminTicketsQueryKey, useGetAdminTicket, getGetAdminTicketQueryKey,
  useReplyAdminTicket, useSetAdminTicketStatus, getGetAdminOverviewQueryKey,
  type ListAdminTicketsParams, type AdminTicket,
} from "@workspace/api-client-react";
import { ChevronLeft, ChevronRight, LifeBuoy, Search, X } from "lucide-react";
import { AdminShell } from "@/components/admin/shell";
import { LIVE, useAdminReady } from "@/components/admin/access";
import { Bar, CopyId, EmptyState, ErrorState, PageHeader, Panel, StatusBadge } from "@/components/admin/bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { errorMessage, formatDateTime, relativeTime } from "@/lib/format";
import { usePageMeta } from "@/lib/meta";
import { cn } from "@/lib/utils";

type Status = NonNullable<ListAdminTicketsParams["status"]>;
const TABS: { key: Status; label: string }[] = [
  { key: "open", label: "Needs reply" },
  { key: "answered", label: "Answered" },
  { key: "closed", label: "Closed" },
  { key: "all", label: "All" },
];

function tone(status: AdminTicket["status"]) {
  return status === "open" ? "attention" : status === "answered" ? "success" : "neutral";
}
function who(t: AdminTicket) {
  return t.username ? "@" + t.username : "ID " + t.telegramId;
}

function TicketsList() {
  usePageMeta("Tickets", "Support tickets from the bot and the reseller panel. Answers are stored on the ticket and sent to the customer in Telegram.");
  const ready = useAdminReady();
  const qc = useQueryClient();
  const [status, setStatus] = useState<Status>("open");
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setQ(text.trim().slice(0, 80)); setPage(1); }, 300);
    return () => clearTimeout(timer.current);
  }, [text]);
  const params: ListAdminTicketsParams = { status, page };
  if (q) params.q = q;
  const list = useListAdminTickets(params, { query: { enabled: ready, queryKey: getListAdminTicketsQueryKey(params), placeholderData: (p) => p, ...LIVE } });
  const d = list.data;
  const counts = d?.counts;
  return (
    <>
      <PageHeader title="Tickets" description="Customers and resellers open tickets from the bot's Contact support button or the panel's Support page. Reply here or by replying to the Telegram notification; either way it lands on the ticket and in the customer's chat." />
      <Panel flush>
        <div className="flex flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-1">
            {TABS.map((t) => {
              const n = counts ? (t.key === "all" ? counts.open + counts.answered + counts.closed : counts[t.key]) : undefined;
              return (
                <button key={t.key} onClick={() => { setStatus(t.key); setPage(1); setOpen(null); }} data-testid={`tab-tickets-${t.key}`}
                  className={cn("rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors", status === t.key ? "bg-[#f1f1f1] text-foreground dark:bg-white/10" : "text-muted-foreground hover:text-foreground")}>
                  {t.label}{n !== undefined && <span className={cn("ml-1.5 rounded-md px-1.5 py-px text-[11px] font-semibold", t.key === "open" && n ? "bg-[#ffd79d] text-[#5e4200]" : "bg-[#e3e3e3] text-foreground dark:bg-white/10")}>{n}</span>}
                </button>
              );
            })}
          </div>
          <div className="relative w-full md:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)} placeholder="Ticket number, username or Telegram ID" className="h-8 pl-8 pr-8 text-[13px]" data-testid="input-ticket-search" />
            {text && <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setText("")} aria-label="Clear"><X className="h-4 w-4" /></button>}
          </div>
        </div>
        {list.isError ? (
          <div className="p-4"><ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} /></div>
        ) : d && d.items.length === 0 ? (
          <EmptyState icon={<LifeBuoy className="h-5 w-5" />} title={q ? "No tickets match" : status === "open" ? "Nothing waiting for a reply" : "No tickets here"}>
            {q ? "Try the ticket number, a username or a Telegram ID." : "New tickets from the bot and the reseller panel appear here, and you also get a Telegram notification."}
          </EmptyState>
        ) : (
          <div className={cn("overflow-x-auto transition-opacity", list.isFetching && list.isPlaceholderData ? "opacity-60" : "")}>
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Ticket</th>
                  <th className="px-3 py-2 font-medium">From</th>
                  <th className="px-3 py-2 font-medium">Last message</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {list.isLoading && Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-border last:border-0">{Array.from({ length: 5 }).map((_, j) => <td key={j} className="px-3 py-3 first:px-4"><Bar className="h-3.5" /></td>)}</tr>
                ))}
                {!list.isLoading && d?.items.map((t) => (
                  <tr key={t.id} onClick={() => setOpen(t.id)} data-testid={`row-ticket-${t.id}`} className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-[#f7f7f7] dark:hover:bg-white/5">
                    <td className="px-4 py-2.5"><div className="font-medium">{t.topicLabel}</div><div className="font-mono text-[11px] text-muted-foreground">{t.id}</div></td>
                    <td className="px-3 py-2.5"><div className="font-medium">{who(t)}</div><div className="text-xs text-muted-foreground">{t.reseller ? "Reseller" : "Customer"} · via {t.channel === "web" ? "web panel" : "bot"}</div></td>
                    <td className="max-w-[320px] px-3 py-2.5"><div className="truncate"><span className="text-muted-foreground">{t.lastSender === "support" ? "You: " : ""}</span>{t.preview}</div><div className="text-xs text-muted-foreground">{t.messages} message{t.messages === 1 ? "" : "s"}</div></td>
                    <td className="px-3 py-2.5"><StatusBadge status={t.status === "open" ? "needs reply" : t.status} tone={tone(t.status)} /></td>
                    <td className="px-3 py-2.5 whitespace-nowrap"><div className="num">{formatDateTime(t.updatedAt)}</div><div className="text-xs text-muted-foreground">{relativeTime(t.updatedAt)}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {d && (d.more || page > 1) && (
          <div className="flex items-center justify-end gap-1 border-t border-border px-4 py-2.5 text-sm">
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
            <span className="num px-2 text-muted-foreground">Page {page}</span>
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={!d.more} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        )}
      </Panel>
      {open && <TicketDialog id={open} onClose={() => { setOpen(null); qc.invalidateQueries({ queryKey: getListAdminTicketsQueryKey() }); }} />}
    </>
  );
}

function TicketDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useGetAdminTicket(id, { query: { queryKey: getGetAdminTicketQueryKey(id), refetchInterval: 20000 } });
  const reply = useReplyAdminTicket();
  const setStatus = useSetAdminTicketStatus();
  const [body, setBody] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  const d = q.data;
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [d?.messages.length]);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: getGetAdminTicketQueryKey(id) });
    qc.invalidateQueries({ queryKey: getListAdminTicketsQueryKey() });
    qc.invalidateQueries({ queryKey: getGetAdminOverviewQueryKey() });
  };
  const send = (e: FormEvent) => {
    e.preventDefault();
    const text = body.trim();
    if (!text) return;
    reply.mutate({ id, data: { body: text } }, {
      onSuccess: (v) => { toast({ title: v.delivered === false ? "Saved, but Telegram could not deliver it" : "Reply sent", description: v.delivered === false ? "The customer may have blocked the bot. They can still read it in the web panel." : undefined }); setBody(""); refresh(); },
    });
  };
  const toggle = () => {
    if (!d) return;
    const next = d.ticket.status === "closed" ? "open" : "closed";
    setStatus.mutate({ id, data: { status: next } }, { onSuccess: () => { toast({ title: next === "closed" ? "Ticket closed" : "Ticket reopened" }); refresh(); } });
  };
  const t = d?.ticket;
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="flex max-h-[90dvh] max-w-2xl flex-col overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-5 pb-3 pt-5">
          <DialogTitle className="flex flex-wrap items-center gap-2">{t ? t.topicLabel : "Ticket"} <span className="font-mono text-sm font-normal text-muted-foreground">{id}</span>{t && <StatusBadge status={t.status === "open" ? "needs reply" : t.status} tone={tone(t.status)} />}</DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {t && <>
              <span>{who(t)}{t.reseller ? " · reseller" : ""} · via {t.channel === "web" ? "web panel" : "bot"}</span>
              <CopyId value={String(t.telegramId)} label="Telegram ID" />
              <span>opened {formatDateTime(t.createdAt)}</span>
            </>}
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto bg-[#f7f7f7] px-5 py-4 dark:bg-black/20">
          {q.isError && <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />}
          {!d ? <div className="space-y-2"><Bar className="h-4" /><Bar className="h-4 w-2/3" /></div> : (
            <div className="flex flex-col gap-2.5">
              {d.messages.map((m) => (
                <div key={m.id} className={cn("max-w-[85%] rounded-xl px-3 py-2 text-sm shadow-sm", m.sender === "support" ? "self-end bg-[#303030] text-white dark:bg-[#e3e3e3] dark:text-[#1a1a1a]" : "self-start bg-card")}>
                  <div className={cn("mb-0.5 text-[11px]", m.sender === "support" ? "opacity-70" : "text-muted-foreground")}>{m.sender === "support" ? "You" : who(d.ticket)} · {formatDateTime(m.createdAt)}</div>
                  <div className="whitespace-pre-wrap break-words">{m.body}</div>
                </div>
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>
        <form onSubmit={send} className="border-t border-border px-5 py-3">
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} rows={3} placeholder={t?.status === "closed" ? "Replying reopens the ticket and notifies the customer" : "Write your answer. It is sent to the customer in Telegram."} className="text-sm" data-testid="input-ticket-reply" />
          {reply.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(reply.error)}</p>}
          {setStatus.isError && <p className="mt-2 text-xs text-destructive">{errorMessage(setStatus.error)}</p>}
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <Button type="button" variant="outline" size="sm" disabled={!t || setStatus.isPending} onClick={toggle} data-testid="button-ticket-toggle">{t?.status === "closed" ? "Reopen" : "Close ticket"}</Button>
            <Button type="submit" size="sm" disabled={reply.isPending || !body.trim()} data-testid="button-ticket-send">{reply.isPending ? "Sending…" : "Send reply"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function TicketsPage() {
  return <AdminShell><TicketsList /></AdminShell>;
}
