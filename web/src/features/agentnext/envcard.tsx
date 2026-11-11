// The .env upload card: the file is read in the browser, names are listed (never values) and one save goes to Phoenix as Alex.
import { useEffect, useState } from "react"

import { api } from "@/lib/api"
import { answerBrowser } from "./choicecard"
import { parseEnv, type EnvRow } from "./envfile"

/** What the agent asked: the project and why. */
export interface EnvAsk { project: string; why: string }

/** Pick out an .env request that fits the shape; null when it does not. */
export function envAskFrom(data: unknown): EnvAsk | null {
  const d = (data ?? {}) as Record<string, unknown>
  if (typeof d.project !== "string" || !d.project) return null
  return { project: d.project, why: typeof d.why === "string" ? d.why : "" }
}

type Phase = "open" | "saving" | "saved" | "cancelled"

/** A file chooser, the names found with Secret/Public and conflict choices, then Add keys or Cancel. */
export function EnvUploadCard({ ask, callId }: { ask: EnvAsk; callId: string }) {
  const [rows, setRows] = useState<EnvRow[]>([])
  const [existing, setExisting] = useState<Set<string>>(new Set())
  const [replace, setReplace] = useState<Set<string>>(new Set())
  const [phase, setPhase] = useState<Phase>("open")
  const [error, setError] = useState("")
  const [counts, setCounts] = useState({ added: 0, replaced: 0, kept: 0 })

  useEffect(() => {
    api.keys(ask.project).then((k) => setExisting(new Set(k.map((r) => r.name)))).catch(() => setExisting(new Set()))
  }, [ask.project])

  const choose = async (file: File | undefined) => {
    if (!file) return
    setError("")
    setReplace(new Set())
    setRows(parseEnv(await file.text()))
  }
  const toggle = (name: string, on: boolean) =>
    setReplace((s) => { const n = new Set(s); if (on) n.add(name); else n.delete(name); return n })

  const add = async () => {
    const send = rows.filter((r) => r.value && (!existing.has(r.name) || replace.has(r.name)))
    const replaced = send.filter((r) => existing.has(r.name)).length
    const kept = rows.filter((r) => existing.has(r.name) && !replace.has(r.name)).length
    setPhase("saving")
    setError("")
    try {
      if (send.length) await api.saveKeys(ask.project, send.map((r) => ({ name: r.name, value: r.value, secret: r.secret })))
    } catch (err) {
      setPhase("open")
      setError(err instanceof Error ? err.message : "The keys could not be saved.")
      return
    }
    const next = { added: send.length - replaced, replaced, kept }
    setCounts(next)
    setRows([])
    setPhase("saved")
    try { await answerBrowser(callId, { status: "saved", ...next }) } catch { /* the run times out on its own */ }
  }
  const cancel = async () => {
    setRows([])
    setPhase("cancelled")
    try { await answerBrowser(callId, { status: "cancelled" }) } catch { /* the run times out on its own */ }
  }

  return (
    <section className="card flex flex-col gap-2" aria-label="Upload a .env file" data-testid="env-card">
      <strong>The agent asks for a .env file</strong>
      <p>Project: <strong>{ask.project}</strong></p>
      {ask.why && <p>Why: {ask.why}</p>}
      {phase === "saved" && <p>Added {counts.added}, replaced {counts.replaced}, kept {counts.kept}.</p>}
      {phase === "cancelled" && <p>Cancelled.</p>}
      {(phase === "open" || phase === "saving") && (
        <>
          <input type="file" aria-label="Choose a .env file" disabled={phase === "saving"} onChange={(e) => void choose(e.target.files?.[0])} />
          {rows.length > 0 && (
            <ul aria-label="Names found">
              {rows.map((r) => (
                <li key={r.name}>
                  {r.name}: {r.secret ? "Secret" : "Public"}
                  {existing.has(r.name) && (
                    <span>
                      {" "}(already set){" "}
                      <label><input type="radio" name={`c-${r.name}`} checked={!replace.has(r.name)} onChange={() => toggle(r.name, false)} /> Keep existing</label>{" "}
                      <label><input type="radio" name={`c-${r.name}`} checked={replace.has(r.name)} onChange={() => toggle(r.name, true)} /> Replace</label>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {error && <p role="alert">{error}</p>}
          <div className="flex gap-2">
            <button type="button" className="btn" disabled={phase === "saving" || !rows.length} onClick={() => void add()}>Add keys</button>
            <button type="button" className="btn" disabled={phase === "saving"} onClick={() => void cancel()}>Cancel</button>
          </div>
        </>
      )}
    </section>
  )
}
