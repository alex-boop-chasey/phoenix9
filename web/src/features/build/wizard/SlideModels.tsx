// Slide 4: one card per AI step that is switched on; each opens to its model, fallbacks, tools and limits.
import { Skeleton } from "@/components/ui/skeleton"

import { AiCard } from "./AiCard"
import { aiCards } from "./model"
import type { SlideProps } from "./Wizard"

/** The AI step cards, with defaults from the preset's (Phoenix settings') values. */
export function SlideModels({ state, dispatch, plan, baseline }: SlideProps) {
  if (!plan) return <Skeleton className="h-40 w-full" />
  const steps = aiCards(plan.steps, state.answers)
  const preset = (name: string) => (baseline?.steps.find((s) => s.name === name)?.ai ?? {}) as Record<string, unknown>
  const models = (baseline?.steps ?? []).flatMap((s) => {
    const ai = s.ai ?? {}
    return [ai.model, ...(Array.isArray(ai.fallback_models) ? ai.fallback_models : [])].filter((m): m is string => typeof m === "string")
  })
  return (
    <div className="stackg">
      <p className="small">Only the AI steps switched on for this build are listed. Open one to change its model and tools.</p>
      {steps.length === 0 && <p className="small">No AI steps are on.</p>}
      <div className="stackg">
        {steps.map((s) => (
          <AiCard
            key={s.name} step={s} preset={preset(s.name)} models={models} edits={state.answers.ai}
            onEdit={(key, value) => dispatch({ type: "ai", key, value })}
          />
        ))}
      </div>
    </div>
  )
}
