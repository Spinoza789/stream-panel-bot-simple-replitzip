import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useGetAdminFaq, getGetAdminFaqQueryKey, useUpdateAdminFaq, type FaqItem } from "@workspace/api-client-react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Bar, ErrorState, Panel } from "./bits";
import { useAdminReady } from "./access";
import { useToast } from "@/hooks/use-toast";
import { errorMessage } from "@/lib/format";

const MAX_ITEMS = 30;
const MAX_QUESTION = 120;
const MAX_ANSWER = 1500;

/** Questions and answers customers see under FAQ in the Telegram bot. The button stays hidden there until one is saved. */
export function FaqPanel() {
  const ready = useAdminReady();
  const qc = useQueryClient();
  const { toast } = useToast();
  const faq = useGetAdminFaq({ query: { enabled: ready, queryKey: getGetAdminFaqQueryKey() } });
  const save = useUpdateAdminFaq();
  const [items, setItems] = useState<FaqItem[]>([]);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (faq.data && !dirty) setItems(faq.data.items); }, [faq.data, dirty]);

  const change = (next: FaqItem[]) => { setItems(next); setDirty(true); };
  const edit = (i: number, patch: Partial<FaqItem>) => change(items.map((it, n) => (n === i ? { ...it, ...patch } : it)));
  const move = (i: number, by: number) => { const next = [...items]; const [it] = next.splice(i, 1); next.splice(i + by, 0, it); change(next); };
  const incomplete = items.some((it) => !it.question.trim() || !it.answer.trim());
  const submit = () => {
    const cleaned = items.map((it) => ({ question: it.question.trim(), answer: it.answer.trim() }));
    save.mutate({ data: { items: cleaned } }, {
      onSuccess: (d) => { setItems(d.items); setDirty(false); qc.setQueryData(getGetAdminFaqQueryKey(), d); toast({ title: "FAQ saved", description: d.items.length ? "Customers see it in the bot straight away." : "The FAQ button is hidden in the bot while the list is empty." }); },
    });
  };

  return (
    <Panel title="Bot FAQ" aside={<span className="text-xs text-muted-foreground">{items.length} of {MAX_ITEMS}</span>}>
      {faq.isError ? <ErrorState message={errorMessage(faq.error)} onRetry={() => faq.refetch()} /> : !faq.data ? <Bar className="h-24" /> : (
        <div className="space-y-3 text-sm">
          <p className="text-xs text-muted-foreground">Shown under FAQ in the Telegram bot, in this order. While the list is empty the bot hides the FAQ button and offers Support instead.</p>
          {items.length === 0 && <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-muted-foreground" data-testid="text-faq-empty">No questions yet. Add the first one below.</p>}
          {items.map((it, i) => (
            <div key={i} className="rounded-lg border border-border p-3" data-testid={`faq-item-${i}`}>
              <div className="flex items-center gap-2">
                <span className="w-5 shrink-0 text-xs tabular-nums text-muted-foreground">{i + 1}</span>
                <Input value={it.question} maxLength={MAX_QUESTION} onChange={(e) => edit(i, { question: e.target.value })} placeholder="Question, for example: How long does payment take?" className="h-9" aria-label={`Question ${i + 1}`} data-testid={`input-faq-question-${i}`} />
                <Button type="button" size="icon" variant="ghost" className="h-8 w-8 shrink-0" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up"><ArrowUp className="h-4 w-4" /></Button>
                <Button type="button" size="icon" variant="ghost" className="h-8 w-8 shrink-0" disabled={i === items.length - 1} onClick={() => move(i, 1)} aria-label="Move down"><ArrowDown className="h-4 w-4" /></Button>
                <Button type="button" size="icon" variant="ghost" className="h-8 w-8 shrink-0 text-destructive" onClick={() => change(items.filter((_, n) => n !== i))} aria-label="Remove question" data-testid={`button-faq-remove-${i}`}><Trash2 className="h-4 w-4" /></Button>
              </div>
              <Textarea value={it.answer} maxLength={MAX_ANSWER} onChange={(e) => edit(i, { answer: e.target.value })} placeholder="Answer shown to the customer" rows={3} className="mt-2 ml-7 w-[calc(100%-1.75rem)]" aria-label={`Answer ${i + 1}`} data-testid={`input-faq-answer-${i}`} />
              <p className="ml-7 mt-1 text-right text-[11px] tabular-nums text-muted-foreground">{it.answer.length} / {MAX_ANSWER}</p>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" variant="outline" disabled={items.length >= MAX_ITEMS} onClick={() => change([...items, { question: "", answer: "" }])} data-testid="button-faq-add"><Plus className="mr-1 h-4 w-4" />Add question</Button>
            <Button type="button" size="sm" disabled={!dirty || incomplete || save.isPending} onClick={submit} data-testid="button-faq-save">{save.isPending ? "Saving…" : "Save FAQ"}</Button>
            {dirty && <Button type="button" size="sm" variant="ghost" onClick={() => { setItems(faq.data.items); setDirty(false); }}>Discard changes</Button>}
            {dirty && incomplete && <span className="text-xs text-muted-foreground">Fill in every question and answer, or remove the empty ones.</span>}
          </div>
          {save.isError && <p className="text-xs text-destructive">{errorMessage(save.error)}</p>}
        </div>
      )}
    </Panel>
  );
}
