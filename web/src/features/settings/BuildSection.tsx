// The Build half of the Settings tab: preset, steps, retries, failure mode, merge and deploy.
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { SaveBar, SettingsRow } from "@/features/settings/ProjectSection"
import { Choices } from "@/features/build/wizard/Choice"
import { AiStepEditor } from "@/features/settings/AiStepEditor"
import { ExplainDialog } from "@/features/settings/ExplainDialog"
import { StepToggleList } from "@/features/settings/StepToggleList"
import { getPath, sameValue } from "@/features/settings/dotted"
import { useLibraryPresets, useLibraryTools, usePlanRows, useSetPreset, useSetSettings, useSettings } from "@/lib/queries"
import type { PlanStep } from "@/lib/types"

export const ON_FAILURE = [
  { value: "continue", label: "Continue", help: "Move on to tasks that don't depend on the failed one, and flag it." },
  { value: "pause", label: "Pause for me", help: "Pause and show an escalation; press Acknowledged when fixed." },
  { value: "delegate", label: "Hand it to Claude in the project folder", help: "The Phoenix agent is sent one message to fix it; you are alerted if it is asleep or can't." },
]
export const MERGE = [
  { value: "auto", label: "Merge automatically", help: "Merge when the checks pass." },
  { value: "ask", label: "Ask me first", help: "Wait for you to approve each merge." },
]
const DEPLOY_MODES = [
  { value: "on-merge", label: "When a merge happens" },
  { value: "button", label: "When I press a button" },
  { value: "off", label: "Off" },
]
const PRESET_FALLBACK: Record<string, string> = { custom: "Your own mix of steps." }

/** A changed value counts only when it differs from the saved one and is not just emptied. */
export function changedKeys(values: unknown, changes: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(changes)) {
    if (value === undefined || value === "") continue
    if (typeof value === "number" && Number.isNaN(value)) continue
    if (!sameValue(value, getPath(values, key))) out[key] = value
  }
  return out
}

function knownModels(values: Record<string, unknown>): string[] {
  const found = new Set<string>()
  const steps = (values.steps ?? {}) as Record<string, Record<string, unknown>>
  for (const s of Object.values(steps)) {
    if (typeof s.model === "string" && s.model) found.add(s.model)
    if (Array.isArray(s.fallback_models)) s.fallback_models.forEach((m) => typeof m === "string" && found.add(m))
  }
  return [...found]
}

/** The build settings form with its own Save. */
export function BuildSection({ name }: { name: string }) {
  const settings = useSettings(name)
  const toolList = useLibraryTools().data?.tools
  const plan = usePlanRows(name)
  const presets = useLibraryPresets()
  const save = useSetSettings(name)
  const reset = useSetPreset(name)
  const [changes, setChanges] = useState<Record<string, unknown>>({})
  const [chosen, setChosen] = useState<string | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [resetting, setResetting] = useState(false)
  const [explaining, setExplaining] = useState(false)

  const values = settings.data?.values
  const source = settings.data?.source
  const models = useMemo(() => (values ? knownModels(values) : []), [values])
  if (!values || !source || !plan.data) return null

  const pending = changedKeys(values, changes)
  const dirty = Object.keys(pending).length > 0
  const val = (key: string) => (key in changes ? changes[key] : getPath(values, key))
  const set = (key: string, value: unknown) => setChanges((c) => ({ ...c, [key]: value }))
  const preset = chosen ?? String(values.preset ?? "custom")
  const locked = name === "phoenix9"
  const deployWith = String(val("deploy.with") ?? "none")

  const presetList = [...(presets.data?.presets ?? [])]
  if (!presetList.some((p) => p.name === "custom")) {
    presetList.push({ name: "custom", title: "Custom", has_file: false, description: PRESET_FALLBACK.custom! })
  }

  const stepOn: Record<string, boolean> = {}
  for (const s of plan.data.steps) {
    const key = `steps.${s.name}.on`
    if (key in changes) stepOn[s.name] = Boolean(changes[key])
  }

  function doSave() {
    setProblems([])
    save.mutate(pending, {
      onSuccess: () => { setChanges({}); toast.success("Saved") },
      onError: (err) => setProblems(err.message.split("; ").filter(Boolean)),
    })
  }

  function doReset() {
    reset.mutate(preset, {
      onSuccess: () => { setChanges({}); setChosen(null); toast.success("Saved") },
      onError: (err) => setProblems(err.message.split("; ").filter(Boolean)),
    })
  }

  const aiEditor = (s: PlanStep) =>
    s.kind === "ai" ? (
      <AiStepEditor
        step={s.name} title={s.title} models={models} toolList={toolList} source={source}
        effective={(getPath(values, `steps.${s.name}`) ?? {}) as Record<string, unknown>}
        changes={changes} onChange={set}
      />
    ) : null

  const discard = () => { setChanges({}); setChosen(null); setProblems([]) }

  return (
    <div className="sect" id="sec-build">
      <div className="sect-h">
        <h2 className="h2">Build</h2>
        <span className="area"><Icon name="hammer" />Build</span>
      </div>

      <SettingsRow keys={["preset"]} id="s-preset" label="Preset">
        <div className="stackg">
          <Choices
            name="preset" label="Preset" value={preset} onChange={setChosen}
            options={presetList.map((p) => ({ value: p.name, label: p.title, help: p.description }))}
          />
          {preset !== String(values.preset ?? "custom") && (
            <p className="help">Use Reset to preset to apply a preset's values.</p>
          )}
          <button type="button" className="btn btn-secondary btn-sm" style={{ justifySelf: "start" }}
            disabled={reset.isPending} onClick={() => setResetting(true)}>
            Reset to preset
          </button>
        </div>
      </SettingsRow>

      <SettingsRow keys={["steps"]} label="Steps">
        <div className="stackg">
          <div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExplaining(true)}>
              Show the effective step list
            </button>
          </div>
          <StepToggleList
            steps={plan.data.steps} values={stepOn} renderExtra={aiEditor}
            onChange={(n, on) => set(`steps.${n}.on`, on)}
          />
        </div>
      </SettingsRow>

      <SettingsRow keys={["max_tries", "on_failure"]} id="s-fail" label="Failures">
        <div className="stackg">
          <div className="field" style={{ maxWidth: 200 }}>
            <label htmlFor="bs-max-tries">Tries per task</label>
            <input
              id="bs-max-tries" className="input" type="number" inputMode="numeric" min={1} max={10}
              value={String(val("max_tries") ?? "")}
              onChange={(e) => set("max_tries", e.target.value === "" ? undefined : Number(e.target.value))}
            />
          </div>
          <span className="lbl">When a task still fails</span>
          <Choices
            name="on_failure" label="On failure" value={String(val("on_failure") ?? "pause")} onChange={(v) => set("on_failure", v)}
            options={ON_FAILURE.map((o) => ({ value: o.value, label: o.label, help: o.help }))}
          />
        </div>
      </SettingsRow>

      <SettingsRow keys={["budget_usd"]} id="s-budget" label="Spending cap">
        <div className="field" style={{ maxWidth: 220 }}>
          <label htmlFor="bs-budget">Spending cap ($)</label>
          <input
            id="bs-budget" className="input" type="number" min={0} step="any" placeholder="No cap"
            value={String(val("budget_usd") ?? "")}
            onChange={(e) => set("budget_usd", e.target.value === "" ? undefined : Number(e.target.value))}
          />
        </div>
      </SettingsRow>

      <SettingsRow keys={["merge", "deploy"]} id="s-merge" label="Merge and deploy">
        <div className="stackg">
          <Choices
            name="merge" label="Merge" value={locked ? "ask" : String(val("merge") ?? "auto")} onChange={(v) => set("merge", v)}
            options={MERGE.map((o) => ({
              value: o.value, label: o.label, help: o.help, disabled: locked,
              icon: locked && o.value === "ask" ? <Icon name="lock" size="sm" /> : undefined,
            }))}
          />
          {locked && (
            <div className="blk-info"><Icon name="lock" /><span>Phoenix's own project always asks before merging.</span></div>
          )}
          <div className="dcard" aria-label="Deploy">
            <b>Deploy</b>
            <div className="field">
              <label htmlFor="bs-deploy-with">Deploy with</label>
              <select id="bs-deploy-with" className="select" value={deployWith} onChange={(e) => set("deploy.with", e.target.value)}>
                <option value="none">none</option>
              </select>
              <span className="help">Deployers come later.</span>
            </div>
            <div className="field">
              <label htmlFor="bs-deploy-mode">When to deploy</label>
              <select
                id="bs-deploy-mode" className="select" disabled={deployWith === "none"}
                value={String(val("deploy.mode") ?? "off")} onChange={(e) => set("deploy.mode", e.target.value)}
              >
                {DEPLOY_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <label className="swaprow" htmlFor="bs-deploy-preview">
              <input
                id="bs-deploy-preview" type="checkbox" role="switch" className="switch" aria-label="Deploy a preview"
                disabled={deployWith === "none"} checked={Boolean(val("deploy.preview"))}
                onChange={(e) => set("deploy.preview", e.target.checked)}
              />
              Deploy a preview
            </label>
          </div>
        </div>
      </SettingsRow>

      {problems.length > 0 && (
        <div className="blk-info" role="alert">
          <Icon name="warning-circle" />
          <div>
            <b>Nothing was saved</b>
            <ul className="list-disc pl-4">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        </div>
      )}
      {(dirty || preset !== String(values.preset ?? "custom")) && (
        <SaveBar label="Save build settings" busy={save.isPending} onDiscard={discard} onSave={doSave} />
      )}

      <ConfirmDialog
        open={resetting} onOpenChange={setResetting} title="Reset to preset?"
        body={`This sets the preset to ${preset} and clears every per-step on/off choice. Other step settings stay, and unsaved edits here are dropped.`}
        confirmLabel="Reset to preset" onConfirm={doReset}
      />
      <ExplainDialog name={name} open={explaining} onOpenChange={setExplaining} />
    </div>
  )
}
