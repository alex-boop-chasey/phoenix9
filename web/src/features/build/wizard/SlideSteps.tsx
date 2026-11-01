// Slide 3: switch steps on or off; the preset becomes Custom, and the resolver's reasons and errors show.
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"
import { StepToggleList } from "@/features/settings/StepToggleList"

import { presetLabel, shownStepValues } from "./model"
import type { SlideProps } from "./Wizard"

/** The editable step list. */
export function SlideSteps({ state, dispatch, plan, presets }: SlideProps) {
  const a = state.answers
  if (!plan) return <Skeleton className="h-40 w-full" />
  const forced = plan.steps.filter((s) => !s.on && s.reason.startsWith("needs "))
  return (
    <div className="space-y-4">
      <p className="text-sm">
        Preset: <span className="font-medium">{presetLabel(a, presets)}</span>
        {a.preset === "custom" && <span className="text-muted-foreground"> (changing a step makes the preset Custom)</span>}
      </p>
      {a.source === "brief" && (
        <p className="text-sm text-muted-foreground">The Planner stays on because you wrote a brief.</p>
      )}
      {plan.errors.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>These steps can't run together</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">{plan.errors.map((e) => <li key={e}>{e}</li>)}</ul>
          </AlertDescription>
        </Alert>
      )}
      {forced.length > 0 && (
        <Alert>
          <AlertTitle>Switched off by another step</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">{forced.map((s) => <li key={s.name}>{s.title}: {s.reason}</li>)}</ul>
          </AlertDescription>
        </Alert>
      )}
      <StepToggleList
        steps={plan.steps} values={shownStepValues(plan.steps, a)}
        onChange={(name, on) => dispatch({ type: "step", name, on })}
      />
    </div>
  )
}
