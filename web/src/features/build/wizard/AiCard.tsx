// One AI step on the Models slide: a card that opens to its model, fallback models, tools and limits.
import { useId, useState } from "react"

import { Icon } from "@/components/Icon"
import { Button } from "@/components/ui/button"
import type { PlanStep } from "@/lib/types"

import { SwitchRow } from "./Choice"
import { useLibraryTools } from "@/lib/queries"
import { switchTool, toolState, usesDefaults } from "@/lib/tools"

import { ModelPicker } from "./ModelPicker"

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [])
const asNumber = (v: unknown): number | undefined => (typeof v === "number" && !Number.isNaN(v) ? v : undefined)

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
  const lists = { tools: asList(value("tools")), denied: asList(value("tools_denied")) }
  const library = useLibraryTools().data?.tools ?? []
  const edited = Object.keys(edits).some((k) => k.startsWith(`steps.${step.name}.`))
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
          <ModelPicker
            model={model} backups={fallbacks} models={models}
            onModel={(m) => onEdit(key("model"), m)} onBackups={(l) => setList("fallback_models", l)}
          />
          <span className="lbl">Tools it may use</span>
          {usesDefaults(lists) && <p className="help">Using this step's default tools. Switch one off to deny it.</p>}
          <div className="rail choices">
            {library.map((t) => (
              <SwitchRow
                key={t.name} id={`${uid}-tool-${t.name}`} label={t.label} help={t.help} checked={toolState(lists, t.name) !== "off"}
                onChange={(on) => {
                  const next = switchTool(lists, t.name, on)
                  setList("tools", next.tools)
                  setList("tools_denied", next.denied)
                }}
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
              <span className="help">The AI stops when it has used this many turns or this many minutes, whichever comes first.</span>
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
