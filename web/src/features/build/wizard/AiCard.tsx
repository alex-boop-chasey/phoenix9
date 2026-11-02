// One AI step on the Models slide: a card that opens to its model, fallback models, tools and limits.
import { useId, useState } from "react"

import { Icon } from "@/components/Icon"
import { Button } from "@/components/ui/button"
import type { PlanStep } from "@/lib/types"

import { SwitchRow } from "./Choice"
import { TOOLS, editList } from "./model"

/** Models offered when the presets name none. */
const KNOWN_MODELS = ["claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5"]

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [])
const asNumber = (v: unknown): number | undefined => (typeof v === "number" && !Number.isNaN(v) ? v : undefined)

/** The model choices: the known ones plus anything the presets or this card already use. */
export function modelChoices(...used: (string | undefined)[][]): string[] {
  return [...new Set([...KNOWN_MODELS, ...used.flat().filter((m): m is string => !!m)])]
}

/** A card for one AI step; `preset` holds the defaults (from Phoenix settings), `edits` what was changed here. */
export function AiCard({ step, preset, edits, models, onEdit }: {
  step: PlanStep
  preset: Record<string, unknown>
  edits: Record<string, unknown>
  models: string[]
  onEdit: (key: string, value: unknown) => void
}) {
  const [open, setOpen] = useState(false)
  const uid = useId()
  const key = (k: string) => `steps.${step.name}.${k}`
  const value = (k: string): unknown => (key(k) in edits ? edits[key(k)] : preset[k])
  const model = String(value("model") ?? "")
  const fallbacks = asList(value("fallback_models"))
  const tools = asList(value("tools"))
  const edited = Object.keys(edits).some((k) => k.startsWith(`steps.${step.name}.`))
  const choices = modelChoices([model], fallbacks, models)
  const setList = (k: string, list: string[]) => onEdit(key(k), list)
  const setNumber = (k: string, text: string) => onEdit(key(k), text === "" ? undefined : Number(text))
  const body = `${uid}-body`

  return (
    <div className="aic" data-open={open} data-step={step.name} role="group" aria-label={step.title}>
      <div className="aic-h">
        <b className="row" style={{ gap: 8 }}><Icon name="sparkle" />{step.title}</b>
        <span className="row">
          {open ? <span className="src">{edited ? "edited here" : "from: Phoenix default"}</span>
            : <span className="mono small">{model || "default model"}</span>}
          <Button variant="secondary" size="sm" aria-expanded={open} aria-controls={body} onClick={() => setOpen(!open)}>
            {open ? "Close" : "Model and tools"}
          </Button>
        </span>
      </div>
      {open && (
        <div className="aic-b" id={body}>
          <div className="field">
            <label htmlFor={`${uid}-model`}>Model</label>
            <select
              id={`${uid}-model`} className="select" style={{ fontFamily: "var(--f-mono)" }} value={model}
              onChange={(e) => onEdit(key("model"), e.target.value)}
            >
              {choices.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div className="lane" role="group" aria-label="Fallback models">
            {fallbacks.map((f, i) => (
              <div className="lane-row" key={`${i}-${f}`}>
                <span className="n">{i + 1}</span>
                <select
                  className="select" style={{ fontFamily: "var(--f-mono)" }} aria-label={`Fallback model ${i + 1}`} value={f}
                  onChange={(e) => setList("fallback_models", fallbacks.map((x, j) => (j === i ? e.target.value : x)))}
                >
                  {modelChoices([f], choices).map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <span className="ctl">
                  <Button variant="ghost" size="icon-sm" aria-label={`Move fallback ${i + 1} up`} disabled={i === 0}
                    onClick={() => setList("fallback_models", editList(fallbacks, { up: i }))}>
                    <Icon name="caret-down" className="rotate-180" />
                  </Button>
                  <Button variant="ghost" size="icon-sm" aria-label={`Move fallback ${i + 1} down`} disabled={i === fallbacks.length - 1}
                    onClick={() => setList("fallback_models", editList(fallbacks, { down: i }))}>
                    <Icon name="caret-down" />
                  </Button>
                  <Button variant="ghost" size="icon-sm" aria-label={`Remove fallback ${i + 1}`}
                    onClick={() => setList("fallback_models", editList(fallbacks, { remove: i }))}>
                    <Icon name="x" />
                  </Button>
                </span>
              </div>
            ))}
            <Button
              variant="ghost" size="sm" style={{ justifySelf: "start" }}
              onClick={() => setList("fallback_models", editList(fallbacks, { add: choices.find((m) => m !== model && !fallbacks.includes(m)) ?? "" }))}
            >
              <Icon name="plus" />Add a fallback model
            </Button>
            <p className="help">Tried in this order if the first one is unavailable.</p>
          </div>
          <span className="lbl">Tools it may use</span>
          <div className="rail choices">
            {TOOLS.map(([label, tool]) => (
              <SwitchRow
                key={tool} id={`${uid}-tool-${tool}`} label={label} checked={tools.includes(tool)}
                onChange={(on) => setList("tools", on ? [...tools, tool] : tools.filter((t) => t !== tool))}
              />
            ))}
          </div>
          <div className="g2">
            <div className="field">
              <label htmlFor={`${uid}-turns`}>Turn limit</label>
              <input
                id={`${uid}-turns`} className="input" inputMode="numeric"
                value={String(asNumber(value("max_turns")) ?? "")} onChange={(e) => setNumber("max_turns", e.target.value)}
              />
              <span className="help">How many back-and-forth turns the AI may take before it stops.</span>
            </div>
            <div className="field">
              <label htmlFor={`${uid}-time`}>Time limit (minutes)</label>
              <input
                id={`${uid}-time`} className="input" inputMode="numeric"
                value={String(asNumber(value("timeout")) ?? "")} onChange={(e) => setNumber("timeout", e.target.value)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
