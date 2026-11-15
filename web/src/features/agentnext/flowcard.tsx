// The flow card: where a guided flow is (step N of M), the facts picked so far, and a Cancel button; drawn from typed data only.
import { Button } from "@/components/ui/button"

/** The fixed chat message the Cancel button sends. */
export const CANCEL_MESSAGE = "Cancel this and stop."

/** Card data for one step of a guided flow. */
export interface FlowCardData { flow: string; status: "active" | "done" | "cancelled"; step: number; steps: number; label: string; facts: { name: string; value: string }[] }

const SECRET_WORDS = ["key", "secret", "token", "password", "value"]

function whole(v: unknown): v is number { return typeof v === "number" && Number.isInteger(v) && v >= 0 }
function factText(v: unknown): string | null {
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v)
  if (Array.isArray(v) && v.every((p) => typeof p === "string")) return v.join(", ")
  return null
}

/** The flow card data when it fits its shape, else null. Facts named like a secret are left out. */
export function flowFrom(data: unknown): FlowCardData | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null
  const d = data as Record<string, unknown>
  if (typeof d.flow !== "string" || !d.flow) return null
  if (d.status !== "active" && d.status !== "done" && d.status !== "cancelled") return null
  if (!whole(d.step) || !whole(d.steps) || d.steps < 1 || d.step > d.steps) return null
  if (typeof d.label !== "string") return null
  const facts: { name: string; value: string }[] = []
  const values = d.values
  if (values !== undefined && values !== null) {
    if (typeof values !== "object" || Array.isArray(values)) return null
    for (const [name, v] of Object.entries(values)) {
      const text = factText(v)
      if (text === null) return null
      if (SECRET_WORDS.some((w) => name.toLowerCase().includes(w))) continue
      facts.push({ name, value: text })
    }
  }
  return { flow: d.flow, status: d.status, step: d.step, steps: d.steps, label: d.label, facts }
}

function headline(c: FlowCardData): string {
  if (c.status === "done") return "Finished"
  if (c.status === "cancelled") return "Cancelled"
  return `Step ${c.step} of ${c.steps}: ${c.label}`
}

/** A fact's name in plain words: first letter capital, "_" and "-" as spaces ("github_owner" -> "Github owner"). */
export function plainLabel(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim()
  return words ? words[0]!.toUpperCase() + words.slice(1) : name
}

/** An older step of a flow, shown as one line. */
export function FlowLine({ card }: { card: FlowCardData }) {
  return <p className="ag-kind" data-testid="flow-line">{headline(card)}{card.status === "active" ? "" : `: ${card.label}`}</p>
}

/** The current step of a guided flow, with the facts so far; an active flow can be cancelled. */
export function FlowCard({ card, onSend }: { card: FlowCardData; onSend?: (message: string) => void }) {
  return (
    <section className="ag-card" data-testid="flow-card" aria-label="Guided flow">
      <h3 className="ag-card-h">{headline(card)}</h3>
      {card.status !== "active" && card.label ? <p className="ag-card-b">{card.label}</p> : null}
      {card.facts.length ? (
        <dl className="ag-facts">
          {card.facts.map((f) => <div key={f.name} data-testid="flow-fact"><dt>{plainLabel(f.name)}<span className="sr-only">: </span></dt><dd>{f.value}</dd></div>)}
        </dl>
      ) : null}
      {card.status === "active" ? <div className="ag-card-f"><Button variant="secondary" onClick={() => onSend?.(CANCEL_MESSAGE)}>Cancel</Button></div> : null}
    </section>
  )
}
