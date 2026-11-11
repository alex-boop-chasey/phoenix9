// The choice card: chips for the agent's options; the answer carries only a status and the picked indexes.
import { useState } from "react"

import { apiBase } from "@/lib/api"

/** One option as drawn: plain label and hint. */
export interface ChoiceItem { label: string; hint: string }
/** What the agent asked: a question, 2 to 12 options and whether several may be picked. */
export interface ChoiceAsk { question: string; options: ChoiceItem[]; multiple: boolean }

/** Pick out a choice request that fits the shape; null when it does not. */
export function choiceAskFrom(data: unknown): ChoiceAsk | null {
  const d = (data ?? {}) as Record<string, unknown>
  if (typeof d.question !== "string" || !Array.isArray(d.options)) return null
  if (d.options.length < 2 || d.options.length > 12) return null
  const options: ChoiceItem[] = []
  for (const o of d.options) {
    const r = (o ?? {}) as Record<string, unknown>
    if (typeof r.label !== "string" || !r.label) return null
    options.push({ label: r.label, hint: typeof r.hint === "string" ? r.hint : "" })
  }
  return { question: d.question, options, multiple: d.multiple === true }
}

/** Tell the agent only the status and the picked indexes. */
export async function answerBrowser(callId: string, result: Record<string, unknown>) {
  await fetch(new URL(`agent-next/browser-results/${encodeURIComponent(callId)}`, apiBase()).toString(), {
    method: "POST",
    headers: { "X-Phoenix": "1", "Content-Type": "application/json" },
    body: JSON.stringify({ result }),
  })
}

/** A question with one chip per option; once answered it shows what was picked and takes no more clicks. */
export function ChoiceCard({ ask, callId }: { ask: ChoiceAsk; callId: string }) {
  const [picked, setPicked] = useState<number[]>([])
  const [done, setDone] = useState<"open" | "picked" | "cancelled">("open")

  const finish = async (status: "picked" | "cancelled", indexes: number[]) => {
    if (done !== "open") return
    setDone(status)
    setPicked(indexes)
    const result = status === "picked" ? { status, picked: indexes } : { status }
    try { await answerBrowser(callId, result) } catch { /* the agent's run will time out on its own */ }
  }
  const click = (i: number) => {
    if (done !== "open") return
    if (!ask.multiple) { void finish("picked", [i]); return }
    setPicked((p) => (p.includes(i) ? p.filter((x) => x !== i) : [...p, i].sort((a, b) => a - b)))
  }

  return (
    <section className="card flex flex-col gap-2" aria-label="Choice" data-testid="choice-card">
      <strong>{ask.question}</strong>
      {done === "open" ? (
        <>
          <div className="flex flex-wrap gap-2">
            {ask.options.map((o, i) => (
              <button key={i} type="button" className="btn" aria-pressed={ask.multiple ? picked.includes(i) : undefined} title={o.hint || undefined} onClick={() => click(i)}>
                {o.label}{o.hint ? <span className="block text-xs">{o.hint}</span> : null}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            {ask.multiple && <button type="button" className="btn" disabled={!picked.length} onClick={() => void finish("picked", picked)}>Done</button>}
            <button type="button" className="btn" onClick={() => void finish("cancelled", [])}>Cancel</button>
          </div>
        </>
      ) : done === "picked" ? (
        <p>You picked: {picked.map((i) => ask.options[i]?.label).join(", ")}</p>
      ) : (
        <p>Cancelled.</p>
      )}
    </section>
  )
}
