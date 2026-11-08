// Slide 7: one card per wizard step with the choices as label/value rows, the "use as defaults" box, and any submit error.
import type { ReactNode } from "react"

import { InfoBlock } from "@/components/InfoBlock"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

import { ON_FAILURE } from "@/features/settings/BuildSection"

import { aiCards, planInOrder, presetLabel, shownOn } from "./model"
import type { SlideProps } from "./Wizard"

const onOff = (on: boolean) => (on ? "On" : "Off")
const asList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [])

/** One card: a title, an Edit link back to its step, and its rows. */
function ReviewCard({ n, title, onEdit, children }: { n: number; title: string; onEdit: (n: number) => void; children: ReactNode }) {
  return (
    <section className="rv-card" aria-label={title} data-card={title}>
      <div className="rv-h">
        <h3 className="h3">{title}</h3>
        <button type="button" className="rv-edit" aria-label={`Edit ${title}`} onClick={() => onEdit(n)}>Edit</button>
      </div>
      {children}
    </section>
  )
}

/** Label/value rows. */
function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="rv-rows">
      {rows.map(([k, v]) => (
        <div key={k} data-fact={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Everything that will happen, grouped by wizard step. */
export function SlideReview({ state, dispatch, plan, baseline, presets, specs }: SlideProps) {
  const a = state.answers
  if (!plan) return <Skeleton className="h-40 w-full" />
  const spec = specs.find((s) => s.path === a.spec)
  const what = a.source === "spec" ? `${spec?.title ?? a.spec} (${a.spec})` : a.brief.trim()
  const edit = (slide: number) => dispatch({ type: "goto", slide })
  const preset = (name: string) => (baseline?.steps.find((s) => s.name === name)?.ai ?? {}) as Record<string, unknown>
  const pick = (step: string, k: string): unknown => {
    const key = `steps.${step}.${k}`
    return key in a.ai ? a.ai[key] : preset(step)[k]
  }
  const models: [string, string][] = aiCards(plan.steps, a).map((s) => {
    const backup = asList(pick(s.name, "fallback_models"))[0]
    const model = String(pick(s.name, "model") ?? "") || "Default model"
    return [s.title, backup ? `${model}, backup ${backup}` : model]
  })
  return (
    <div className="stackg">
      <ReviewCard n={1} title="What to build" onEdit={edit}>
        <Rows rows={[[a.source === "spec" ? "Spec" : "Brief for the Planner", what]]} />
      </ReviewCard>
      <ReviewCard n={2} title="Preset" onEdit={edit}>
        <Rows rows={[["Preset", presetLabel(a, presets)]]} />
      </ReviewCard>
      <ReviewCard n={3} title="Steps" onEdit={edit}>
        <div role="region" aria-label="Plan" className="stackg" style={{ gap: 10 }}>
          {planInOrder(plan.steps).map((g) => (
            <div key={g.group} className="space-y-1">
              <h4 className="text-sm font-medium text-muted-foreground">{g.title}</h4>
              <ul className="rv-chips">
                {g.steps.map((s) => {
                  const on = shownOn(s, a)
                  return (
                    <li
                      key={s.name} data-step={s.name} data-on={String(on)}
                      className={cn("rv-chip", !on && "line-through")}
                    >
                      {s.title}<span className="sr-only"> ({on ? "on" : "off"})</span>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </div>
      </ReviewCard>
      <ReviewCard n={4} title="Models and tools" onEdit={edit}>
        {models.length ? <Rows rows={models} /> : <p className="small">No AI steps are on.</p>}
      </ReviewCard>
      <ReviewCard n={5} title="Failures" onEdit={edit}>
        <Rows rows={[
          ["Tries per task", String(a.maxTries)],
          ["When a task still fails", ON_FAILURE.find((o) => o.value === a.onFailure)?.label ?? a.onFailure],
          ["Spending cap", a.budget.trim() ? `$${a.budget}` : "No cap"],
        ]} />
      </ReviewCard>
      <ReviewCard n={6} title="Finish" onEdit={edit}>
        <Rows rows={[
          ["Merge", a.merge === "ask" ? "Ask me first" : "Merge automatically"],
          ["Deploy", onOff(a.deploy)],
          ["Notifications", onOff(a.steps.notify ?? true)],
        ]} />
      </ReviewCard>
      <div className="stackg" style={{ gap: 4 }}>
        <label className="check" htmlFor="wz-remember">
          <input
            id="wz-remember" type="checkbox"
            checked={state.remember} onChange={(e) => dispatch({ type: "remember", on: e.target.checked })}
          />
          Use these choices for this project's next builds
        </label>
        <span className="help">Next time you start a build here, the wizard begins with these choices.</span>
      </div>
      {state.error && (
        <InfoBlock tone="bad">
          <b>The build did not start</b>
          <p>{state.error}</p>
        </InfoBlock>
      )}
    </div>
  )
}
