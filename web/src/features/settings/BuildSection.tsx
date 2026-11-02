// The Build half of the Settings tab: preset, steps, retries, failure mode, merge and deploy.
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { AiStepEditor } from "@/features/settings/AiStepEditor"
import { ExplainDialog } from "@/features/settings/ExplainDialog"
import { StepToggleList } from "@/features/settings/StepToggleList"
import { getPath, sameValue } from "@/features/settings/dotted"
import { useLibraryPresets, usePlanRows, useSetPreset, useSetSettings, useSettings } from "@/lib/queries"
import type { PlanStep } from "@/lib/types"

export const ON_FAILURE = [
  { value: "continue", label: "Continue", help: "Move on to tasks that don't depend on the failed one, and flag it." },
  { value: "pause", label: "Pause for me", help: "Pause and show an escalation; press Acknowledged when fixed." },
  { value: "delegate", label: "Delegate to the project chat", help: "The project's chat tries to fix it and only alerts you if it can't." },
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
        step={s.name} title={s.title} models={models} source={source}
        effective={(getPath(values, `steps.${s.name}`) ?? {}) as Record<string, unknown>}
        changes={changes} onChange={set}
      />
    ) : null

  return (
    <Card>
      <CardHeader><CardTitle>Build</CardTitle></CardHeader>
      <CardContent className="space-y-8">
        <section className="space-y-3" aria-label="Preset">
          <h3 className="font-semibold">Preset</h3>
          <RadioGroup value={preset} onValueChange={setChosen} aria-label="Preset">
            {presetList.map((p) => (
              <div key={p.name} className="flex items-start gap-2">
                <RadioGroupItem value={p.name} id={`preset-${p.name}`} className="mt-1" />
                <Label htmlFor={`preset-${p.name}`} className="flex-col items-start gap-0 font-normal">
                  <span className="font-medium">{p.title}</span>
                  <span className="text-sm text-muted-foreground">{p.description}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>
          {preset !== String(values.preset ?? "custom") && (
            <p className="text-sm text-muted-foreground">Use Reset to preset to apply a preset's values.</p>
          )}
          <Button variant="outline" onClick={() => setResetting(true)} disabled={reset.isPending}>Reset to preset</Button>
        </section>

        <section className="space-y-3" aria-label="Steps">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">Steps</h3>
            <button type="button" className="min-h-11 text-sm underline" onClick={() => setExplaining(true)}>
              Show the effective step list
            </button>
          </div>
          <StepToggleList
            steps={plan.data.steps} values={stepOn} renderExtra={aiEditor}
            onChange={(n, on) => set(`steps.${n}.on`, on)}
          />
        </section>

        <section className="space-y-2" aria-label="Retries">
          <h3 className="font-semibold">Retries</h3>
          <Label htmlFor="bs-max-tries">Tries per task</Label>
          <Input
            id="bs-max-tries" type="number" min={1} max={10} className="w-24"
            value={String(val("max_tries") ?? "")}
            onChange={(e) => set("max_tries", e.target.value === "" ? undefined : Number(e.target.value))}
          />
        </section>

        <section className="space-y-2" aria-label="On failure">
          <h3 className="font-semibold">On failure</h3>
          <RadioGroup value={String(val("on_failure") ?? "pause")} onValueChange={(v) => set("on_failure", v)} aria-label="On failure">
            {ON_FAILURE.map((o) => (
              <div key={o.value} className="flex items-start gap-2">
                <RadioGroupItem value={o.value} id={`of-${o.value}`} className="mt-1" />
                <Label htmlFor={`of-${o.value}`} className="flex-col items-start gap-0 font-normal">
                  <span className="font-medium">{o.label}</span>
                  <span className="text-sm text-muted-foreground">{o.help}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>
        </section>

        <section className="space-y-2" aria-label="Merge">
          <h3 className="font-semibold">Merge</h3>
          <RadioGroup
            value={locked ? "ask" : String(val("merge") ?? "auto")} disabled={locked}
            onValueChange={(v) => set("merge", v)} aria-label="Merge"
          >
            {MERGE.map((o) => (
              <div key={o.value} className="flex items-start gap-2">
                <RadioGroupItem value={o.value} id={`mg-${o.value}`} className="mt-1" />
                <Label htmlFor={`mg-${o.value}`} className="flex-col items-start gap-0 font-normal">
                  <span className="font-medium">{o.label}</span>
                  <span className="text-sm text-muted-foreground">{o.help}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>
          {locked && <p className="text-sm text-muted-foreground">Phoenix's own project always asks before merging.</p>}
        </section>

        <section className="space-y-3" aria-label="Deploy">
          <h3 className="font-semibold">Deploy</h3>
          <div className="space-y-1">
            <Label htmlFor="bs-deploy-with">Deploy with</Label>
            <Select value={deployWith} onValueChange={(v) => set("deploy.with", v)}>
              <SelectTrigger id="bs-deploy-with" aria-label="Deploy with" className="w-full md:w-64"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="none">none</SelectItem></SelectContent>
            </Select>
            <p className="text-sm text-muted-foreground">Deployers come later.</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="bs-deploy-mode">When to deploy</Label>
            <Select
              disabled={deployWith === "none"} value={String(val("deploy.mode") ?? "off")}
              onValueChange={(v) => set("deploy.mode", v)}
            >
              <SelectTrigger id="bs-deploy-mode" aria-label="When to deploy" className="w-full md:w-64"><SelectValue /></SelectTrigger>
              <SelectContent>{DEPLOY_MODES.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <span className="flex min-h-11 min-w-11 items-center justify-center">
              <Switch
                id="bs-deploy-preview" aria-label="Deploy a preview" disabled={deployWith === "none"}
                checked={Boolean(val("deploy.preview"))} onCheckedChange={(v) => set("deploy.preview", v)}
              />
            </span>
            <Label htmlFor="bs-deploy-preview" className="font-normal">Deploy a preview</Label>
          </div>
        </section>

        {problems.length > 0 && (
          <Alert variant="destructive">
            <AlertTitle>Nothing was saved</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </AlertDescription>
          </Alert>
        )}
        <div className="flex items-center gap-3">
          <Button disabled={!dirty || save.isPending} onClick={doSave}>Save build settings</Button>
          {dirty && <span className="text-sm text-muted-foreground">Unsaved changes</span>}
        </div>

        <ConfirmDialog
          open={resetting} onOpenChange={setResetting} title="Reset to preset?"
          body={`This sets the preset to ${preset} and clears every per-step on/off choice. Other step settings stay, and unsaved edits here are dropped.`}
          confirmLabel="Reset to preset" onConfirm={doReset}
        />
        <ExplainDialog name={name} open={explaining} onOpenChange={setExplaining} />
      </CardContent>
    </Card>
  )
}
