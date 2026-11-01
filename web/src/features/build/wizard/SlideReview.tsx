// Slide 7: the plan as a readable list plus every choice, the "remember" box, and any submit error.
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
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
    <div className="space-y-6">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
        {facts.map(([k, v]) => (
          <div key={k} className="contents" data-fact={k}>
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="mb-1 min-w-0 break-words sm:mb-0">{v}</dd>
          </div>
        ))}
      </dl>
      <section className="space-y-3" aria-label="Plan">
        <h3 className="font-semibold">The plan</h3>
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
      <div className="flex min-h-11 items-center gap-2">
        <Checkbox
          id="wz-remember" checked={state.remember}
          onCheckedChange={(v) => dispatch({ type: "remember", on: v === true })}
        />
        <Label htmlFor="wz-remember" className="font-normal">Remember these as this project's defaults</Label>
      </div>
      {state.error && (
        <Alert variant="destructive">
          <AlertTitle>The build did not start</AlertTitle>
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      )}
    </div>
  )
}
