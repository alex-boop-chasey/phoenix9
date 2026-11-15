// The masked key card: Alex types a key here; it goes straight to Phoenix and the agent only hears saved or cancelled.
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiBase, api } from "@/lib/api"
import { Mark, NeedsYou, cardClass } from "./cardparts"

/** What the agent asked for: which project and key, and why. */
export interface KeyAsk { project: string; name: string; why: string }

/** Pick out a key request that fits the shape; null when it does not. */
export function keyAskFrom(data: unknown): KeyAsk | null {
  const d = (data ?? {}) as Record<string, unknown>
  if (typeof d.project !== "string" || typeof d.name !== "string") return null
  return { project: d.project, name: d.name, why: typeof d.why === "string" ? d.why : "" }
}

/** Tell the agent only how it went; the value is never part of this. */
async function answerAgent(callId: string, status: "saved" | "cancelled") {
  await fetch(new URL(`agent-next/browser-results/${encodeURIComponent(callId)}`, apiBase()).toString(), {
    method: "POST",
    headers: { "X-Phoenix": "1", "Content-Type": "application/json" },
    body: JSON.stringify({ result: { status } }),
  })
}

/** A masked field for one key: Save posts it to Phoenix, Cancel drops it; either way the agent hears the status. */
export function KeyInputCard({ ask, callId, onDone }: { ask: KeyAsk; callId: string; onDone?: (status: "saved" | "cancelled") => void }) {
  const [value, setValue] = useState("")
  const [state, setState] = useState<"open" | "saving" | "saved" | "cancelled">("open")
  const [error, setError] = useState("")

  const finish = async (status: "saved" | "cancelled") => {
    setState(status)
    try { await answerAgent(callId, status) } catch { /* the agent's run will time out on its own */ }
    onDone?.(status)
  }
  const save = async () => {
    const typed = value
    if (!typed) return
    setValue("")
    setState("saving")
    setError("")
    try {
      await api.saveKeys(ask.project, [{ name: ask.name, value: typed, secret: true }])
    } catch (err) {
      setState("open")
      setError(err instanceof Error ? err.message : "The key could not be saved.")
      return
    }
    await finish("saved")
  }
  const cancel = () => { setValue(""); void finish("cancelled") }

  const waiting = state === "open" || state === "saving"
  return (
    <section className={cardClass(waiting)} aria-label="Key needed" data-testid="key-card">
      <h3 className="ag-card-h">The agent needs a key{waiting ? <NeedsYou /> : null}</h3>
      <div className="ag-card-b">
        <p>Project: <strong>{ask.project}</strong></p>
        <p>Key: <strong>{ask.name}</strong></p>
        {ask.why && <p>Why: {ask.why}</p>}
        {state === "saved" && <p className="ag-result"><Mark ok /><span>Saved.</span></p>}
        {state === "cancelled" && <p className="ag-quiet">Cancelled.</p>}
      </div>
      {(state === "open" || state === "saving") && (
        <>
          <Input
            type="password" autoComplete="off" spellCheck={false} aria-label={`Value for ${ask.name}`}
            value={value} onChange={(e) => setValue(e.target.value)} disabled={state === "saving"}
          />
          {error && <p role="alert" className="ag-result"><Mark ok={false} /><span>{error}</span></p>}
          <div className="ag-card-f">
            <Button variant="secondary" onClick={cancel} disabled={state === "saving"}>Cancel</Button>
            <Button variant="primary" onClick={save} disabled={state === "saving" || !value}>Save</Button>
          </div>
        </>
      )}
    </section>
  )
}
