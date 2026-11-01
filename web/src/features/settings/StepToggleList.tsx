// The steps of a plan grouped by where they run, each with a Switch, a kind badge and a Safety label.
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { useLibrarySteps } from "@/lib/queries"
import type { PlanStep, StepGroup } from "@/lib/types"

const GROUPS: { group: StepGroup; title: string }[] = [
  { group: "run-start", title: "At the start" },
  { group: "task", title: "For every task" },
  { group: "run-finish", title: "At the end" },
]
const KIND_LABEL = { ai: "AI", script: "script", gate: "gate" } as const

const forcedOff = (s: PlanStep) => !s.on && s.reason.startsWith("needs ")

/** The checked state of a step: the caller's value, else what the plan says. */
export const stepIsOn = (s: PlanStep, values: Record<string, boolean>) => values[s.name] ?? s.on

/** Steps grouped as At the start / For every task / At the end, each with an on/off Switch. */
export function StepToggleList({
  steps, values, onChange, readOnly = false, renderExtra,
}: {
  steps: PlanStep[]
  values: Record<string, boolean>
  onChange: (name: string, on: boolean) => void
  readOnly?: boolean
  renderExtra?: (step: PlanStep) => React.ReactNode
}) {
  const library = useLibrarySteps()
  const description = (name: string) => library.data?.steps.find((s) => s.name === name)?.description ?? ""
  return (
    <div className="space-y-6">
      {GROUPS.map(({ group, title }) => {
        const rows = steps.filter((s) => s.group === group).sort((a, b) => a.order - b.order)
        if (!rows.length) return null
        return (
          <section key={group} aria-label={title} className="space-y-2">
            <h3 className="text-sm font-semibold text-muted-foreground">{title}</h3>
            <ul className="divide-y rounded-md border">
              {rows.map((s) => (
                <li key={s.name} className="p-3" data-step={s.name}>
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{s.title}</span>
                        <Badge variant="outline">{KIND_LABEL[s.kind]}</Badge>
                        {!!s.safety && <Badge variant="secondary">Safety</Badge>}
                      </div>
                      {description(s.name) && <p className="text-sm text-muted-foreground">{description(s.name)}</p>}
                      {forcedOff(s) && <p className="text-sm text-muted-foreground">{s.reason}</p>}
                    </div>
                    <StepSwitch step={s} on={stepIsOn(s, values)} readOnly={readOnly} onChange={onChange} />
                  </div>
                  {renderExtra?.(s)}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

function StepSwitch({
  step, on, readOnly, onChange,
}: { step: PlanStep; on: boolean; readOnly: boolean; onChange: (name: string, on: boolean) => void }) {
  const locked = step.default === "always"
  return (
    <div className="flex shrink-0 items-center gap-2">
      {locked && <span className="text-xs text-muted-foreground">always on</span>}
      <span className="flex min-h-11 min-w-11 items-center justify-center">
        <Switch
          aria-label={step.title} checked={locked ? true : on}
          disabled={readOnly || locked || forcedOff(step)}
          onCheckedChange={(v) => onChange(step.name, v)}
        />
      </span>
    </div>
  )
}
