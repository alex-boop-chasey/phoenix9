// Phoenix settings > Models: a grid of AI step by model, fallback and second fallback, saved as Phoenix's defaults.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { post } from "@/lib/api"
import { useGlobal } from "@/lib/queries"
import { modelChoices } from "@/features/build/wizard/ModelPicker"

const NONE = ""
type Draft = Record<string, [string, string, string]>

/** Rows of [model, fallback, then] for every AI step. */
function toDraft(models: Record<string, { model: string; fallback_models: string[] }>): Draft {
  return Object.fromEntries(Object.entries(models).map(([k, m]) => [k, [m.model, m.fallback_models[0] ?? NONE, m.fallback_models[1] ?? NONE]]))
}

/** The Models panel. */
export function ModelsTab() {
  const g = useGlobal()
  const qc = useQueryClient()
  const models = g.data?.default_models
  const [draft, setDraft] = useState<Draft>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (models) setDraft(toDraft(models)) }, [models])

  if (!models) return <div className="gpanel" data-gp="models"><p className="small">Loading…</p></div>
  const saved = toDraft(models)
  const dirty = JSON.stringify(saved) !== JSON.stringify(draft)
  const all = Object.values(draft).flat()
  const options = modelChoices(all.filter(Boolean))

  function set(step: string, col: number, value: string) {
    const row: [string, string, string] = [...(draft[step] ?? ["", "", ""])] as [string, string, string]
    row[col] = value
    setDraft({ ...draft, [step]: row })
  }

  const problem = Object.entries(draft).map(([step, r]) => {
    const used = r.filter(Boolean)
    return new Set(used).size !== used.length ? `${models[step]?.title ?? step}: use each model once.` : ""
  }).find(Boolean)

  async function save() {
    setBusy(true)
    try {
      const steps = Object.fromEntries(Object.entries(draft).map(([k, r]) => [k, { model: r[0], fallback_models: r.slice(1).filter(Boolean) }]))
      await post("global/models", { steps })
      toast.success("Default models saved.")
      void qc.invalidateQueries({ queryKey: ["global"] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the models.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gpanel" data-gp="models">
      <section className="board" aria-labelledby="g-m">
        <div className="board-h">
          <h2 className="h2" id="g-m">Default models</h2>
          <span className="sp small">Used by every new build unless the build changes them</span>
        </div>
        <div className="board-b tscroll">
          <table className="mgrid">
            <thead><tr><th>Step</th><th>Model</th><th>If that's unavailable</th><th>Then</th></tr></thead>
            <tbody id="mgrid">
              {Object.entries(models).map(([step, m]) => (
                <tr key={step} data-step={step}>
                  <td>{m.title ?? step}</td>
                  {[0, 1, 2].map((col) => (
                    <td key={col}>
                      <label className="sr" htmlFor={`mg-${step}-${col}`}>{m.title ?? step} model {col + 1}</label>
                      <select id={`mg-${step}-${col}`} className="select" value={draft[step]?.[col] ?? ""} onChange={(e) => set(step, col, e.target.value)}>
                        {col > 0 && <option value={NONE}>None</option>}
                        {options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="board-b row">
          <button type="button" className="btn btn-primary" disabled={!dirty || busy || !!problem} onClick={() => void save()}>Save models</button>
          {dirty && <button type="button" className="btn btn-ghost" onClick={() => setDraft(saved)}>Discard</button>}
          {problem && <span className="cfgerr" role="alert">{problem}</span>}
        </div>
      </section>
      <div className="blk-info tip"><Icon name="lightbulb" /><span>Each build can still change these on its “Models and tools” step.</span></div>
    </div>
  )
}
