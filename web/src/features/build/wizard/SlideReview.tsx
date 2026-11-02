// Slide 7: the plan as a readable list plus every choice, the "remember" box, and any submit error.
import { InfoBlock } from "@/components/InfoBlock"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

import { ON_FAILURE } from "@/features/settings/BuildSection"

import { planInOrder, presetLabel } from "./model"
import type { SlideProps } from "./Wizard"

const onOff = (on: boolean) => (on ? "On" : "Off")

/** Everything that will happen, in order. */
export function SlideReview({ state, dispatch, plan, presets, specs }: SlideProps) {
  const a = state.answers
  if (!plan) return <Skeleton className="h-40 w-full" />
  const spec = specs.find((s) => s.path === a.spec)
  const what = a.source === "spec" ? `${spec?.title ?? a.spec} (${a.spec})` : `Brief: ${a.brief.trim()}`
  const facts: [string, string][] = [
    ["What", what],
    ["Preset", presetLabel(a, presets)],
    ["Tries per task", String(a.maxTries)],
    ["When a task still fails", ON_FAILURE.find((o) => o.value === a.onFailure)?.label ?? a.onFailure],
    ["Merge", a.merge === "ask" ? "Ask me first" : "Merge automatically"],
    ["Deploy", onOff(a.deploy)],
    ["Notifications", onOff(a.steps.notify ?? true)],
  ]
  return (
    <div className="stackg">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]" style={{ margin: 0 }}>
        {facts.map(([k, v]) => (
          <div key={k} className="contents" data-fact={k}>
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="mb-1 min-w-0 break-words sm:mb-0">{v}</dd>
          </div>
        ))}
      </dl>
      <section className="stackg" aria-label="Plan">
        <h3 className="h3">The plan</h3>
        {planInOrder(plan.steps).map((g) => (
          <div key={g.group} className="space-y-1">
            <h4 className="text-sm font-medium text-muted-foreground">{g.title}</h4>
            <ol className="ml-4 list-decimal text-sm">
              {g.steps.map((s) => (
                <li
                  key={s.name} data-step={s.name} data-on={String(s.on)}
                  className={cn(!s.on && "text-muted-foreground line-through")}
                >
                  {s.title}{!s.on && <span className="sr-only"> (off)</span>}
                </li>
              ))}
            </ol>
          </div>
        ))}
      </section>
      <label className="rrow nodot" htmlFor="wz-remember" style={{ border: "1px solid var(--line)" }}>
        <span className="rt"><b>Remember these as this project's defaults</b></span>
        <input
          id="wz-remember" type="checkbox" className="switch" role="switch" aria-label="Remember these as this project's defaults"
          checked={state.remember} onChange={(e) => dispatch({ type: "remember", on: e.target.checked })}
        />
      </label>
      {state.error && (
        <InfoBlock tone="bad">
          <b>The build did not start</b>
          <p>{state.error}</p>
        </InfoBlock>
      )}
    </div>
  )
}
