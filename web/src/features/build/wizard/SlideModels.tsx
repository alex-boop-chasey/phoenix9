// Slide 4: the model and tools of each AI step that will run, collapsed, with the preset's values shown.
import { Skeleton } from "@/components/ui/skeleton"
import { AiStepEditor } from "@/features/settings/AiStepEditor"

import { enabledAiSteps } from "./model"
import type { SlideProps } from "./Wizard"

/** One collapsed editor per enabled AI step. */
export function SlideModels({ state, dispatch, plan, baseline }: SlideProps) {
  if (!plan) return <Skeleton className="h-40 w-full" />
  const steps = enabledAiSteps(plan.steps)
  if (!steps.length) return <p className="text-sm text-muted-foreground">No AI steps are on.</p>
  const preset = (name: string) => (baseline?.steps.find((s) => s.name === name)?.ai ?? {}) as Record<string, unknown>
  const models = [...new Set((baseline?.steps ?? []).flatMap((s) => {
    const ai = s.ai ?? {}
    return [ai.model, ...(Array.isArray(ai.fallback_models) ? ai.fallback_models : [])].filter((m): m is string => typeof m === "string" && !!m)
  }))]
  return (
    <ul className="divide-y rounded-md border">
      {steps.map((s) => {
        const model = state.answers.ai[`steps.${s.name}.model`] || preset(s.name).model
        return (
          <li key={s.name} className="p-3" data-step={s.name}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-medium">{s.title}</span>
              <span className="min-w-0 break-all text-sm text-muted-foreground">Model: {String(model || "default")}</span>
            </div>
            <AiStepEditor
              step={s.name} title={s.title} effective={preset(s.name)} source={{}} models={models}
              changes={state.answers.ai} onChange={(key, value) => dispatch({ type: "ai", key, value })}
            />
          </li>
        )
      })}
    </ul>
  )
}
